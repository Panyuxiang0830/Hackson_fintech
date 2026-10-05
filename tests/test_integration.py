"""Functional/security tests use a real local Qdrant engine, not ANN mocks."""

import hashlib
import json
from pathlib import Path
import tempfile
import time
import unittest
import uuid
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock, patch

from qdrant_client import QdrantClient, models as qm

from contextledger.audit_store import AuditStore
from contextledger.filtered_index import FilteredIndex, IndexUnavailable, payload_for, point_id, prepare_snapshot
from contextledger.identity_store import IdentityStore
from contextledger.models import CanonicalDoc, Chunk, Principal
from contextledger.store import connect, init_db, insert_documents, insert_principals
from contextledger.unified_service import PermissionChanged, UnifiedService, validate_security_path
from contextledger.web import create_app
from src.audit import AuditIntegrityError


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.content = self.root / "content"
        self.content.mkdir()
        self.db_path = self.content / "canonical.sqlite"
        self.security = self.root / "security"
        self.ids = IdentityStore(self.security / "identities.sqlite")
        self.audit = AuditStore(self.security / "audit.sqlite")
        self.alice = self.ids.register("https://issuer.example", "alice-sub", "Same Name")
        self.bob = self.ids.register("https://issuer.example", "bob-sub", "Same Name")
        self.admin = self.ids.register("https://issuer.example", "admin-sub", "Admin")
        self.ids.update(self.admin.id, role="admin")
        self.ids.bind(self.alice.id, "alpha", "alpha:a", True)
        self.ids.bind(self.bob.id, "alpha", "alpha:b", True)
        db = connect(self.db_path)
        self.addCleanup(db.close)
        init_db(db)
        insert_principals(db, [Principal("alpha", "alpha:a", "A", "engineer", "eng"),
                              Principal("alpha", "alpha:b", "B", "sales", "sales"),
                              Principal("beta", "beta:a", "A", "engineer", "eng")], {})
        docs, chunks = [], []
        for number, (corpus, acl, source) in enumerate([
                ("alpha", ["alpha:a"], "confluence"), ("alpha", ["alpha:a"], "jira"),
                ("alpha", ["alpha:b"], "slack"), ("beta", ["beta:a"], "google_drive")]):
            doc_id = "doc-" + str(number)
            text = f"TitanDB fact {number}. Decision approved."
            digest = hashlib.sha256(text.encode()).hexdigest()
            extra = {"project": "payments", "updated_at": "2026-10-05T00:00:00Z"}
            docs.append(CanonicalDoc(corpus, doc_id, source, "Title " + str(number), text,
                None, None, "eng", [], acl, "test-explicit-acl", digest[:12], digest, extra, [doc_id + "-0"]))
            chunks.append(Chunk(doc_id + "-0", corpus, doc_id, 0, text))
        insert_documents(db, docs, chunks)
        db.commit()
        self.qdrant = QdrantClient(":memory:")
        self.addCleanup(self.qdrant.close)
        self.qdrant.create_collection("fixture", vectors_config=qm.VectorParams(size=2, distance=qm.Distance.COSINE))
        prepare_snapshot(db, "fixture", "test-generation", "test-embedding", 2)
        points = []
        for chunk in db.execute("SELECT * FROM chunks"):
            meta = db.execute("SELECT * FROM cl_metadata WHERE corpus=? AND doc_id=?", (chunk["corpus"], chunk["doc_id"])).fetchone()
            points.append(qm.PointStruct(id=point_id(chunk["corpus"], chunk["doc_id"], meta["version"], chunk["chunk_id"]),
                                        vector=[1.0, 0.0], payload=payload_for(chunk, meta)))
        self.qdrant.upsert("fixture", points)
        db.execute("UPDATE cl_index_state SET state='ready'")
        db.commit()
        self.index = FilteredIndex(self.db_path, self.qdrant, self.ids, embed=lambda q: [1.0, 0.0])
        with patch.dict("os.environ", {"LLM_PROVIDER": "mock", "LLM_API_KEY": ""}):
            self.service = UnifiedService(self.index, self.ids, self.audit)
        self.app = create_app(self.db_path, self.security, service=self.service,
                             config={"TESTING": True, "SECRET_KEY": "test-secret-" * 4, "OIDC_ISSUER": "", "OIDC_CLIENT_ID": ""})
        self.client = self.app.test_client()
        self.login(self.alice)

    def login(self, actor, client=None):
        client = client or self.client
        sid = self.ids.new_session(actor, time.time() + 600)
        with client.session_transaction() as session:
            session["sid"], session["csrf"] = sid, "test-csrf"

    def post(self, path, body, client=None):
        return (client or self.client).post(path, json=body, headers={"X-CSRF-Token": "test-csrf"})

    def test_unauthenticated_apis_and_unconfigured_login_fail_closed(self):
        client = self.app.test_client()
        for path in ("/api/search?q=TitanDB", "/api/doc?doc_id=doc-0", "/api/admin/users", "/api/audit"):
            self.assertEqual(client.get(path).status_code, 401)
        self.assertEqual(client.get("/auth/login").status_code, 503)
        self.assertIn(b"OIDC", client.get("/").data)

    def test_unconfigured_non_test_app_locks_preexisting_sessions(self):
        app = create_app(self.db_path, self.security, service=self.service,
            config={"TESTING": False, "SECRET_KEY": "test-secret-" * 4, "OIDC_ISSUER": "", "OIDC_CLIENT_ID": ""})
        client = app.test_client()
        self.login(self.alice, client)
        self.assertEqual(client.get("/api/search?corpus=alpha&q=TitanDB").status_code, 401)
        self.assertFalse(client.get("/api/session").json["authenticated"])

    def test_both_indexes_filter_before_candidates_and_isolate_corpora(self):
        for mode in ("keyword", "vector", "hybrid"):
            with patch.object(self.qdrant, "query_points", wraps=self.qdrant.query_points) as call:
                result = self.client.get(f"/api/search?corpus=alpha&q=TitanDB&mode={mode}")
                self.assertEqual(result.status_code, 200, result.json)
                self.assertEqual({h["doc_id"] for h in result.json["hits"]}, {"doc-0", "doc-1"})
                if mode != "keyword":
                    self.assertIsNotNone(call.call_args.kwargs["query_filter"])
        self.assertEqual(self.client.get("/api/search?corpus=beta&q=TitanDB&mode=vector").json["hits"], [])

    def test_caller_cannot_impersonate_source_principal(self):
        self.assertEqual(self.client.get("/api/search?corpus=alpha&q=TitanDB&principal=alpha:b").status_code, 400)
        self.assertEqual(self.post("/api/ask", {"corpus": "alpha", "q": "TitanDB", "principal_id": "alpha:b"}).status_code, 400)

    def test_document_interface_independently_enforces_current_acl(self):
        self.assertEqual(self.client.get("/api/doc?corpus=alpha&doc_id=doc-0").status_code, 200)
        self.assertEqual(self.client.get("/api/doc?corpus=alpha&doc_id=doc-2").status_code, 404)
        self.ids.bind(self.alice.id, "alpha", "alpha:a", False)
        self.assertEqual(self.client.get("/api/doc?corpus=alpha&doc_id=doc-0").status_code, 404)

    def test_answer_reuses_service_and_audits_evidence_versions(self):
        result = self.post("/api/ask", {"corpus": "alpha", "q": "TitanDB", "mode": "hybrid"})
        self.assertEqual(result.status_code, 200, result.json)
        self.assertEqual(result.json["provider"], "mock")
        self.assertIn("[1]", result.json["answer"])
        self.assertEqual({e["doc_id"] for e in result.json["evidence"]}, {"doc-0", "doc-1"})
        events = self.audit.query(request_id=result.json["request_id"])
        self.assertEqual(events[0]["permission_epoch"], self.ids.get(self.alice.id).epoch)
        self.assertIn("version", events[0]["evidence"][0])
        self.assertTrue(self.audit.verify().valid)

    def test_revocation_during_model_call_discards_answer(self):
        answer = Mock()
        def generate(*args):
            self.ids.bind(self.alice.id, "alpha", "alpha:a", False)
            return "SECRET GENERATED ANSWER [1]", "answered", "fixture"
        answer.answer.side_effect = generate
        self.service.answer = answer
        result = self.post("/api/ask", {"corpus": "alpha", "q": "TitanDB", "mode": "keyword"})
        self.assertEqual(result.status_code, 409)
        self.assertNotIn(b"SECRET GENERATED", result.data)
        self.assertNotIn("SECRET GENERATED", json.dumps(self.audit.query()))

    def test_local_platform_and_document_denials_push_to_both_indexes(self):
        self.ids.restrict(self.alice.id, "alpha", "source", "jira", True)
        for mode in ("keyword", "vector", "hybrid"):
            result = self.client.get(f"/api/search?corpus=alpha&q=TitanDB&mode={mode}")
            self.assertEqual([h["doc_id"] for h in result.json["hits"]], ["doc-0"])
        self.ids.restrict(self.alice.id, "alpha", "document", "doc-0", True)
        self.assertEqual(self.client.get("/api/search?corpus=alpha&q=TitanDB&mode=hybrid").json["hits"], [])

    def test_current_actor_projects_and_clearance_are_index_filters(self):
        self.ids.update(self.alice.id, projects=["other-project"])
        for mode in ("keyword", "vector"):
            self.assertEqual(self.client.get(f"/api/search?corpus=alpha&q=TitanDB&mode={mode}").json["hits"], [])
        self.ids.update(self.alice.id, projects=[], clearance=0)
        self.assertEqual(self.client.get("/api/search?corpus=alpha&q=TitanDB&mode=hybrid").json["hits"], [])

    def test_acl_snapshot_change_blocks_vector_before_call(self):
        with connect(self.db_path) as db:
            db.execute("UPDATE documents SET acl_json='[]' WHERE doc_id='doc-0'")
        with patch.object(self.qdrant, "query_points", wraps=self.qdrant.query_points) as call:
            result = self.client.get("/api/search?corpus=alpha&q=TitanDB&mode=vector")
            self.assertEqual(result.status_code, 503)
            call.assert_not_called()

    def test_pending_index_and_bad_chunk_hash_do_not_reach_answer_model(self):
        with connect(self.db_path) as db:
            db.execute("UPDATE cl_index_state SET state='building'")
        model = Mock()
        self.service.answer = model
        result = self.post("/api/ask", {"corpus": "alpha", "q": "TitanDB"})
        self.assertEqual(result.status_code, 503)
        model.answer.assert_not_called()

    def test_corrupted_keyword_chunk_is_not_used_as_evidence(self):
        with connect(self.db_path) as db:
            db.execute("UPDATE chunks SET text='Injected unrelated content' WHERE chunk_id='doc-0-0'")
        model = Mock()
        self.service.answer = model
        response = self.post("/api/ask", {"corpus": "alpha", "q": "TitanDB", "mode": "keyword"})
        self.assertEqual(response.status_code, 503)
        model.answer.assert_not_called()

    def test_poisoned_vector_backend_is_rechecked_against_fact_store(self):
        payload = {"corpus": "alpha", "doc_id": "doc-2", "chunk_id": "doc-2-0", "version": "wrong"}
        point = qm.ScoredPoint(id=str(uuid.uuid4()), score=1.0, version=1, payload=payload)
        with patch.object(self.qdrant, "query_points", return_value=SimpleNamespace(points=[point])):
            result = self.client.get("/api/search?corpus=alpha&q=TitanDB&mode=vector")
            self.assertEqual(result.status_code, 200)
            self.assertEqual(result.json["hits"], [])

    def test_permission_change_after_audit_before_delivery_also_discards_payload(self):
        original = self.service.record
        def record(actor, event_type, **kwargs):
            event = original(actor, event_type, **kwargs)
            if event_type == "answer":
                self.ids.bind(actor.id, "alpha", "alpha:a", False)
            return event
        with patch.object(self.service, "record", side_effect=record):
            result = self.post("/api/ask", {"corpus": "alpha", "q": "TitanDB", "mode": "keyword"})
            self.assertEqual(result.status_code, 409)
            self.assertNotIn(b"TitanDB fact", result.data)

    def test_session_expiry_and_no_implicit_admin_content_access(self):
        with self.ids.db() as db:
            db.execute("UPDATE sessions SET expires_at=?", (time.time() - 1,))
        self.assertEqual(self.client.get("/api/search?q=TitanDB").status_code, 401)
        self.login(self.admin)
        self.assertEqual(self.client.get("/api/search?corpus=alpha&q=TitanDB&mode=keyword").json["hits"], [])

    def test_orgforge_historical_day_does_not_restore_departed_source_identity(self):
        with connect(self.db_path) as db:
            db.execute("INSERT INTO principals VALUES ('orgforge:departed','orgforge','Departed','engineer','eng',0,10)")
        self.ids.bind(self.alice.id, "orgforge", "orgforge:departed", True)
        scope = self.index.scope(self.ids.get(self.alice.id), "orgforge", day=8)
        self.assertEqual(scope.principals, ())

    def test_full_audit_chain_detects_content_tampering(self):
        self.service.record(self.ids.get(self.alice.id), "test")
        with self.audit.db() as db:
            payload = json.loads(db.execute("SELECT payload FROM events WHERE sequence=1").fetchone()[0])
            payload["decision"] = "tampered"
            db.execute("UPDATE events SET payload=? WHERE sequence=1", (json.dumps(payload),))
        self.assertFalse(self.audit.verify().valid)
        self.assertEqual(self.client.get("/api/search?corpus=alpha&q=TitanDB&mode=keyword").status_code, 503)

    def test_roles_and_csrf_cannot_be_bypassed(self):
        self.assertEqual(self.client.get("/api/admin/users").status_code, 403)
        self.assertEqual(self.client.get("/api/audit").status_code, 403)
        self.assertEqual(self.client.post("/api/ask", json={"q": "TitanDB"}).status_code, 403)
        self.login(self.admin)
        self.assertEqual(self.post("/api/admin/permissions", {"user_id": self.alice.id, "action": "binding",
                         "corpus": "alpha", "principal_id": "alpha:a", "enabled": False}).status_code, 200)
        self.login(self.alice)
        self.assertEqual(self.client.get("/api/search?corpus=alpha&q=TitanDB&mode=keyword").json["hits"], [])

    def test_auditor_without_source_access_sees_redacted_content(self):
        result = self.post("/api/ask", {"corpus": "alpha", "q": "TitanDB", "mode": "keyword"})
        self.login(self.admin)
        audited = self.client.get("/api/audit?q=最近%207%20天")
        self.assertEqual(audited.status_code, 200, audited.json)
        event = next(e for e in audited.json["events"] if e["request_id"] == result.json["request_id"])
        self.assertIn("redacted", event["answer"])
        self.assertEqual(event["retrieved_document_ids"], [])
        self.assertTrue(audited.json["integrity"]["valid"])

    def test_account_disable_expires_access_and_cache_is_disabled(self):
        response = self.client.get("/api/search?corpus=alpha&q=TitanDB&mode=keyword")
        self.assertIn("no-store", response.headers["Cache-Control"])
        self.ids.update(self.alice.id, enabled=False)
        self.assertEqual(self.client.get("/api/search?corpus=alpha&q=TitanDB").status_code, 401)
        self.assertFalse(self.client.get("/api/session").json["authenticated"])

    def test_identity_and_restrictions_survive_reopening(self):
        self.ids.restrict(self.alice.id, "alpha", "source", "slack", True)
        reopened = IdentityStore(self.ids.path)
        actor = reopened.get(self.alice.id)
        self.assertEqual(reopened.scope(actor, "alpha")[1]["source"], ["slack"])
        self.assertNotEqual(self.alice.id, self.bob.id)
        self.assertNotEqual(self.ids.register("https://other.example", "alice-sub", "Same Name").id, self.alice.id)
        with self.assertRaises(ValueError):
            validate_security_path(self.content, self.content / "security")

    def test_source_permission_adapter_explicitly_not_enabled(self):
        self.login(self.admin)
        response = self.client.get("/api/admin/source-permissions")
        self.assertTrue(all(s["status"] == "not_enabled" and s["checked_at"] is None for s in response.json))

    def test_multiple_audit_writers_and_tail_tampering(self):
        def write(number):
            AuditStore(self.audit.path).append({"timestamp": "2026-10-06T00:00:00+00:00", "user_id": "fixture", "number": number})
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(write, range(16)))
        self.assertTrue(self.audit.verify().valid)
        with self.audit.db() as db:
            db.execute("DELETE FROM events WHERE sequence=(SELECT MAX(sequence) FROM events)")
        self.assertFalse(self.audit.verify().valid)
        with self.assertRaises(AuditIntegrityError):
            self.audit.append({"timestamp": "2026-10-06T00:00:00+00:00"})


if __name__ == "__main__":
    unittest.main()
