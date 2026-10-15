"""Durable administrator updates with automatic, guarded index publication."""

from dataclasses import asdict
from datetime import datetime
import json
from pathlib import Path
import threading
import time
import uuid

from qdrant_client import models as qm

from contextledger.retrieval.filtered_index import (
    IndexUnavailable, MODEL, _scan_snapshot, _sync_published_guard, live_source, now,
    payload_for, point_id, snapshot_document,
)
from contextledger.storage.index_lock import index_lock
from contextledger.storage.models import CanonicalDoc, SourceDoc
from contextledger.ingestion.processors import chunk_document
from contextledger.storage.store import connect, content_hash, insert_documents


class UpdateConflict(ValueError):
    pass


class DocumentUpdates:
    def __init__(self, index, identities, audit, *, embed=None, chunker=None, autostart=True):
        self.index, self.identities, self.audit = index, identities, audit
        self.db_path = Path(index.db_path)
        self.embed = embed or self._embed
        self.custom_embedding = embed is not None
        self.chunker = chunker or chunk_document
        self._wake, self._stop = threading.Event(), threading.Event()
        self._thread = None
        self._thread_lock = threading.Lock()
        with connect(self.db_path) as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS cl_update_jobs (
                    id TEXT PRIMARY KEY, corpus TEXT NOT NULL, doc_id TEXT NOT NULL,
                    actor_id TEXT NOT NULL, base_version TEXT, document_json TEXT NOT NULL,
                    state TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL, retry_at REAL NOT NULL DEFAULT 0,
                    error_type TEXT, generation TEXT);
                CREATE INDEX IF NOT EXISTS cl_updates_pending ON cl_update_jobs(corpus,state);
                CREATE UNIQUE INDEX IF NOT EXISTS cl_updates_resource ON cl_update_jobs(corpus,doc_id)
                    WHERE state IN ('queued','running','failed');
                CREATE TABLE IF NOT EXISTS cl_document_history (
                    corpus TEXT NOT NULL, doc_id TEXT NOT NULL, version TEXT NOT NULL,
                    document_json TEXT NOT NULL, chunks_json TEXT NOT NULL, saved_at TEXT NOT NULL,
                    PRIMARY KEY(corpus,doc_id,version));
            """)
            if "source_scope" not in {row[1] for row in db.execute("PRAGMA table_info(cl_update_jobs)")}:
                db.execute("ALTER TABLE cl_update_jobs ADD COLUMN source_scope TEXT")
        self.autostart = autostart
        if autostart:
            self.start()

    @staticmethod
    def _embed(texts):
        from contextledger.retrieval.vectors import _model
        return _model().encode(texts, normalize_embeddings=True, batch_size=64,
                               convert_to_numpy=True).tolist()

    def _admin(self, actor_id):
        actor = self.identities.get(actor_id)
        if actor is None or not actor.enabled or actor.role != "admin":
            raise PermissionError("administrator required")
        return actor

    def _record(self, actor_id, event_type, job_id, **details):
        self.audit.append({"request_id": uuid.uuid4().hex, "timestamp": now(),
            "event_type": event_type, "user_id": actor_id, "job_id": job_id,
            "decision": "allowed", "retrieved_document_ids": [], **details})

    @staticmethod
    def _text(value, name, maximum=256):
        if not isinstance(value, str) or not value.strip() or len(value) > maximum or "\x00" in value:
            raise ValueError(f"invalid {name}")
        return value.strip()

    def _document(self, db, body, version, *, source_refresh=False):
        allowed = {"corpus", "doc_id", "source", "title", "text", "expected_version", "acl",
                   "department", "project", "project_name", "classification", "allowed_roles", "allowed_departments",
                   "source_updated_at", "source_metadata", "permission_annotation"}
        if not isinstance(body, dict) or set(body) - allowed or "expected_version" not in body:
            raise ValueError("document fields and expected_version are required")
        corpus = self._text(body.get("corpus"), "corpus")
        doc_id = self._text(body.get("doc_id"), "doc_id")
        old = db.execute("SELECT * FROM documents WHERE corpus=? AND doc_id=?", (corpus, doc_id)).fetchone()
        expected = body["expected_version"]
        if expected is not None:
            self._text(expected, "expected_version")
        if (old["version"] if old else None) != expected:
            raise UpdateConflict("document version changed; reload before updating")
        if not db.execute("SELECT 1 FROM principals WHERE corpus=? LIMIT 1", (corpus,)).fetchone():
            raise ValueError("unknown corpus")
        source = self._text(body.get("source", old["source"] if old else None), "source")
        if source not in {"slack", "jira", "confluence", "google_drive"} or old and source != old["source"]:
            raise ValueError("invalid or changed source")
        title = self._text(body.get("title"), "title", 1000)
        self._text(body.get("text"), "text", 24000)
        text = body["text"]
        previous_acl = json.loads(old["acl_json"]) if old else None
        acl = body.get("acl", previous_acl)
        if not isinstance(acl, list) or len(acl) > 100 or any(not isinstance(p, str) for p in acl) or len(set(acl)) != len(acl):
            raise ValueError("explicit source ACL required; an empty list denies all access")
        for principal in acl:
            if not db.execute("SELECT 1 FROM principals WHERE corpus=? AND principal_id=?", (corpus, principal)).fetchone():
                raise ValueError("ACL principal does not belong to this corpus")
        extra = json.loads(old["extra_json"]) if old else {"classification": "internal"}
        if "permission_annotation" in body:
            annotation = body["permission_annotation"]
            if (not isinstance(annotation, dict)
                    or set(annotation) != {"kind", "scenario_id", "authority"}
                    or annotation.get("kind") not in {"manual_demo", "administrator_policy"}
                    or annotation.get("authority") != "team_decision"
                    or not isinstance(annotation.get("scenario_id"), str)
                    or not 1 <= len(annotation["scenario_id"]) <= 120):
                raise ValueError("invalid manual permission annotation")
            extra["permission_annotation"] = annotation
        if "project_name" in body:
            extra["project_name"] = self._text(body["project_name"], "project_name", 120)
        for name in ("project", "classification", "allowed_roles", "allowed_departments"):
            if name in body:
                value = body[name]
                if name.startswith("allowed_"):
                    if not isinstance(value, list) or len(value) > 100 or any(not isinstance(v, str) or not v.strip() or len(v) > 256 for v in value):
                        raise ValueError(f"invalid {name}")
                elif name == "classification":
                    if not isinstance(value, str) or value not in {"public", "internal", "confidential", "restricted"}:
                        raise ValueError("invalid classification")
                elif not (name == "project" and value == ""):
                    self._text(value, name)
                extra[name] = value
        source_time = old["ts"] if old else None
        if "source_updated_at" in body:
            source_time = self._text(body["source_updated_at"], "source_updated_at")
            parsed = datetime.fromisoformat(source_time.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                raise ValueError("source_updated_at requires a timezone")
            extra["updated_at"] = source_time
        extra["observed_at"] = now()
        extra["update_origin"] = "trusted_administrator"
        metadata = body.get("source_metadata", {})
        allowed_metadata = {"source_resource_id", "source_url", "source_revision", "source_acl_observed_at", "source_acl_basis"}
        if not isinstance(metadata, dict) or set(metadata) - allowed_metadata:
            raise ValueError("invalid source metadata")
        acl_source_fields = {"source_acl_basis", "source_acl_observed_at"}
        for key, value in metadata.items():
            value = self._text(value, key, 2000 if key == "source_url" else 256)
            if key in acl_source_fields and not source_refresh:
                # Administrator-provided annotations are references, not proof
                # that the current ACL was checked on the source platform.
                reference = extra.get("source_acl_reference")
                if not isinstance(reference, dict):
                    reference = extra["source_acl_reference"] = {}
                reference[key] = value
                reference["authority"] = "administrator_supplied_unverified_reference"
            else:
                extra[key] = value
        acl_basis = old["acl_basis"] if old else "trusted administrator supplied ACL"
        provenance = None
        if source_refresh:
            if acl_source_fields <= set(metadata):
                acl_basis = extra["source_acl_basis"]
                provenance = {"kind": "source_snapshot", "observed_at": extra["source_acl_observed_at"]}
            else:
                # Quarantine/missing-resource withdrawals do not constitute a
                # newly verified grant; never inherit the previous source label.
                for key in acl_source_fields:
                    extra.pop(key, None)
                acl_basis = ("source ACL withdrawn: permission unavailable or resource absent" if not acl else
                             "trusted operator supplied ACL; source verification metadata unavailable")
                provenance = {"kind": "source_withdrawal" if not acl else "operator_snapshot",
                              "observed_at": extra["observed_at"]}
        elif previous_acl is None or set(acl) != set(previous_acl):
            for key in acl_source_fields:
                extra.pop(key, None)
            acl_basis = "administrator adjusted ACL; previous provenance retained in document history" if old else acl_basis
            provenance = {"kind": "administrator_adjustment" if old else "administrator_snapshot",
                          "observed_at": extra["observed_at"]}
        if provenance is not None:
            if old:
                provenance["previous_version"] = old["version"]
            extra["acl_provenance"] = provenance
        department = body.get("department", old["dept"] if old else "")
        if not isinstance(department, str) or len(department) > 256 or "\x00" in department:
            raise ValueError("invalid department")
        return CanonicalDoc(corpus, doc_id, source, title, text, old["day"] if old else None,
            source_time, department, json.loads(old["actors_json"]) if old else [], acl,
            acl_basis, version, content_hash(text), extra, [])

    def submit(self, actor_id, body, *, source_refresh=False):
        self._admin(actor_id)
        if type(source_refresh) is not bool:
            raise ValueError("invalid source refresh flag")
        job_id = uuid.uuid4().hex
        with connect(self.db_path) as db:
            db.execute("BEGIN IMMEDIATE")
            document = self._document(db, body, job_id, source_refresh=source_refresh)
            source_scope = None
            if source_refresh:
                # Not a document/body field: only SourceSync opts into this path.
                # A closed, persistent gate is required before touching canonical
                # data or vectors, including when the worker resumes after restart.
                self._source_fence(document)
                source_scope = document.source
            self.index.state(db)
            if db.execute("SELECT 1 FROM cl_update_jobs WHERE corpus=? AND doc_id=? AND state IN ('queued','running','failed')",
                          (document.corpus, document.doc_id)).fetchone():
                raise UpdateConflict("document already has a pending update; wait or retry it")
            self._admin(actor_id)
            self._record(actor_id, "document_update_intent", job_id, corpus=document.corpus, doc_id=document.doc_id)
            db.execute("INSERT INTO cl_update_jobs (id,corpus,doc_id,actor_id,base_version,document_json,state,created_at,updated_at,source_scope) VALUES (?,?,?,?,?,?,'queued',?,?,?)",
                (job_id, document.corpus, document.doc_id, actor_id, body["expected_version"],
                 json.dumps(asdict(document), ensure_ascii=False), now(), now(), source_scope))
        if self.autostart:
            self.start()
        self._wake.set()
        return self.status(actor_id, job_id)

    def _source_fence(self, document):
        if live_source(document.source, document.doc_id) != document.source:
            raise ValueError("source-scoped publication requires a matching live resource")
        with self.identities.db() as db:
            if not db.execute("SELECT 1 FROM sqlite_master WHERE name='live_source_guards'").fetchone():
                raise IndexUnavailable("source permission gate required")
            row = db.execute("SELECT state FROM live_source_guards WHERE corpus=? AND source=?",
                             (document.corpus, document.source)).fetchone()
        if row is None or row[0] not in {"refreshing", "blocked"}:
            raise IndexUnavailable("source permission gate must stay closed during publication")

    def status(self, actor_id, job_id):
        self._admin(actor_id)
        with connect(self.db_path) as db:
            row = db.execute("SELECT id,corpus,doc_id,state,attempts,created_at,updated_at,error_type,generation FROM cl_update_jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            raise ValueError("unknown update job")
        return dict(row) | {"version": row["id"]}

    def retry(self, actor_id, job_id):
        self._admin(actor_id)
        with connect(self.db_path) as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT state FROM cl_update_jobs WHERE id=?", (job_id,)).fetchone()
            if row is None or row["state"] != "failed":
                raise UpdateConflict("only failed update jobs can be retried")
            self._record(actor_id, "document_update_retry", job_id)
            db.execute("UPDATE cl_update_jobs SET actor_id=?,state='queued',attempts=0,retry_at=0,error_type=NULL,updated_at=? WHERE id=?", (actor_id, now(), job_id))
        self._wake.set()
        return self.status(actor_id, job_id)

    def start(self):
        with self._thread_lock:
            if self._thread is None or not self._thread.is_alive():
                self._stop.clear()
                self._thread = threading.Thread(target=self._loop, name="document-updates", daemon=True)
                self._thread.start()

    def close(self):
        self._stop.set()
        self._wake.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=5)

    def _loop(self):
        while not self._stop.is_set():
            try:
                worked = self.process_one()
            except Exception:
                worked = False
            if not worked:
                self._wake.wait(1)
                self._wake.clear()

    def wait(self, actor_id, job_id, timeout=120):
        deadline = time.monotonic() + timeout
        while True:
            result = self.status(actor_id, job_id)
            if result["state"] == "ready" or result["state"] == "failed" and result["attempts"] >= 3:
                return result
            if time.monotonic() >= deadline:
                raise TimeoutError("update remains queued; its durable job is not cancelled")
            self._stop.wait(.05)

    def process_one(self):
        try:
            with index_lock(self.db_path, blocking=False):
                return self._process_locked()
        except BlockingIOError:
            return False

    def _process_locked(self):
        with connect(self.db_path) as db:
            db.execute("BEGIN IMMEDIATE")
            job = db.execute("SELECT * FROM cl_update_jobs WHERE state IN ('queued','running','failed') AND (state='running' OR attempts<3 AND retry_at<=?) ORDER BY created_at,id LIMIT 1", (time.time(),)).fetchone()
            if job is None:
                return False
            db.execute("UPDATE cl_update_jobs SET state='running',attempts=attempts+1,updated_at=? WHERE id=?", (now(), job["id"]))
        try:
            self._publish(job)
        except Exception as error:
            with connect(self.db_path) as db:
                db.execute("UPDATE cl_update_jobs SET state='failed',error_type=?,retry_at=?,updated_at=? WHERE id=?",
                    (type(error).__name__, time.time() + min(2 ** job["attempts"], 8), now(), job["id"]))
                if job["source_scope"] is None:
                    db.execute("UPDATE cl_index_state SET state='failed' WHERE generation=?", (job["id"],))
            self._record(job["actor_id"], "document_update_failed", job["id"], error_type=type(error).__name__)
        return True

    def _save_history(self, db, row):
        if row is not None:
            previous = db.execute("SELECT document_json FROM cl_document_history WHERE corpus=? AND doc_id=? AND version=?",
                                  (row["corpus"], row["doc_id"], row["version"])).fetchone()
            if previous is not None and json.loads(previous[0]) != dict(row):
                raise UpdateConflict("historical content version changed")
            chunks = [dict(c) for c in db.execute("SELECT * FROM chunks WHERE corpus=? AND doc_id=? ORDER BY ordinal", (row["corpus"], row["doc_id"]))]
            db.execute("INSERT OR IGNORE INTO cl_document_history VALUES (?,?,?,?,?,?)", (
                row["corpus"], row["doc_id"], row["version"], json.dumps(dict(row), ensure_ascii=False),
                json.dumps(chunks, ensure_ascii=False), now()))

    def _publish(self, job):
        self._admin(job["actor_id"])
        document = CanonicalDoc(**json.loads(job["document_json"]))
        scoped = job["source_scope"] is not None
        if scoped:
            if job["source_scope"] != document.source:
                raise UpdateConflict("source publication scope changed")
            self._source_fence(document)
        source = SourceDoc(document.corpus, document.doc_id, document.source, document.title,
            document.text, document.day, document.ts, document.dept, document.actors, dict(document.extra))
        chunks = self.chunker(source)
        if not chunks:
            raise ValueError("document produced no searchable chunks")
        for chunk in chunks:
            chunk.chunk_id = point_id(document.corpus, document.doc_id, document.version, chunk.ordinal)
        document.chunks = [chunk.chunk_id for chunk in chunks]
        with connect(self.db_path) as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM cl_index_state WHERE id=1").fetchone()
            if row is None:
                raise IndexUnavailable("publish the initial index before updating documents")
            state = dict(row)
            if scoped and state["state"] != "ready":
                raise IndexUnavailable("source refresh cannot bypass a whole-index publication gate")
            if scoped:
                self.index.consistent(db, document.corpus)
            if not self.custom_embedding and (state["model"] != MODEL or state["dim"] != 384):
                raise IndexUnavailable("update embedding configuration differs from published index")
            old = db.execute("SELECT * FROM documents WHERE corpus=? AND doc_id=?", (document.corpus, document.doc_id)).fetchone()
            current_version = old["version"] if old else None
            if current_version not in {job["base_version"], document.version}:
                raise UpdateConflict("a newer document superseded this update")
            if current_version == document.version and old["content_hash"] != document.content_hash:
                raise UpdateConflict("immutable update version changed")
            if current_version == document.version:
                expected = {"source": document.source, "title": document.title, "text": document.text,
                            "day": document.day, "ts": document.ts, "dept": document.dept,
                            "acl_json": json.dumps(document.acl, ensure_ascii=False),
                            "extra_json": json.dumps(document.extra, ensure_ascii=False)}
                if any(old[field] != value for field, value in expected.items()):
                    raise UpdateConflict("immutable update metadata changed")
            self._save_history(db, old)
            for table in ("documents", "chunks", "docs_fts"):
                db.execute(f"DELETE FROM {table} WHERE corpus=? AND doc_id=?", (document.corpus, document.doc_id))
            insert_documents(db, [document], chunks)
            snapshot_document(db, document.corpus, document.doc_id)
            if scoped:
                # This known canonical mutation is isolated by the closed source
                # gate AND pending-resource filter. Seal only after checking all
                # canonical snapshots so unrelated edits cannot be legitimised.
                _scan_snapshot(db, document.corpus)
                _sync_published_guard(db, document.corpus)
            else:
                db.execute("UPDATE cl_index_state SET generation=?,state='building' WHERE id=1", (job["id"],))
            counter = db.execute("SELECT n FROM cl_mutation WHERE corpus=?", (document.corpus,)).fetchone()[0]
        vectors = self.embed([chunk.text for chunk in chunks])
        if len(vectors) != len(chunks) or any(len(vector) != state["dim"] for vector in vectors):
            raise ValueError("update vector dimensions or count differ from published index")
        match = qm.Filter(must=[qm.FieldCondition(key="corpus", match=qm.MatchValue(value=document.corpus)),
                                qm.FieldCondition(key="doc_id", match=qm.MatchValue(value=document.doc_id))])
        client = self.index.client
        client.delete(state["collection"], points_selector=qm.FilterSelector(filter=match), wait=True)
        with connect(self.db_path) as db:
            metadata = db.execute("SELECT * FROM cl_metadata WHERE corpus=? AND doc_id=?", (document.corpus, document.doc_id)).fetchone()
            points = [qm.PointStruct(id=point_id(document.corpus, document.doc_id, document.version, chunk.chunk_id),
                vector=vector, payload=payload_for(asdict(chunk), metadata)) for chunk, vector in zip(chunks, vectors)]
        for offset in range(0, len(points), 128):
            client.upsert(state["collection"], points[offset:offset + 128], wait=True)
        actual, cursor = client.scroll(state["collection"], scroll_filter=match, limit=len(points) + 1, with_payload=True)
        expected = {str(point.id): point.payload for point in points}
        if cursor is not None or {str(point.id): point.payload for point in actual} != expected:
            raise IndexUnavailable("updated vector payloads did not pass publication checks")
        self._admin(job["actor_id"])
        if scoped:
            self._source_fence(document)
        self._record(job["actor_id"], "document_update_publication_intent", job["id"], corpus=document.corpus, doc_id=document.doc_id)
        with connect(self.db_path) as db:
            db.execute("BEGIN IMMEDIATE")
            current = dict(db.execute("SELECT * FROM cl_index_state WHERE id=1").fetchone())
            expected_generation, expected_state = (state["generation"], "ready") if scoped else (job["id"], "building")
            if current["generation"] != expected_generation or current["state"] != expected_state:
                raise UpdateConflict("a newer index publication superseded this update")
            if db.execute("SELECT n FROM cl_mutation WHERE corpus=?", (document.corpus,)).fetchone()[0] != counter:
                raise UpdateConflict("canonical state changed during index publication")
            _scan_snapshot(db, document.corpus)
            # A different quarantined live resource can have an unfinished vector
            # write. This resource's exact payloads were checked above; do not let
            # that unrelated failure prevent its own source from being published.
            if not scoped and client.count(state["collection"], exact=True).count != db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]:
                raise IndexUnavailable("vector and canonical chunk counts differ")
            self._save_history(db, db.execute("SELECT * FROM documents WHERE corpus=? AND doc_id=?", (document.corpus, document.doc_id)).fetchone())
            _sync_published_guard(db, document.corpus)
            published_at = now()
            db.execute("UPDATE cl_metadata SET indexed_at=? WHERE corpus=? AND doc_id=?", (published_at, document.corpus, document.doc_id))
            db.execute("UPDATE cl_index_state SET generation=?,state='ready',indexed_at=? WHERE id=1", (job["id"], published_at))
            db.execute("UPDATE cl_update_jobs SET state='ready',error_type=NULL,generation=?,updated_at=? WHERE id=?", (job["id"], now(), job["id"]))
        self._record(job["actor_id"], "document_update_ready", job["id"], corpus=document.corpus, doc_id=document.doc_id, version=document.version)
