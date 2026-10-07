"""Functional/security tests use a real local Qdrant engine, not ANN mocks."""

import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
import uuid
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock, patch

from qdrant_client import QdrantClient, models as qm

from contextledger.audit_store import AuditStore
from contextledger.filtered_index import FilteredIndex, IndexUnavailable, MODEL, migrate, payload_for, point_id, prepare_snapshot
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
                             config={"TESTING": True, "SECRET_KEY": "test-secret-" * 4, "BROWSER_LOGIN_ENABLED": False, "OIDC_ISSUER": "", "OIDC_CLIENT_ID": ""})
        self.client = self.app.test_client()
        self.login(self.alice)

    def login(self, actor, client=None):
        client = client or self.client
        sid = self.ids.new_session(actor, time.time() + 600)
        with client.session_transaction() as session:
            session["sid"], session["csrf"] = sid, "test-csrf"

    def post(self, path, body, client=None):
        return (client or self.client).post(path, json=body, headers={"X-CSRF-Token": "test-csrf"})

    def test_chinese_adjoining_entity_is_tokenised_and_authorised(self):
        from contextledger.search import _fts_query
        self.assertIn('"TitanDB"', _fts_query("介绍TitanDB是做什么的"))
        hits, _ = self.index.search(self.index.scope(self.ids.get(self.alice.id), "alpha"), "TitanDB是做什么的")
        self.assertEqual({h["doc_id"] for h in hits}, {"doc-0", "doc-1"})

    def test_unknown_entity_does_not_return_nearest_unrelated_docs_or_call_model(self):
        self.index.embed = Mock(side_effect=AssertionError("unnecessary embedding"))
        answerer = self.service.answer
        with patch.object(answerer, "_openai_compatible") as model:
            result, hits = self.service.ask(self.alice.id, "alpha", "TibanDB是做什么的")
        self.assertEqual(hits, [])
        self.assertEqual(result["decision"], "insufficient")
        self.assertEqual(result["llm_diagnostics"]["attempts"], 0)
        self.index.embed.assert_not_called()
        model.assert_not_called()

    def test_spelling_suggestions_are_authorised_and_not_auto_applied(self):
        with connect(self.db_path) as db:
            db.execute("UPDATE documents SET title=? WHERE doc_id=?", ("TitanDB Overview", "doc-0"))
            db.execute("UPDATE documents SET title=? WHERE doc_id=?", ("TibanSecretDB Overview", "doc-2"))
            db.commit()
            prepare_snapshot(db, "fixture", "test-generation", "test-embedding", 2)
            db.execute("UPDATE cl_index_state SET state=?", ("ready",))
            db.commit()
        result, hits = self.service.ask(self.alice.id, "alpha", "TibanDB是做什么的")
        self.assertEqual(hits, [])
        self.assertEqual(result["query_suggestions"], ["TitanDB"])
        self.assertIn("系统未自动替换", result["answer"])
        self.assertNotIn("TibanSecretDB", result["answer"])
        self.assertEqual(self.audit.query(request_id=result["request_id"])[0]["query"], "TibanDB是做什么的")

    def test_api_failures_audited_as_insufficient_with_safe_diagnostics(self):
        import os, urllib.error
        from src.answering import AnswerService
        with patch.dict(os.environ, {"LLM_API_KEY":"fixture-key", "LLM_PROVIDER":"openai_compatible"}):
            self.service.answer = AnswerService()
            with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("fixture-key")):
                result, _ = self.service.ask(self.alice.id, "alpha", "TitanDB是做什么的")
        event = self.audit.query(request_id=result["request_id"])[0]
        self.assertEqual(event["decision"], "insufficient")
        self.assertEqual(event["llm_diagnostics"]["failures"], ["api_unavailable"])
        self.assertNotIn("fixture-key", json.dumps(event))

    def test_substantive_chunk_replaces_heading_only_and_keeps_hash_validation(self):
        text = "TitanDB title only\n\nTitanDB stores relational records. TitanDB is backed by PostgreSQL and used for telemetry."
        digest = hashlib.sha256(text.encode()).hexdigest()
        with connect(self.db_path) as db:
            db.execute("UPDATE documents SET text=?,version=?,content_hash=? WHERE doc_id=?",
                       (text,digest[:12],digest,"doc-0"))
            db.execute("UPDATE docs_fts SET text=? WHERE doc_id=?", (text,"doc-0"))
            db.execute("UPDATE chunks SET text=? WHERE chunk_id=?", ("TitanDB title only","doc-0-0"))
            db.execute("INSERT INTO chunks VALUES (?,?,?,?,?)", ("doc-0-1","alpha","doc-0",1,text.split("\n\n")[1]))
            db.commit()
            prepare_snapshot(db, "fixture", "test-generation", "test-embedding", 2)
            db.execute("UPDATE cl_index_state SET state=?", ("ready",))
            db.commit()
        hits,_ = self.index.search(self.index.scope(self.ids.get(self.alice.id),"alpha"), "TitanDB是做什么的",mode="keyword")
        hit = next(hit for hit in hits if hit["doc_id"]=="doc-0")
        self.assertEqual(hit["chunk_id"], "doc-0-1")
        self.assertIn("PostgreSQL",hit["text"])
        with connect(self.db_path) as db:
            db.execute("UPDATE chunks SET text=? WHERE chunk_id=?", ("TitanDB INJECTED TitanDB","doc-0-1"))
            db.commit()
        with self.assertRaises(IndexUnavailable):
            self.index.search(self.index.scope(self.ids.get(self.alice.id),"alpha"),"TitanDB是做什么的",mode="keyword")

    def test_empty_question_has_actionable_chinese_error(self):
        response = self.post("/api/ask", {"corpus":"alpha","q":"  "})
        self.assertEqual(response.status_code,400)
        self.assertIn("灰色示例文字",response.json["error"])

    def test_unauthenticated_apis_and_unconfigured_login_fail_closed(self):
        client = self.app.test_client()
        for path in ("/api/search?q=TitanDB", "/api/doc?doc_id=doc-0", "/api/admin/users", "/api/audit"):
            self.assertEqual(client.get(path).status_code, 401)
        self.assertEqual(client.get("/auth/login").status_code, 404)
        self.assertEqual(client.get("/auth/callback?code=forged").status_code, 404)
        page = client.get("/").get_data(as_text=True)
        self.assertNotIn('href="/auth/login"', page)
        self.assertIn("Part A 数据链路与前端验收", page)
        self.assertIn("普通模式不开放演示身份选择", page)
        self.assertNotIn("工具身份入口尚未实现", page)
        status = client.get("/api/session").json
        self.assertFalse(status["browser_login_enabled"])
        self.assertFalse(status["tool_access_configured"])
        self.assertEqual(status["identity_mode"], "identity_entry_pending")

    def test_deferred_login_ignores_existing_oidc_configuration_and_sessions(self):
        with patch.dict("os.environ", {"BROWSER_LOGIN_ENABLED": "false"}):
            app = create_app(self.db_path, self.security, service=self.service,
                config={"TESTING": False, "SECRET_KEY": "test-secret-" * 4,
                        "OIDC_ISSUER": "https://issuer.example", "OIDC_CLIENT_ID": "retained-client-id"})
        client = app.test_client()
        self.login(self.alice, client)
        self.assertIsNone(app.extensions["oidc_client"])
        self.assertEqual(client.get("/auth/login").status_code, 404)
        self.assertEqual(client.get("/auth/callback").status_code, 404)
        status = client.get("/api/session").json
        self.assertFalse(status["authenticated"])
        self.assertFalse(status["oidc_configured"])
        self.assertNotIn(b'href="/auth/login"', client.get("/").data)
        for path in ("/api/search?corpus=alpha&q=TitanDB&user_id=" + self.alice.id,
                     "/api/doc?corpus=alpha&doc_id=doc-0", "/api/admin/users", "/api/audit"):
            response = client.get(path, headers={"X-User-ID": self.alice.id})
            self.assertEqual(response.status_code, 401)
            self.assertEqual(response.json["error"], "trusted_identity_required")
        self.assertEqual(client.post("/api/ask", json={"q": "TitanDB", "user_id": self.alice.id}).status_code, 401)

    def test_unconfigured_non_test_app_locks_preexisting_sessions(self):
        app = create_app(self.db_path, self.security, service=self.service,
            config={"TESTING": False, "SECRET_KEY": "test-secret-" * 4, "BROWSER_LOGIN_ENABLED": False, "OIDC_ISSUER": "", "OIDC_CLIENT_ID": ""})
        client = app.test_client()
        self.login(self.alice, client)
        self.assertEqual(client.get("/api/search?corpus=alpha&q=TitanDB").status_code, 401)
        self.assertFalse(client.get("/api/session").json["authenticated"])

    def test_migration_reuses_embedding_row_maps_in_read_only_mode(self):
        import numpy as np
        import warnings

        with connect(self.db_path) as db:
            for corpus in ("alpha", "beta"):
                chunks = list(db.execute("SELECT * FROM chunks WHERE corpus=? ORDER BY rowid", (corpus,)))
                directory = self.content / "vectors" / corpus
                directory.mkdir(parents=True)
                matrix = np.zeros((len(chunks), 384), dtype=np.float32)
                matrix[:, 0] = 1.0
                (directory / "embeddings.f32").write_bytes(matrix.tobytes())
                (directory / "status.json").write_text(json.dumps({"model": MODEL, "dim": 384, "rows": len(chunks)}))
                with sqlite3.connect(directory / "rows.sqlite") as cache:
                    cache.execute("CREATE TABLE vec_rows (row_id INTEGER,doc_id TEXT,chunk_id TEXT)")
                    cache.executemany("INSERT INTO vec_rows VALUES (?,?,?)",
                                      [(i, row["doc_id"], row["chunk_id"]) for i, row in enumerate(chunks)])
        with patch("contextledger.filtered_index.sqlite3.connect", wraps=sqlite3.connect) as opening:
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore", message="Payload indexes have no effect in the local Qdrant.*")
                result = migrate(self.db_path, self.qdrant, reuse_embeddings=True, batch_size=2)
        self.assertEqual(result["chunks"], 4)
        cache_calls = [call for call in opening.call_args_list if "rows.sqlite" in str(call.args[0])]
        self.assertEqual(len(cache_calls), 2)
        self.assertTrue(all(str(call.args[0]).endswith("?mode=ro") and call.kwargs["uri"] for call in cache_calls))
        for call in cache_calls:
            with sqlite3.connect(*call.args, **call.kwargs) as cache:
                with self.assertRaises(sqlite3.OperationalError):
                    cache.execute("DELETE FROM vec_rows")

    def test_both_indexes_filter_before_candidates_and_isolate_corpora(self):
        for mode in ("keyword", "vector", "hybrid"):
            with patch.object(self.qdrant, "query_points", wraps=self.qdrant.query_points) as call:
                result = self.client.get(f"/api/search?corpus=alpha&q=TitanDB&mode={mode}")
                self.assertEqual(result.status_code, 200, result.json)
                self.assertEqual({h["doc_id"] for h in result.json["hits"]}, {"doc-0", "doc-1"})
                if mode != "keyword":
                    self.assertIsNotNone(call.call_args.kwargs["query_filter"])
        self.assertEqual(self.client.get("/api/search?corpus=beta&q=TitanDB&mode=vector").json["hits"], [])

    def test_service_isolates_two_internal_callers_without_browser_login(self):
        # Trusted in-process identities in an isolated fixture; NOT a production
        # tool endpoint accepting arbitrary user IDs from the model or network.
        for mode in ("keyword", "vector", "hybrid"):
            alice, _ = self.service.search(self.alice.id, "alpha", "TitanDB", mode)
            bob, _ = self.service.search(self.bob.id, "alpha", "TitanDB", mode)
            self.assertEqual({h["doc_id"] for h in alice["hits"]}, {"doc-0", "doc-1"})
            self.assertEqual({h["doc_id"] for h in bob["hits"]}, {"doc-2"})
        self.ids.bind(self.alice.id, "alpha", "alpha:a", False)
        self.assertEqual(self.service.search(self.alice.id, "alpha", "TitanDB")[0]["hits"], [])
        self.assertEqual({h["doc_id"] for h in self.service.search(self.bob.id, "alpha", "TitanDB")[0]["hits"]}, {"doc-2"})
        self.assertTrue(self.audit.verify().valid)

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

    def test_independent_named_admin_is_not_a_dataset_employee(self):
        account = self.ids.register(
            "https://issuer.example", "independent-admin-sub", "ContextLedger 管理员"
        )
        self.ids.update(account.id, role="admin")
        admin = self.ids.get(account.id)
        self.assertEqual(admin.name, "ContextLedger 管理员")
        self.assertEqual(admin.role, "admin")
        self.assertEqual(self.ids.scope(admin, "alpha"), ([], {}))
        with connect(self.db_path) as db:
            self.assertIsNone(
                db.execute("SELECT 1 FROM principals WHERE principal_id=?", (admin.id,)).fetchone()
            )
        same_account = self.ids.register(
            "https://issuer.example", "independent-admin-sub", "External display name"
        )
        self.assertEqual(same_account.id, admin.id)
        self.assertEqual(same_account.name, admin.name)
        self.login(admin)
        self.assertEqual(self.client.get("/api/admin/users").status_code, 200)
        self.assertEqual(
            self.client.get("/api/search?corpus=alpha&q=TitanDB&mode=hybrid").json["hits"], []
        )

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
