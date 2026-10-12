"""Small OrgForge business-record fixture adapter and controlled replay.

No evaluation answers, causal labels or recurrence metadata enter model evidence.
ACL is a synthetic engineering/support split, never a claim of live platform ACL.
"""
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path
from contextledger.models import SourceDoc, CanonicalDoc, Chunk
from contextledger.store import content_hash

REVISION = "f2a1ab2ac94043f20ad4d15fc2bbc60c09332656"
FORBIDDEN = {"facts", "ground_truth", "causal_chain", "recurrence_of", "recurrence_gap_days", "answer", "expected_answer"}
TYPES = {"jira_tickets": "jira", "pr_registry": "github", "slack_threads": "slack",
         "confluence_pages": "confluence", "emails": "email", "zd_tickets": "zendesk"}


def assert_business_only(value):
    if isinstance(value, dict):
        if FORBIDDEN.intersection(value):
            raise ValueError("Evaluation-only fields cannot be evidence")
        for item in value.values():
            assert_business_only(item)
    elif isinstance(value, list):
        for item in value:
            assert_business_only(item)


def parse_time(value):
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        # Date-only carries day precision; don't silently invent an exact event time.
        return parsed.replace(tzinfo=parsed.tzinfo or timezone.utc)
    except ValueError:
        return None


def load_records(path):
    records = [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]
    for record in records:
        assert_business_only(record)
    return records


def source_documents(records, *, cutoff=None, final=True):
    """Split source descriptions/comments/final states; never backdate final fields."""
    limit = parse_time(cutoff) if cutoff else None
    if cutoff and limit is None:
        raise ValueError("invalid replay cutoff")
    output = {}
    for record in records:
        assert_business_only(record)
        payload = record["payload"]
        native = record["record_kind"] == "native_business_record"
        source = TYPES.get(record.get("source_type")) if native else payload.get("doc_type")
        source = "github" if source == "pr" else source
        if source not in set(TYPES.values()):
            continue
        resource = record["resource_id"]
        root = ("native:" if native else "artifact:") + resource
        title = str(payload.get("title") or payload.get("subject") or resource)
        created = payload.get("created_at") if native else payload.get("timestamp")
        created = created or payload.get("timestamp") or payload.get("ts") or payload.get("date")
        if limit and (not parse_time(created) or parse_time(created) > limit):
            continue  # Unknown observation cannot be safely included in a past cut.
        text = str(payload.get("description") or payload.get("content") or payload.get("body") or payload.get("text") or title)
        links = [str(payload.get(k) or "") for k in ("linked_ticket", "ticket_id", "related_incident")]
        # Snapshot links have unknown addition time, so only include them in final mode.
        if final:
            links += list(map(str, payload.get("linked_prs") or []))
            if any(links):
                text += "\nLinked source records: " + ", ".join(filter(None, links))
        if native and not final:
            # Native descriptions are final snapshot text, not known initial versions.
            # Replay exposes dated comments under a stub parent, never future prose.
            text = "Source record exists; final snapshot description is not available at this replay cut."
        metadata = {"record_type": "description" if native else "artifact",
            "native_resource_id": resource, "radar_root_doc_id": root,
            "source_revision": REVISION, "origin_locator": record.get("json_pointer") or record.get("source_file"),
            "event_time": created, "source_date": payload.get("date"), "source_day": payload.get("day"), "source_timestamp": payload.get("timestamp"), "time_precision": "day" if created and len(str(created)) == 10 else "timestamp",
            "observed_at": cutoff if cutoff else "final offline snapshot (exact observation time unknown)",
            "reconstructed_for_replay": not final, "fixture_acl": True, "radar_snapshot_only": native}
        day = payload.get("day") if not native else None
        output[root] = SourceDoc("orgforge", root, source, resource + " · " + title, resource + "\n" + text,
                                 day if type(day) is int and 0 <= day <= 60 else None, created, "engineering", [], metadata)
        if not native:
            continue
        for index, comment in enumerate(payload.get("comments") or []):
            when = comment.get("timestamp") or comment.get("date") or comment.get("ts")
            if limit and (not parse_time(when) or parse_time(when) > limit):
                continue
            cid = root + ":comment:" + str(index)
            content = str(comment.get("text") or comment.get("body") or "")
            if not content:
                continue
            meta = {**metadata, "record_type": "comment", "event_time": when,
                    "actor": comment.get("author"), "verdict": comment.get("verdict")}
            output[cid] = SourceDoc("orgforge", cid, source, resource + " · comment " + str(index),
                resource + "\n" + content, None, when, "engineering", [], meta)
        if final and payload.get("status"):
            cid = root + ":state"
            # Final state is observed in a snapshot; no event timestamp is available.
            meta = {**metadata, "record_type": "native_state", "native_status": payload["status"],
                    "event_time": None, "time_precision": "unknown"}
            output[cid] = SourceDoc("orgforge", cid, source, resource + " · native state",
                resource + "\nNative snapshot status: " + str(payload["status"]) + ". State transition time is unknown.",
                None, None, "engineering", [], meta)
    return list(output.values())


def canonical_documents(documents):
    """Deterministic paragraph chunks for replay, not production MiniLM tokenization."""
    canonical, chunks = [], []
    for doc in documents:
        acl = ["radar:engineering", "radar:support"] if doc.source in {"zendesk", "email"} else ["radar:engineering"]
        parts = [doc.text[n:n+1800] for n in range(0, len(doc.text), 1800)]
        own = [Chunk(doc.doc_id + ":chunk:" + str(i), doc.corpus, doc.doc_id, i, part) for i, part in enumerate(parts)]
        digest = content_hash(doc.text)
        canonical.append(CanonicalDoc(doc.corpus, doc.doc_id, doc.source, doc.title, doc.text, doc.day,
            doc.ts, doc.dept, doc.actors, acl, "explicit-synthetic-radar-fixture-acl", digest[:12], digest,
            doc.extra, [c.chunk_id for c in own]))
        chunks.extend(own)
    return canonical, chunks
