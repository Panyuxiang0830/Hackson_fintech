import hashlib
import json
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from qdrant_client import QdrantClient, models as qm

from contextledger.audit_store import AuditStore
from contextledger.document_updates import DocumentUpdates, UpdateConflict
from contextledger.filtered_index import FilteredIndex, IndexUnavailable, payload_for, point_id, prepare_snapshot
from contextledger.identity_store import IdentityStore
from contextledger.index_lock import index_lock
from contextledger.models import CanonicalDoc, Chunk, Principal
from contextledger.store import chunk_digest, connect, init_db, insert_documents, insert_principals
from contextledger.unified_service import UnifiedService
from contextledger.web import create_app


class DocumentUpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db_path = self.root / "content" / "canonical.sqlite"
        self.security = self.root / "security"
        self.ids = IdentityStore(self.security / "identities.sqlite")
        self.admin = self.ids.register("test", "admin", "Admin")
        self.ids.update(self.admin.id, role="admin")
        self.alice = self.ids.register("test", "alice", "Alice")
        self.ids.bind(self.alice.id, "alpha", "alpha:a", True)
        self.audit = AuditStore(self.security / "audit.sqlite")
        self.client = QdrantClient(":memory:")
        self.addCleanup(self.client.close)
        with connect(self.db_path) as db:
            init_db(db)
            insert_principals(db, [Principal("alpha", "alpha:a", "Alice", "engineer", "eng")], {})
            text = "SeedPolicy describes an unrelated reference policy."
            doc = CanonicalDoc("alpha", "seed", "confluence", "SeedPolicy", text, None, None,
                "eng", [], ["alpha:a"], "fixture", "seed-v1", hashlib.sha256(text.encode()).hexdigest(), {}, ["seed-chunk"])
            insert_documents(db, [doc], [Chunk("seed-chunk", "alpha", "seed", 0, text)])
            db.commit()
            self.client.create_collection("updates", vectors_config=qm.VectorParams(size=2, distance=qm.Distance.COSINE))
            prepare_snapshot(db, "updates", "initial", "test-embedding", 2)
            meta = db.execute("SELECT * FROM cl_metadata").fetchone()
            chunk = db.execute("SELECT * FROM chunks").fetchone()
            self.client.upsert("updates", [qm.PointStruct(id=point_id("alpha", "seed", "seed-v1", "seed-chunk"), vector=[1, 0], payload=payload_for(chunk, meta))], wait=True)
            db.execute("UPDATE cl_index_state SET state='ready'")
        self.index = FilteredIndex(self.db_path, self.client, self.ids, embed=lambda text: [1., 0.])
        self.embedded = []
        self.updates = DocumentUpdates(self.index, self.ids, self.audit, embed=self.embed,
            chunker=self.chunks, autostart=False)
        self.addCleanup(self.updates.close)
        with patch.dict("os.environ", {"LLM_PROVIDER": "mock", "LLM_API_KEY": ""}):
            self.service = UnifiedService(self.index, self.ids, self.audit)
        self.app = create_app(self.db_path, self.security, service=self.service, updates=self.updates,
            config={"TESTING": True, "SECRET_KEY": "test-" * 10, "BROWSER_LOGIN_ENABLED": False})
        self.http = self.app.test_client()
        self.login(self.admin)

    def login(self, actor):
        sid = self.ids.new_session(self.ids.get(actor.id), time.time() + 600)
        with self.http.session_transaction() as session:
            session["sid"], session["csrf"] = sid, "csrf"

    def post(self, endpoint, body):
        return self.http.post(endpoint, json=body, headers={"X-CSRF-Token": "csrf"})

    def embed(self, texts):
        self.embedded.extend(texts)
        return [[1., .1] for _ in texts]

    @staticmethod
    def chunks(source):
        return [Chunk("temporary", source.corpus, source.doc_id, 0, source.text)]

    def body(self, *, version=None, amount="50,000", **extra):
        return {"corpus": "alpha", "doc_id": "payment", "source": "confluence", "title": "PaymentPolicy",
            "text": f"PaymentPolicy daily transfer limit is {amount} CNY. Approved for each customer.",
            "expected_version": version, "acl": ["alpha:a"], **extra}

    def submit_ready(self, body=None):
        job = self.updates.submit(self.admin.id, body or self.body())
        self.assertTrue(self.updates.process_one())
        ready = self.updates.status(self.admin.id, job["id"])
        self.assertEqual(ready["state"], "ready", ready)
        return ready

    def assert_answer(self, amount, version):
        for mode in ("keyword", "vector", "hybrid"):
            result, hits = self.service.ask(self.alice.id, "alpha", "PaymentPolicy", mode, planning=False)
            self.assertEqual(result["decision"], "answered")
            self.assertIn(amount, result["answer"])
            self.assertEqual({h["version"] for h in hits}, {version})

    def test_add_modify_changes_all_answers_and_retains_history(self):
        first = self.submit_ready()
        self.assert_answer("50,000", first["version"])
        body = self.body(version=first["version"], amount="100,000")
        body.pop("acl")
        second = self.submit_ready(body)
        self.assert_answer("100,000", second["version"])
        self.assertEqual(len(self.embedded), 2)
        with connect(self.db_path) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM docs_fts WHERE doc_id='payment'").fetchone()[0], 1)
            history = db.execute("SELECT document_json FROM cl_document_history WHERE doc_id='payment' ORDER BY saved_at").fetchall()
            self.assertEqual(len(history), 2)
            self.assertIn("50,000", history[0][0])
            self.assertIn("100,000", history[1][0])
        points, _ = self.client.scroll("updates", limit=10, with_payload=True)
        self.assertEqual(len(points), 2)
        self.assertEqual({p.payload["version"] for p in points if p.payload["doc_id"] == "seed"}, {"seed-v1"})
        self.assertEqual({p.payload["version"] for p in points if p.payload["doc_id"] == "payment"}, {second["version"]})
        self.assertTrue(self.audit.verify().valid)

    def test_http_submit_and_status_require_admin_and_csrf(self):
        self.login(self.alice)
        self.assertEqual(self.post("/api/admin/documents", self.body()).status_code, 403)
        self.login(self.admin)
        self.assertEqual(self.http.post("/api/admin/documents", json=self.body()).status_code, 403)
        response = self.post("/api/admin/documents", self.body())
        self.assertEqual(response.status_code, 202)
        job = response.json["job"]
        self.assertNotIn("text", job)
        self.assertEqual(self.http.get("/api/admin/document-updates/" + job["id"]).json["job"]["state"], "queued")
        self.updates.process_one()
        self.login(self.alice)
        self.assertEqual(self.http.get("/api/admin/document-updates/" + job["id"]).status_code, 403)

    def test_background_worker_automatically_publishes(self):
        self.updates.autostart = True
        job = self.post("/api/admin/documents", self.body()).json["job"]
        result = self.updates.wait(self.admin.id, job["id"], timeout=5)
        self.assertEqual(result["state"], "ready")
        self.assert_answer("50,000", result["version"])

    def test_pending_and_failed_updates_block_old_evidence(self):
        first = self.submit_ready()
        job = self.updates.submit(self.admin.id, self.body(version=first["version"], amount="100,000"))
        for mode in ("keyword", "vector", "hybrid"):
            with self.assertRaises(IndexUnavailable):
                self.service.ask(self.alice.id, "alpha", "PaymentPolicy", mode, planning=False)
        with patch.object(self.updates, "embed", side_effect=ValueError("private diagnostic")):
            self.updates.process_one()
        failed = self.updates.status(self.admin.id, job["id"])
        self.assertEqual(failed["state"], "failed")
        self.assertEqual(failed["error_type"], "ValueError")
        self.assertNotIn("private", json.dumps(failed))
        with self.assertRaises(IndexUnavailable):
            self.service.search(self.alice.id, "alpha", "PaymentPolicy", planning=False)
        response = self.post("/api/admin/document-updates/" + job["id"] + "/retry", {})
        self.assertEqual(response.status_code, 202)
        self.updates.process_one()
        self.assert_answer("100,000", job["version"])

    def test_partial_vector_failure_is_recoverable(self):
        job = self.updates.submit(self.admin.id, self.body())
        with patch.object(self.client, "upsert", side_effect=RuntimeError("offline")):
            self.updates.process_one()
        self.assertEqual(self.updates.status(self.admin.id, job["id"])["state"], "failed")
        self.updates.retry(self.admin.id, job["id"])
        self.updates.process_one()
        self.assert_answer("50,000", job["version"])

    def test_restart_recovers_queued_and_interrupted_jobs(self):
        job = self.updates.submit(self.admin.id, self.body())
        with connect(self.db_path) as db:
            db.execute("UPDATE cl_update_jobs SET state='running',attempts=1 WHERE id=?", (job["id"],))
        replacement = DocumentUpdates(self.index, self.ids, self.audit, embed=self.embed,
            chunker=self.chunks, autostart=False)
        self.addCleanup(replacement.close)
        self.assertTrue(replacement.process_one())
        self.assertEqual(replacement.status(self.admin.id, job["id"])["state"], "ready")

    def test_stale_version_and_duplicate_pending_write_are_conflicts(self):
        job = self.updates.submit(self.admin.id, self.body())
        self.assertEqual(self.post("/api/admin/documents", self.body()).status_code, 409)
        self.updates.process_one()
        with self.assertRaises(UpdateConflict):
            self.updates.submit(self.admin.id, self.body())
        self.assertEqual(self.updates.status(self.admin.id, job["id"])["state"], "ready")

    def test_invalid_fields_and_acl_never_queue(self):
        for change in ({"acl": None}, {"acl": ["beta:unknown"]}, {"principal_id": "alpha:a"},
                       {"classification": "nonsense"}, {"classification": []}, {"department": 0},
                       {"source_updated_at": "2026-10-12"}, {"text": ""}):
            self.assertEqual(self.post("/api/admin/documents", self.body(**change)).status_code, 400, change)
        body = self.body()
        body.pop("expected_version")
        self.assertEqual(self.post("/api/admin/documents", body).status_code, 400)
        with connect(self.db_path) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM cl_update_jobs").fetchone()[0], 0)

    def test_empty_acl_stays_denied(self):
        self.submit_ready(self.body(acl=[]))
        result, _ = self.service.ask(self.alice.id, "alpha", "PaymentPolicy", planning=False)
        self.assertEqual(result["decision"], "insufficient")
        self.assertEqual(result["evidence"], [])

    def test_source_text_and_hash_are_preserved_exactly(self):
        text = "  PaymentPolicy daily transfer limit is 50,000 CNY.\n\n"
        self.submit_ready(self.body(text=text))
        with connect(self.db_path) as db:
            row = db.execute("SELECT text,content_hash FROM documents WHERE doc_id='payment'").fetchone()
            self.assertEqual(row["text"], text)
            self.assertEqual(row["content_hash"], hashlib.sha256(text.encode()).hexdigest())

    def test_legacy_cache_blocks_pending_and_changed_chunks_without_deleting_files(self):
        from contextledger import vectors
        directory = self.db_path.parent / "vectors/alpha"
        directory.mkdir(parents=True)
        status_path = directory / "status.json"
        with connect(self.db_path) as db:
            signature = chunk_digest(db, "alpha")
        status_path.write_text(json.dumps({"model": vectors.MODEL_NAME, "dim": 384, "chunks_sha256": signature}))
        stat = status_path.stat()
        counter = vectors._canonical_counter(self.db_path.parent.resolve(), "alpha")
        cached = SimpleNamespace(status_signature=(stat.st_mtime_ns, stat.st_size, stat.st_ino, counter))
        key = (str(self.db_path.parent.resolve()), "alpha")
        with patch.dict(vectors._STORES, {key: cached}):
            self.assertIs(vectors.get_store(self.db_path.parent, "alpha"), cached)
            self.updates.submit(self.admin.id, self.body())
            with self.assertRaisesRegex(RuntimeError, "pending"):
                vectors.get_store(self.db_path.parent, "alpha")
            self.updates.process_one()
            with self.assertRaisesRegex(RuntimeError, "rebuild legacy"):
                vectors.get_store(self.db_path.parent, "alpha")
        self.assertTrue(status_path.exists())
        self.assertEqual(json.loads(status_path.read_text())["chunks_sha256"], signature)

    def test_rechunking_removes_previous_vectors_and_chunks(self):
        self.updates.chunker = lambda s: [Chunk("temporary", s.corpus, s.doc_id, i, s.text)
                                         for i in range(2 if "50,000" in s.text else 1)]
        first = self.submit_ready()
        self.assertEqual(self.client.count("updates", exact=True).count, 3)
        second = self.submit_ready(self.body(version=first["version"], amount="100,000"))
        self.assertEqual(self.client.count("updates", exact=True).count, 2)
        self.assert_answer("100,000", second["version"])
        with connect(self.db_path) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM chunks WHERE doc_id='payment'").fetchone()[0], 1)

    def test_tampered_vector_payload_is_not_published(self):
        job = self.updates.submit(self.admin.id, self.body())
        original = self.client.scroll
        def wrong(*args, **kwargs):
            points, cursor = original(*args, **kwargs)
            points[0].payload["version"] = "stale"
            return points, cursor
        with patch.object(self.client, "scroll", side_effect=wrong):
            self.updates.process_one()
        self.assertEqual(self.updates.status(self.admin.id, job["id"])["state"], "failed")

    def test_direct_mutation_during_embedding_prevents_publication(self):
        def mutate(texts):
            with connect(self.db_path) as db:
                db.execute("UPDATE documents SET title='Changed' WHERE doc_id='payment'")
            return self.embed(texts)
        job = self.updates.submit(self.admin.id, self.body())
        with patch.object(self.updates, "embed", side_effect=mutate):
            self.updates.process_one()
        status = self.updates.status(self.admin.id, job["id"])
        self.assertEqual(status["state"], "failed")
        self.assertEqual(status["error_type"], "UpdateConflict")

    def test_single_publisher_lock_and_bounded_retries(self):
        job = self.updates.submit(self.admin.id, self.body())
        with index_lock(self.db_path):
            self.assertFalse(self.updates.process_one())
        with patch.object(self.updates, "embed", side_effect=RuntimeError("offline")):
            for _ in range(3):
                with connect(self.db_path) as db:
                    db.execute("UPDATE cl_update_jobs SET retry_at=0")
                self.assertTrue(self.updates.process_one())
            self.assertFalse(self.updates.process_one())
        self.assertEqual(self.updates.status(self.admin.id, job["id"])["attempts"], 3)

    def test_symlink_to_database_uses_the_same_publisher_lock(self):
        self.updates.submit(self.admin.id, self.body())
        alias = self.root / "alias.sqlite"
        alias.symlink_to(self.db_path)
        with index_lock(alias):
            self.assertFalse(self.updates.process_one())

    def test_revoked_administrator_cannot_publish(self):
        job = self.updates.submit(self.admin.id, self.body())
        self.ids.update(self.admin.id, role="member")
        self.updates.process_one()
        with connect(self.db_path) as db:
            self.assertEqual(db.execute("SELECT error_type FROM cl_update_jobs WHERE id=?", (job["id"],)).fetchone()[0], "PermissionError")
            self.assertEqual(db.execute("SELECT COUNT(*) FROM documents WHERE doc_id='payment'").fetchone()[0], 0)

    def test_update_during_answer_discards_previous_version(self):
        first = self.submit_ready()
        original = self.service.answer.answer
        def update(user, question, evidence, **kwargs):
            self.updates.submit(self.admin.id, self.body(version=first["version"], amount="100,000"))
            return original(user, question, evidence, **kwargs)
        with patch.object(self.service.answer, "answer", side_effect=update):
            with self.assertRaises(IndexUnavailable):
                self.service.ask(self.alice.id, "alpha", "PaymentPolicy", planning=False)


if __name__ == "__main__":
    unittest.main()
