"""Operator-controlled source pulls with private raw storage and fail-closed ACL gates."""
from __future__ import annotations

import argparse
import fcntl
import hashlib
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import time

from dotenv import load_dotenv

from contextledger.document_updates import DocumentUpdates
from contextledger.source_adapters import SourceError, adapter_for, SOURCES
from contextledger.store import connect
from contextledger.tool_api import build_service


class SourceSync:
    def __init__(self, service, updates, raw_path):
        self.service, self.updates, self.raw_path = service, updates, Path(raw_path)
        self.raw_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.raw_path.is_symlink():
            raise ValueError("source raw database must not be a symlink")
        with self.raw_db() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS source_records (
                corpus TEXT, source TEXT, resource_id TEXT, observed_at TEXT,
                document_json TEXT NOT NULL, disposition TEXT NOT NULL,
                PRIMARY KEY(corpus,source,resource_id,observed_at))""")
        self.raw_path.chmod(0o600)
        # Permission gates survive content-index rebuilds, beside identities.
        with service.identities.db() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS live_source_guards (
                corpus TEXT, source TEXT, state TEXT NOT NULL, expires_at REAL NOT NULL,
                PRIMARY KEY(corpus,source))""")

    def raw_db(self):
        return sqlite3.connect(self.raw_path, timeout=30)

    def gate(self, corpus, source, state, expires=0):
        with self.service.identities.db() as db:
            db.execute("INSERT INTO live_source_guards VALUES (?,?,?,?) ON CONFLICT(corpus,source) DO UPDATE SET state=excluded.state,expires_at=excluded.expires_at",
                       (corpus, source, state, expires))

    def sync(self, actor_id, config, *, adapter=None):
        # Do not hold the content-index publication lock while waiting for its
        # worker. A separate per-source lock serialises source refreshes.
        name = hashlib.sha256(json.dumps([config.get("corpus"), config.get("source")]).encode()).hexdigest()
        fd = os.open(self.raw_path.parent / ("source-" + name + ".lock"), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise SourceError("source_refresh_already_running") from None
            return self._sync(actor_id, config, adapter=adapter)
        finally:
            os.close(fd)

    def _sync(self, actor_id, config, *, adapter=None):
        actor = self.service.current(actor_id)
        if actor.role != "admin":
            raise PermissionError("administrator source sync required")
        corpus, source = config.get("corpus"), config.get("source")
        if not isinstance(corpus, str) or not corpus or source not in SOURCES or config.get("enabled") is not True:
            raise ValueError("explicitly enabled source and corpus required")
        limit, ttl = config.get("max_documents", 100), config.get("acl_ttl_seconds", 300)
        if type(limit) is not int or not 1 <= limit <= 1000 or type(ttl) is not int or not 60 <= ttl <= 3600:
            raise ValueError("documents must be 1..1000; permission TTL must be 60..3600 seconds")
        with connect(self.service.index.db_path) as db:
            known = {r[0] for r in db.execute("SELECT principal_id FROM principals WHERE corpus=?", (corpus,))}
        if not known:
            raise ValueError("bootstrap explicit source principals and bindings in this corpus first")
        started = time.time()
        observed = datetime.now(timezone.utc).isoformat()
        self.gate(corpus, source, "refreshing")
        self.service.record(actor, "source_sync_requested", corpus=corpus, source=source)
        reader = None
        try:
            reader = adapter or adapter_for(config)
            if not set(reader.mapping.values()) <= known:
                raise SourceError("source_principal_mapping_unknown")
            records = {}
            for doc in reader.records():
                self.service.fence(actor)
                if len(records) >= limit or doc.resource_id in records:
                    raise SourceError("source_document_budget_or_duplicate")
                disposition = "publishable" if (doc.permission_state == "verified_subset" and doc.text.strip()
                    and len(doc.text) <= 24000 and doc.title.strip() and len(doc.title) <= 1000
                    and len(doc.resource_id) <= 220 and len(doc.revision) <= 256) else "quarantined"
                encoded = json.dumps(doc.serializable(), ensure_ascii=False)
                if self.raw_path.stat().st_size + len(encoded.encode()) > 256 * 1024 * 1024:
                    raise SourceError("source_raw_storage_budget_exceeded")
                with self.raw_db() as db:
                    db.execute("INSERT INTO source_records VALUES (?,?,?,?,?,?)",
                        (corpus, source, doc.resource_id, observed, encoded, disposition))
                records[doc.resource_id] = (doc, disposition)
            # A complete scoped enumeration is required before restoring access.
            # Missing resources lose ACL; this is not a full deletion/history API.
            prefix = "live:" + source + ":"
            with connect(self.service.index.db_path) as db:
                old = {r["doc_id"]: dict(r) for r in db.execute("SELECT * FROM documents WHERE corpus=? AND source=?", (corpus, source)) if r["doc_id"].startswith(prefix)}
            bodies, quarantined = [], 0
            for resource_id, (doc, disposition) in records.items():
                doc_id = prefix + resource_id
                prior = old.pop(doc_id, None)
                if disposition == "quarantined":
                    quarantined += 1
                    if prior and json.loads(prior["acl_json"]):
                        bodies.append(self.denial(prior))
                    continue
                if (prior and prior["text"] == doc.text and prior["title"] == doc.title
                        and sorted(json.loads(prior["acl_json"])) == doc.acl
                        and (config.get("project") is None or json.loads(prior["extra_json"]).get("project") == config["project"])
                        and json.loads(prior["extra_json"]).get("source_revision") == doc.revision):
                    continue
                body = {"corpus": corpus, "doc_id": doc_id, "source": source, "title": doc.title,
                    "text": doc.text, "acl": doc.acl,
                    "expected_version": prior["version"] if prior else None,
                    "source_metadata": {"source_resource_id": resource_id, "source_url": doc.source_url,
                        "source_revision": doc.revision, "source_acl_observed_at": observed,
                        "source_acl_basis": doc.permission_basis}}
                if doc.updated_at:
                    body["source_updated_at"] = doc.updated_at
                if config.get("project") is not None:
                    body["project"] = config["project"]
                bodies.append(body)
            bodies.extend(self.denial(p) for p in old.values() if json.loads(p["acl_json"]))
            jobs = []
            # Sequential publication: the existing update service has a corpus
            # gate, not a batch commit. Keep our source guard closed throughout.
            for body in bodies:
                self.service.fence(actor)
                job = self.updates.submit(actor_id, body)
                self.updates.start()
                final = self.updates.wait(actor_id, job["id"], timeout=120)
                if final["state"] != "ready":
                    raise SourceError("source_index_publication_incomplete")
                jobs.append(job["id"])
            self.service.fence(actor)
            if time.time() >= started + ttl:
                raise SourceError("source_permission_snapshot_expired_during_sync")
            self.gate(corpus, source, "ready", started + ttl)
            event = self.service.record(actor, "source_sync_completed", corpus=corpus, source=source,
                observed_at=observed, submitted=len(jobs), quarantined=quarantined,
                scope="complete configured scope; verified mapped permission subset; not live revocation")
            return {"state": "ready", "observed_at": observed, "acl_expires_at": started + ttl,
                    "submitted": len(jobs), "quarantined": quarantined, "request_id": event["request_id"]}
        except Exception as error:
            self.gate(corpus, source, "blocked")
            code = str(error) if isinstance(error, SourceError) else type(error).__name__
            self.service.record(actor, "source_sync_failed", corpus=corpus, source=source,
                                decision="blocked", error_type=code)
            raise SourceError(code) from None
        finally:
            if reader is not None and hasattr(getattr(reader, "http", None), "close"):
                reader.http.close()

    @staticmethod
    def denial(prior):
        return {"corpus": prior["corpus"], "doc_id": prior["doc_id"], "source": prior["source"],
                "title": prior["title"], "text": prior["text"], "acl": [], "expected_version": prior["version"]}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Explicit operator source sync; never invoked by an agent tool")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--security-dir", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--source", choices=sorted(SOURCES), required=True)
    parser.add_argument("--admin-id", required=True)
    parser.add_argument("--interval", type=int, default=0, help="0 = one pull; >=30 = explicit periodic operator process")
    args = parser.parse_args(argv)
    if args.interval and not 30 <= args.interval <= 3600:
        parser.error("interval must be 0 or 30..3600 seconds")
    if args.env_file:
        load_dotenv(args.env_file, override=True)
    configs = json.loads(args.config.read_text(encoding="utf-8"))
    config = configs.get(args.source)
    if not isinstance(config, dict) or config.get("source") != args.source:
        parser.error("source configuration missing or mismatched")
    service = build_service(args.out, args.security_dir)
    updates = DocumentUpdates(service.index, service.identities, service.audit, autostart=False)
    sync = SourceSync(service, updates, args.security_dir / "source-raw.sqlite")
    try:
        while True:
            try:
                print(json.dumps(sync.sync(args.admin_id, config), ensure_ascii=False), flush=True)
            except SourceError as error:
                print(json.dumps({"state": "blocked", "error_type": str(error)}), flush=True)
                if not args.interval:
                    return 1
            if not args.interval:
                return 0
            time.sleep(args.interval)
    finally:
        updates.close()


if __name__ == "__main__":
    raise SystemExit(main())
