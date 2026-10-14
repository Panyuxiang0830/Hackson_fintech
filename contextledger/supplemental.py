"""Add isolated, provenance-labelled corpora to an existing Part A store."""

from __future__ import annotations

import hashlib
import gzip
import json
import shutil
import struct
import time
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from huggingface_hub import HfApi, snapshot_download

from contextledger.files import extract_text
from contextledger.models import Principal, SourceDoc
from contextledger.pipeline import _canonical
from contextledger.processors import chunk_document
from contextledger.store import connect, content_hash, insert_documents, insert_principals, write_raw_jsonl

PRIVACY_REPO = "TonicAI/Privacy-Bench"
DEFAULT_WORLDS = ("camille_nike", "grace_deere_company")
JIRA_RECORD = "15719919"


@dataclass
class ImportBatch:
    corpus: str
    label: str
    metadata: dict
    principals: list[Principal] = field(default_factory=list)
    records: list[tuple[SourceDoc, list[str], str]] = field(default_factory=list)


def _json(path: Path, default=None):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def _iso(value) -> str | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=value.tzinfo or timezone.utc).isoformat()
    try:
        return datetime.fromtimestamp(float(value), timezone.utc).isoformat()
    except (ValueError, TypeError):
        return str(value)


def privacy_batch(root: Path, world: str, revision: str) -> ImportBatch:
    corpus = f"privacy_{world}"
    task = root / "tasks" / world
    slack = task / "slack"
    roster = _json(root / "ground_truth" / world / "characters.json", {})
    users = _json(slack / "users.json", [])
    file_info = _json(task / "drive" / "files.json", {"files": []}).get("files", [])
    batch = ImportBatch(corpus, f"PrivacyBench · {world} (synthetic)", {
        "dataset": PRIVACY_REPO, "revision": revision, "world": world,
        "url": f"https://huggingface.co/datasets/{PRIVACY_REPO}",
        "synthetic": True, "license": "CC-BY-4.0",
        "scope": "All Slack exports and Drive files in this selected world; email excluded.",
        "identity_basis": "Upstream character roster resolves email aliases and Slack IDs; it is not indexed.",
        "acl_basis": "Slack export members; Drive user/domain/anyone permissions. Unresolved groups deny access.",
    })
    principals = {}
    slack_ids = {}
    emails = {}
    principal_emails: dict[str, set[str]] = defaultdict(set)

    def add(key: str, name: str, role: str = "member") -> str:
        pid = f"{corpus}:{key}"
        principals.setdefault(pid, Principal(corpus, pid, name, role, world))
        return pid

    for key, character in roster.items():
        pid = add(key, character.get("canonical_name") or key)
        for address in character.get("emails", []):
            email = (address.get("value") if isinstance(address, dict) else address).lower()
            emails[email] = pid
            principal_emails[pid].add(email)
        for handle in character.get("slack_handles", []) + character.get("alt_slack_handles", []):
            slack_ids[handle] = pid
    inactive = set()
    for user in users:
        profile = user.get("profile") or {}
        email = str(profile.get("email") or "").lower()
        pid = slack_ids.get(user["id"]) or emails.get(email) or add(user["id"], user.get("real_name") or user.get("name") or user["id"])
        slack_ids[user["id"]] = pid
        if email:
            emails[email] = pid
            principal_emails[pid].add(email)
        if user.get("deleted"):
            inactive.add(pid)
    for info in file_info:
        for permission in info.get("permissions", []):
            email = str(permission.get("emailAddress") or "").lower()
            if permission.get("type") == "user" and email and email not in emails:
                pid = add(f"email:{email}", permission.get("displayName") or email)
                emails[email] = pid
                principal_emails[pid].add(email)
    outside = add("outside", "Outside workspace", "outsider")
    channels = []
    for kind in ("channels", "groups", "dms", "mpims"):
        channels.extend((kind, channel) for channel in _json(slack / f"{kind}.json", []))
    for kind, channel in channels:
        name = channel.get("name") or channel["id"]
        folder = slack / name
        if not folder.is_dir():
            folder = slack / channel["id"]
        allowed = sorted({slack_ids[member] for member in channel.get("members", []) if member in slack_ids and slack_ids[member] not in inactive})
        threads = defaultdict(list)
        for day_file in sorted(folder.glob("*.json")):
            for message in _json(day_file, []):
                if not message.get("ts"):
                    continue
                root_ts = message.get("thread_ts") or message["ts"]
                threads[str(root_ts)].append(message)
        for root_ts, messages in sorted(threads.items()):
            messages.sort(key=lambda message: float(message["ts"]))
            parts = []
            actors = set()
            for message in messages:
                pid = slack_ids.get(message.get("user"))
                actor = principals[pid].name if pid else message.get("user") or "Unknown sender"
                actors.add(actor)
                text = message.get("text") or ""
                if text.strip():
                    parts.append(f"[{_iso(message['ts'])}] {actor}: {text}")
            if not parts:
                continue
            title = f"#{name} · {(messages[0].get('text') or 'Conversation').splitlines()[0][:90]}"
            doc = SourceDoc(corpus, f"{channel['id']}:{root_ts}", "slack", title, "\n".join(parts), None,
                _iso(messages[0]["ts"]), world, sorted(actors), {
                    "channel_id": channel["id"], "channel": name, "channel_type": kind,
                    "thread_ts": root_ts, "members": channel.get("members", []), "message_count": len(messages),
                    "updated_at": _iso(messages[-1]["ts"]),
                    "source_url": f"https://huggingface.co/datasets/{PRIVACY_REPO}/tree/{revision}/tasks/{world}/slack",
                }, {"channel": channel, "channel_type": kind, "messages": messages})
            batch.records.append((doc, allowed, f"slack_export_{kind}_members"))
    for info in file_info:
        if info.get("trashed"):
            continue
        name = info["name"]
        path = task / "drive" / name
        if Path(name).name != name or name in {".", ".."}:
            raise ValueError("Drive filename escapes its export directory")
        binary = path.read_bytes()
        if info.get("md5Checksum") and hashlib.md5(binary).hexdigest() != info["md5Checksum"]:
            raise ValueError(f"Drive checksum mismatch: {name}")
        text = extract_text(path)
        if not text:
            raise ValueError(f"Drive text extraction produced no text: {name}")
        allowed = set()
        unresolved = []
        for permission in info.get("permissions", []):
            if permission.get("deleted") or permission.get("role") not in {"owner", "organizer", "fileOrganizer", "writer", "commenter", "reader"}:
                continue
            kind = permission.get("type")
            if kind == "user":
                pid = emails.get(str(permission.get("emailAddress") or "").lower())
                if pid:
                    allowed.add(pid)
            elif kind == "anyone":
                allowed.update(principals)
            elif kind == "domain":
                domain = str(permission.get("domain") or "").lower()
                if domain:
                    allowed.update(pid for pid, aliases in principal_emails.items() if any(email.endswith("@" + domain) for email in aliases))
            else:
                unresolved.append(permission)
        doc = SourceDoc(corpus, info["id"], "google_drive", name, text, None,
            info.get("modifiedTime"), world, [owner.get("displayName") or owner.get("emailAddress", "") for owner in info.get("owners", [])], {
                "mime_type": info.get("mimeType"), "parents": info.get("parents", []),
                "created_at": info.get("createdTime"), "updated_at": info.get("modifiedTime"),
                "permissions": info.get("permissions", []), "unresolved_permissions": unresolved,
                "binary_sha256": hashlib.sha256(binary).hexdigest(), "raw_file": str(path),
                "source_url": f"https://huggingface.co/datasets/{PRIVACY_REPO}/blob/{revision}/tasks/{world}/drive/{name}",
                "simulated_platform_url": info.get("webViewLink"),
            }, info)
        batch.records.append((doc, sorted(allowed), "drive_export_permissions"))
    batch.principals = list(principals.values())
    batch.metadata["outside_principal"] = outside
    return batch


def download_privacy(worlds: list[str]) -> list[ImportBatch]:
    revision = HfApi().dataset_info(PRIVACY_REPO).sha
    patterns = []
    for world in worlds:
        patterns.extend([f"tasks/{world}/slack/**", f"tasks/{world}/drive/**", f"ground_truth/{world}/characters.json"])
    root = Path(snapshot_download(PRIVACY_REPO, repo_type="dataset", revision=revision, allow_patterns=patterns, max_workers=6))
    return [privacy_batch(root, world, revision) for world in worlds]


def read_bson(stream):
    from bson import BSON

    while True:
        header = stream.read(4)
        if not header:
            return
        if len(header) != 4:
            raise ValueError("truncated BSON length")
        size = struct.unpack("<i", header)[0]
        if size == -1:
            yield None
            continue
        if not 5 <= size <= 64 * 1024 * 1024:
            raise ValueError(f"invalid BSON record length: {size}")
        payload = stream.read(size - 4)
        if len(payload) != size - 4:
            raise ValueError("truncated BSON record")
        yield BSON(header + payload).decode()


def archive_records(stream):
    if stream.read(4) != struct.pack("<I", 0x8199E26D):
        raise ValueError("not a mongodump archive")
    records = iter(read_bson(stream))
    header = next(records, None)
    if not header or header.get("version") != "0.1":
        raise ValueError("unsupported mongodump archive version")
    for metadata in records:
        if metadata is None:
            break
    else:
        raise ValueError("truncated mongodump prelude")
    for header in records:
        if not header or not header.get("db") or not header.get("collection"):
            raise ValueError("invalid mongodump namespace")
        namespace = f"{header['db']}.{header['collection']}"
        for record in records:
            if record is None:
                break
            yield namespace, record
        else:
            raise ValueError("truncated mongodump block")


def sample_public_jira(cache_dir: Path, limit: int) -> tuple[list[tuple[str, dict]], dict]:
    import requests
    from bson import json_util
    from contextledger.remote_zip import RemoteZipReader

    if limit <= 0:
        raise ValueError("Jira sample limit must be positive")
    cache_dir.mkdir(parents=True, exist_ok=True)
    sample_path = cache_dir / f"public_jira_{JIRA_RECORD}_{limit}.jsonl"
    metadata_path = sample_path.with_suffix(".meta.json")
    if sample_path.exists() and metadata_path.exists():
        metadata = _json(metadata_path)
        if hashlib.sha256(sample_path.read_bytes()).hexdigest() == metadata.get("sample_sha256"):
            rows = [json_util.loads(line) for line in sample_path.read_text().splitlines()]
            if len(rows) == limit:
                return [(row["namespace"], row["issue"]) for row in rows], metadata
    started = time.monotonic()
    response = requests.get(f"https://zenodo.org/api/records/{JIRA_RECORD}", timeout=30)
    response.raise_for_status()
    asset = response.json()["files"][0]
    issues = []
    member = "ThePublicJiraDataset/3. DataDump/mongodump-JiraReposAnon.archive"
    with RemoteZipReader(asset["links"]["self"], asset["size"]) as remote:
        with zipfile.ZipFile(remote) as archive:
            with archive.open(member) as compressed, gzip.GzipFile(fileobj=compressed) as stream:
                for namespace, issue in archive_records(stream):
                    if issue.get("key") and isinstance(issue.get("fields"), dict):
                        issues.append((namespace, issue))
                        if len(issues) % 250 == 0:
                            print(f"Public Jira: sampled {len(issues)}/{limit}; fetched {remote.downloaded / 1024**2:.1f} MiB", flush=True)
                        if len(issues) == limit:
                            break
                    if remote.downloaded > 128 * 1024**2:
                        raise RuntimeError("Jira sample exceeded its 128 MiB download budget")
        downloaded = remote.downloaded
    if len(issues) != limit:
        raise ValueError(f"requested {limit} Jira issues, found {len(issues)}")
    payload = "".join(json_util.dumps({"namespace": namespace, "issue": issue}) + "\n" for namespace, issue in issues)
    metadata = {"dataset": "The Public Jira Dataset", "revision": f"zenodo:{JIRA_RECORD}:{asset['checksum']}",
        "url": f"https://zenodo.org/records/{JIRA_RECORD}", "synthetic": False, "license": "CC-BY-4.0",
        "scope": f"First {limit} issue records in upstream mongodump stream order; not a random or complete corpus sample.",
        "archive_member": member, "archive_bytes": asset["size"], "archive_checksum": asset["checksum"],
        "downloaded_bytes": downloaded, "sample_seconds": round(time.monotonic() - started, 3),
        "sample_sha256": content_hash(payload), "source_counts": dict(Counter(namespace for namespace, _ in issues)),
        "acl_basis": "Public Jira data; no native private-project permissions are present."}
    sample_path.write_text(payload, encoding="utf-8")
    metadata_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return issues, metadata


def _plain(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        if value.get("text"):
            return str(value["text"])
        return " ".join(_plain(item) for item in value.get("content", []))
    if isinstance(value, list):
        return "\n".join(_plain(item) for item in value)
    return str(value)


def jira_batch(namespace: str, issues: list[dict], metadata: dict) -> ImportBatch:
    repository = namespace.split(".", 1)[-1]
    corpus = "publicjira_" + "".join(char.lower() if char.isalnum() else "_" for char in repository)
    reader = Principal(corpus, f"{corpus}:reader", f"{repository} public reader", "public_reader", repository)
    batch = ImportBatch(corpus, f"Public Jira · {repository} (sample)", dict(metadata), [reader])
    batch.metadata["namespace"] = namespace
    for issue in issues:
        fields = issue["fields"]
        def named(key):
            value = fields.get(key)
            return value.get("name") if isinstance(value, dict) else value
        comments = fields.get("comments")
        if comments is None:
            comments = (fields.get("comment") or {}).get("comments", [])
        histories = (issue.get("changelog") or {}).get("histories", [])
        key = issue["key"]
        parts = [f"{key}: {fields.get('summary') or key}", f"Status: {named('status')}",
            f"Type: {named('issuetype')} | Priority: {named('priority')}", _plain(fields.get("description"))]
        for comment in comments:
            author = comment.get("author") or {}
            parts.append(f"Comment [{comment.get('created')}] {author.get('displayName') or author.get('name') or 'anonymous'}: {_plain(comment.get('body'))}")
        for history in histories:
            for item in history.get("items", []):
                parts.append(f"Change [{history.get('created')}] {item.get('field')}: {item.get('fromString')} -> {item.get('toString')}")
        project = fields.get("project") or {}
        extra = {"repository": repository, "project": project, "status": fields.get("status"),
            "issue_type": fields.get("issuetype"), "priority": fields.get("priority"),
            "assignee": fields.get("assignee"), "reporter": fields.get("reporter"),
            "created_at": _iso(fields.get("created")), "updated_at": _iso(fields.get("updated")),
            "resolution": fields.get("resolution"), "resolution_date": _iso(fields.get("resolutiondate")),
            "labels": fields.get("labels", []), "components": fields.get("components", []),
            "issue_links": fields.get("issuelinks", []), "comments": comments, "changelog": histories,
            "comment_count": len(comments), "change_count": len(histories), "source_url": metadata["url"],
            "api_url": issue.get("self"), "native_private_acl_available": False}
        actors = [item.get("displayName") or item.get("name") or "anonymous" for item in (fields.get("assignee"), fields.get("reporter")) if isinstance(item, dict)]
        doc = SourceDoc(corpus, key, "jira", fields.get("summary") or key, "\n\n".join(part for part in parts if part), None,
            _iso(fields.get("updated")), project.get("name") or repository, actors, extra,
            json.loads(json.dumps(issue, default=str)))
        batch.records.append((doc, [reader.principal_id], "public_jira_source"))
    return batch


def augment(out_dir: Path, *, worlds: list[str] | None = None, jira_limit: int = 1000) -> dict:
    if not (out_dir / "canonical.sqlite").exists():
        raise ValueError("build the base Part A store before adding supplemental corpora")
    started = time.monotonic()
    summaries = []
    for batch in download_privacy(list(DEFAULT_WORLDS) if worlds is None else worlds):
        summaries.append(save_batch(out_dir, batch))
    issues, metadata = sample_public_jira(out_dir.parent / "datasets", jira_limit)
    grouped = defaultdict(list)
    for namespace, issue in issues:
        grouped[namespace].append(issue)
    for namespace, records in grouped.items():
        summaries.append(save_batch(out_dir, jira_batch(namespace, records, metadata)))
    report = {"seconds": round(time.monotonic() - started, 3), "corpora": summaries}
    (out_dir / "supplemental-report.json").write_text(json.dumps(report, indent=2, default=str) + "\n")
    return report


def save_batch(out_dir: Path, batch: ImportBatch) -> dict:
    canonical = []
    chunks = []
    seen = set()
    for doc, acl, basis in batch.records:
        if doc.corpus != batch.corpus or doc.doc_id in seen:
            raise ValueError("duplicate or mis-scoped supplemental document")
        seen.add(doc.doc_id)
        if doc.extra.get("raw_file"):
            source_path = Path(doc.extra["raw_file"])
            target = out_dir / "raw" / batch.corpus / "files" / source_path.name
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists() or hashlib.sha256(target.read_bytes()).hexdigest() != doc.extra["binary_sha256"]:
                shutil.copyfile(source_path, target)
            doc.extra["raw_file"] = str(target.resolve())
        doc.extra.update({"dataset": batch.metadata["dataset"], "dataset_revision": batch.metadata["revision"], "synthetic": batch.metadata["synthetic"]})
        pieces = chunk_document(doc)
        if not pieces:
            raise ValueError(f"no chunks for {doc.doc_id}")
        canonical.append(_canonical(doc, acl, basis, pieces))
        chunks.extend(pieces)
    fingerprint = content_hash(json.dumps([(doc.doc_id, doc.content_hash, doc.acl, doc.extra) for doc in canonical], sort_keys=True, default=str))
    for source in sorted({doc.source for doc, _, _ in batch.records}):
        records = [{"doc_id": doc.doc_id, "dataset": batch.metadata["dataset"], "revision": batch.metadata["revision"], "sha256": content_hash(json.dumps(doc.raw, sort_keys=True, default=str)), "payload": doc.raw} for doc, _, _ in batch.records if doc.source == source]
        write_raw_jsonl(out_dir / "raw" / batch.corpus / f"{source}.jsonl", records)
    connection = connect(out_dir / "canonical.sqlite")
    connection.execute("CREATE TABLE IF NOT EXISTS datasets (corpus TEXT PRIMARY KEY, label TEXT NOT NULL, metadata_json TEXT NOT NULL)")
    old = connection.execute("SELECT metadata_json FROM datasets WHERE corpus=?", (batch.corpus,)).fetchone()
    if old and json.loads(old[0]).get("fingerprint") == fingerprint:
        connection.close()
        print(f"{batch.corpus}: unchanged; {len(canonical)} documents", flush=True)
        return json.loads(old[0])
    batch.metadata.update({"fingerprint": fingerprint, "documents": len(canonical), "chunks": len(chunks),
        "principals": len(batch.principals), "by_source": dict(Counter(doc.source for doc in canonical)),
        "imported_at": datetime.now(timezone.utc).isoformat()})
    try:
        with connection:
            for table in ("docs_fts", "chunks", "documents", "role_source", "principals"):
                connection.execute(f"DELETE FROM {table} WHERE corpus=?", (batch.corpus,))
            insert_principals(connection, batch.principals, {})
            insert_documents(connection, canonical, chunks)
            connection.execute("INSERT OR REPLACE INTO datasets VALUES (?,?,?)", (batch.corpus, batch.label, json.dumps(batch.metadata, ensure_ascii=False, default=str)))
    finally:
        connection.close()
    vector_dir = out_dir / "vectors" / batch.corpus
    if vector_dir.exists():
        shutil.rmtree(vector_dir)
    refresh_manifest(out_dir)
    print(f"{batch.corpus}: imported {len(canonical)} documents, {len(chunks)} chunks", flush=True)
    return batch.metadata


def refresh_manifest(out_dir: Path) -> None:
    path = out_dir / "manifest.json"
    manifest = _json(path, {"part": "A"})
    connection = connect(out_dir / "canonical.sqlite")
    try:
        for table, key in (("documents", "documents"), ("chunks", "chunks"), ("principals", "principals")):
            manifest[key] = connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        manifest["by_source"] = {f"{row[0]}/{row[1]}": row[2] for row in connection.execute("SELECT corpus,source,COUNT(*) FROM documents GROUP BY corpus,source ORDER BY corpus,source")}
        manifest["supplemental"] = {row[0]: json.loads(row[1]) for row in connection.execute("SELECT corpus,metadata_json FROM datasets ORDER BY corpus")}
    finally:
        connection.close()
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")


def check_supplemental(connection, record) -> None:
    from contextledger.search import open_document, search

    if not connection.execute("SELECT 1 FROM sqlite_master WHERE name='datasets'").fetchone():
        return
    for dataset in connection.execute("SELECT corpus,metadata_json FROM datasets ORDER BY corpus").fetchall():
        corpus, metadata = dataset[0], json.loads(dataset[1])
        rows = connection.execute("SELECT doc_id,source,title,text,acl_json,extra_json FROM documents WHERE corpus=? ORDER BY doc_id", (corpus,)).fetchall()
        chunks = connection.execute("SELECT COUNT(*) FROM chunks WHERE corpus=?", (corpus,)).fetchone()[0]
        record(f"{corpus} inventory", len(rows) == metadata["documents"] and chunks == metadata["chunks"], f"documents={len(rows)} chunks={chunks}")
        for source in sorted({row["source"] for row in rows}):
            candidate = next((row for row in rows if row["source"] == source and json.loads(row["acl_json"])), None)
            if candidate is None:
                record(f"{corpus}/{source} retrieval", False, "no readable sample")
                continue
            principal = json.loads(candidate["acl_json"])[0]
            query = " ".join(candidate["text"].split()[:20])
            for mode in ("keyword", "vector", "hybrid"):
                result = search(connection, corpus=corpus, query=query, principal_id=principal, mode=mode)
                opened = open_document(connection, corpus=corpus, doc_id=candidate["doc_id"], principal_id=principal)
                record(f"{corpus}/{source} {mode}", bool(result["hits"]) and not result.get("error") and bool(opened), f"hits={len(result['hits'])} direct_open={opened is not None}")
        outsider = metadata.get("outside_principal")
        if outsider:
            private = [row for row in rows if outsider not in json.loads(row["acl_json"])]
            leaked = [row["doc_id"] for row in private if open_document(connection, corpus=corpus, doc_id=row["doc_id"], principal_id=outsider) is not None]
            record(f"{corpus} outside direct access", not leaked, f"checked={len(private)} leaked={len(leaked)}")
            outside_search = search(connection, corpus=corpus, query="project", principal_id=outsider, mode="hybrid")
            record(f"{corpus} outside search", not outside_search["hits"], f"hits={len(outside_search['hits'])}")
        files = [json.loads(row["extra_json"]) for row in rows if row["source"] == "google_drive"]
        if files:
            valid = all(Path(info["raw_file"]).exists() and hashlib.sha256(Path(info["raw_file"]).read_bytes()).hexdigest() == info["binary_sha256"] for info in files)
            record(f"{corpus} native files", valid, f"verified={len(files)} formats={sorted({Path(info['raw_file']).suffix for info in files})}")
        if corpus.startswith("publicjira_"):
            fields = [json.loads(row["extra_json"]) for row in rows]
            comments, changes = sum(info["comment_count"] for info in fields), sum(info["change_count"] for info in fields)
            record(f"{corpus} structured Jira", comments > 0 and changes > 0, f"comments={comments} changelog_entries={changes}")
