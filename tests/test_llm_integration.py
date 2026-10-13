"""Real local Qdrant/SQLite + synthetic deterministic LLM transport, NOT model-quality proof."""
import json
import os
import unittest
import urllib.error
from unittest.mock import patch

import test_integration as fixture
from test_llm_workflows import completion, plan, stage
from contextledger.llm_workflows import AuditAnswerer, QueryPlanner
from contextledger.store import connect
from src.answering import AnswerService, empty_evidence_answer


class LLMIntegrationTests(unittest.TestCase):
    setUp = fixture.IntegrationTests.setUp
    login = fixture.IntegrationTests.login
    post = fixture.IntegrationTests.post

    def enable_workflows(self):
        with patch.dict(os.environ, {"LLM_API_KEY":"fixture-key", "LLM_PROVIDER":"openai_compatible", "LLM_MODEL":"writer",
                                    "LLM_BASE_URL":"https://example.test/v1"}):
            self.service.answer = AnswerService()
        self.service.planner = QueryPlanner(stage("planner"), True)
        self.service.audit_answerer = AuditAnswerer(stage("audit-writer"))
        self.calls = []

    def transport(self, request, **kwargs):
        body = json.loads(request.data)
        payload = json.loads(body["messages"][1]["content"])
        model = body["model"]
        self.calls.append((model, payload))
        if "original_query" in payload:
            result = plan(payload["original_query"], semantic_queries=[])
        elif "visible_events" in payload:
            eid = payload["visible_events"][0]["id"]
            result = {"status":"answered", "answer":f"本次记录显示有一次回答请求 [{eid}]。", "citation_ids":[eid], "uncertainty":"medium"}
        else:
            text = "TitanDB 的决定已获批准 [1]。"
            result = {"status":"answered", "answer":text, "citation_ids":[1], "uncertainty":"low"}
        return completion(result, model)

    def ask(self, **extra):
        # Actual generation transport reads the environment key, never an exposed fixture login.
        with patch.dict(os.environ, {"LLM_API_KEY":"fixture-key"}), patch("urllib.request.urlopen", side_effect=self.transport):
            return self.post("/api/ask", {"corpus":"alpha","q":"TitanDB 用途","mode":"keyword",**extra})

    def test_full_pipeline_plan_first_filtered_branches_without_review(self):
        self.enable_workflows()
        with patch.object(self.index, "search", wraps=self.index.search) as search:
            response = self.ask()
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual([m for m,_ in self.calls], ["planner","writer"])
        self.assertEqual(self.calls[0][1], {"original_query":"TitanDB 用途"})
        self.assertEqual(self.calls[1][1]["original_question"], "TitanDB 用途")
        self.assertEqual({e["doc_id"] for e in response.json["evidence"]}, {"doc-0","doc-1"})
        self.assertNotIn("citation_review", response.json)
        self.assertNotIn("regeneration", response.json)
        self.assertEqual([c.kwargs["mode"] for c in search.call_args_list], ["keyword","keyword","vector"])
        self.assertTrue(all(c.args[0].actor.id == self.alice.id for c in search.call_args_list))
        event = self.audit.query(request_id=response.json["request_id"])[0]
        self.assertNotIn("citation_review", event)
        self.assertNotIn("fixture-key", json.dumps(event))

    def test_legacy_review_config_cannot_enable_review_or_rewrite(self):
        self.enable_workflows()
        with patch.dict(os.environ, {"LLM_REVIEW_ENABLED":"true", "LLM_REVIEW_MODEL":"judge", "LLM_REVIEW_API_KEY":"obsolete"}):
            self.service = type(self.service)(self.index, self.ids, self.audit, self.service.answer,
                planner=self.service.planner, audit_answerer=self.service.audit_answerer)
            self.app.config["TESTING"] = True
            self.assertFalse(hasattr(self.service, "reviewer"))
            with patch.dict(os.environ, {"LLM_API_KEY":"fixture-key"}), patch("urllib.request.urlopen", side_effect=self.transport):
                result, _ = self.service.ask(self.alice.id, "alpha", "TitanDB 用途", "keyword", planning=False)
        self.assertEqual(result["decision"], "answered")
        self.assertEqual([m for m, _ in self.calls], ["writer"])
        self.assertFalse({"citation_review", "regeneration", "review_feedback", "answer_notice"} & result.keys())
        self.assertNotIn("revision_context", self.calls[0][1])
        self.login(self.admin)
        self.calls.clear()
        with patch("urllib.request.urlopen", side_effect=self.transport):
            audited = self.service.audit_query(self.admin.id, query="谁查询了什么？", generate=True)
        self.assertEqual(audited["decision"], "answered")
        self.assertEqual([m for m, _ in self.calls], ["audit-writer"])
        self.assertFalse({"citation_review", "regeneration", "review_feedback"} & audited.keys())

    def test_generation_invalid_citation_still_fails_closed(self):
        self.enable_workflows()
        self.service.planner.enabled = False
        def wrong(request, **kwargs):
            self.calls.append(json.loads(request.data))
            return completion({"status":"answered", "answer":"Unrelated claim [999]", "citation_ids":[999], "uncertainty":"low"}, "writer")
        self.transport = wrong
        result = self.ask()
        self.assertEqual(result.json["provider"], "mock_fallback")
        self.assertNotIn("Unrelated claim", result.json["answer"])
        self.assertEqual(len(self.calls), 2)  # Existing bounded format retry, not model review.

    def test_audit_wrong_citation_and_api_failure_fall_back_without_review(self):
        self.enable_workflows()
        normal = self.ask(planning=False)
        self.login(self.admin)
        for failure in ("wrong_citation", "api_failure"):
            with self.subTest(failure=failure):
                self.calls.clear()
                def fail(request, **kwargs):
                    self.calls.append(json.loads(request.data))
                    if failure == "api_failure":
                        raise urllib.error.URLError("fixture-key")
                    return completion({"status":"answered", "answer":"Invented [E9999]", "citation_ids":["E9999"], "uncertainty":"low"}, "audit-writer")
                with patch("urllib.request.urlopen", side_effect=fail):
                    result = self.post("/api/audit/ask", {"q":"谁查询过信息？", "request_id":normal.json["request_id"]})
                self.assertEqual(result.status_code, 200)
                self.assertEqual(result.json["provider"], "deterministic")
                self.assertNotIn("Invented", result.json["answer"])
                self.assertEqual(len(self.calls), 1)

    def test_permission_change_at_answer_http_delivery_still_discards(self):
        self.enable_workflows()
        from flask import jsonify as real_jsonify
        def revoke(*args, **kwargs):
            response = real_jsonify(*args, **kwargs)
            if args and isinstance(args[0], dict) and args[0].get("decision") == "answered":
                self.ids.restrict(self.alice.id, "alpha", "source", "*", True)
            return response
        with patch("contextledger.web.jsonify", side_effect=revoke):
            result = self.ask(planning=False)
        self.assertEqual(result.status_code, 409)
        self.assertNotIn("决定已获批准", result.get_data(as_text=True))

    def test_baseline_switch_and_planner_failure_retain_original_query(self):
        self.enable_workflows()
        result = self.ask(planning=False)
        self.assertEqual(result.json["query_plan"]["status"], "disabled")
        self.assertEqual([m for m,_ in self.calls], ["writer"])
        real_transport = self.transport
        def offline(request, **kwargs):
            if json.loads(request.data)["model"] == "planner":
                raise urllib.error.URLError("fixture-key")
            return real_transport(request, **kwargs)
        self.transport = offline
        result = self.ask()
        self.assertEqual(result.json["query_plan"]["status"], "api_unavailable")
        self.assertEqual(result.json["query_plan"]["branch_count"], 1)
        self.assertEqual(result.json["decision"], "answered")

    def test_entity_correction_needs_confirmation_without_search_or_generation(self):
        self.enable_workflows()
        def clarify(request, **kwargs):
            self.calls.append(json.loads(request.data))
            return completion(plan(entity_candidates=["TiDB"]), "planner")
        self.transport = clarify
        with patch.object(self.index, "search", wraps=self.index.search) as search:
            result = self.ask()
        self.assertEqual(result.json["decision"], "clarification_required")
        self.assertEqual(result.json["evidence"], [])
        self.assertEqual(len(self.calls), 1)
        self.assertNotIn("TiDB", result.json["answer"])
        search.assert_not_called()

    def test_new_ui_controls_and_api_input_types(self):
        html = self.client.get("/").get_data(as_text=True)
        self.assertIn('id="planning-toggle"', html)
        self.assertIn('id="planner-availability"', html)
        self.assertIn('id="query-plan-status"', html)
        self.assertIn('id="audit-ask"', html)
        self.assertIn('id="audit-answer"', html)
        self.assertNotIn('id="reviewfeedback"', html)
        self.assertNotIn("首次回答单独调用", html)
        self.assertNotIn("review_enabled", self.client.get("/api/session").json["workflows"])
        response = self.post("/api/ask", {"q":"TitanDB", "corpus":"alpha", "planning":"admin"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.post("/api/ask", ["invalid"]).status_code, 400)

    def test_audit_chain_tamper_at_http_delivery_blocks_response(self):
        self.enable_workflows()
        normal = self.ask()
        self.login(self.admin)
        from flask import jsonify as real_jsonify
        def corrupt(*args, **kwargs):
            response = real_jsonify(*args, **kwargs)
            if args and isinstance(args[0], dict) and "events" in args[0]:
                with self.audit.db() as db:
                    db.execute("UPDATE events SET payload='{}' WHERE sequence=1")
            return response
        with patch("contextledger.web.jsonify", side_effect=corrupt):
            response = self.client.get("/api/audit?request_id=" + normal.json["request_id"])
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("events", response.json)

    def test_revocation_during_planning_and_generation_never_delivers(self):
        self.enable_workflows()
        original = self.transport
        for during in ("planner", "writer"):
            with self.subTest(during=during):
                self.ids.restrict(self.alice.id, "alpha", "source", "*", False)
                def revoke(request, **kwargs):
                    result = original(request, **kwargs)
                    if json.loads(request.data)["model"] == during:
                        self.ids.restrict(self.alice.id, "alpha", "source", "*", True)
                    return result
                self.transport = revoke
                response = self.ask()
                self.assertEqual(response.status_code, 409, response.json)
                self.assertNotIn("决定已获批准", response.get_data(as_text=True))

    def test_snapshot_change_during_generation_blocks_delivery_without_answer(self):
        self.enable_workflows()
        original = self.transport
        def change(request, **kwargs):
            response = original(request, **kwargs)
            if json.loads(request.data)["model"] == "writer":
                with connect(self.db_path) as db:
                    db.execute("UPDATE documents SET version='changed' WHERE doc_id='doc-0'")
            return response
        self.transport = change
        response = self.ask()
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("决定已获批准", response.get_data(as_text=True))

    def test_snapshot_change_between_planned_branches_never_calls_generator(self):
        self.enable_workflows()
        original = self.index.search
        def change_after_first(*args, **kwargs):
            result = original(*args, **kwargs)
            with connect(self.db_path) as db:
                db.execute("UPDATE cl_index_state SET generation='new-generation'")
            return result
        with patch.object(self.index, "search", side_effect=change_after_first):
            response = self.ask()
        self.assertEqual(response.status_code, 503)
        self.assertEqual([m for m,_ in self.calls], ["planner"])

    def test_zero_evidence_demo_keeps_session_binding_and_reconstructs_audit(self):
        self.enable_workflows()
        before = self.ask()
        self.assertEqual(before.json["decision"], "answered")
        doc = before.json["evidence"][0]["doc_id"]
        self.login(self.admin)
        changed = self.post("/api/admin/permissions", {"user_id":self.alice.id,"action":"restriction",
            "corpus":"alpha","kind":"source","value":"*","denied":True})
        self.assertEqual(changed.status_code, 200)
        self.login(self.alice)
        self.calls.clear()
        after = self.ask()
        self.assertEqual(after.json["answer"], empty_evidence_answer("TitanDB 用途"))
        self.assertEqual(after.json["evidence"], [])
        self.assertEqual(self.calls, [])
        self.assertTrue(self.client.get("/api/session").json["authenticated"])
        self.assertTrue(self.ids.get(self.alice.id).enabled)
        self.assertEqual(self.ids.scope(self.ids.get(self.alice.id), "alpha")[0], ["alpha:a"])
        self.assertIn("alpha", [c["id"] for c in self.client.get("/api/corpora").json])
        self.assertEqual(self.client.get(f"/api/doc?corpus=alpha&doc_id={doc}").status_code, 404)
        self.login(self.bob)
        self.assertEqual(self.client.get("/api/search?corpus=alpha&q=TitanDB&mode=keyword&planning=false").json["hits"][0]["doc_id"], "doc-2")
        self.login(self.admin)
        audited = self.client.get("/api/audit?user_id=" + self.alice.id).json
        event = next(e for e in audited["events"] if e["request_id"] == after.json["request_id"])
        self.assertEqual(event["returned_evidence_count"], 0)
        self.assertEqual(event["decision"], "insufficient")
        self.assertTrue(audited["integrity"]["valid"])
        self.ids.restrict(self.alice.id, "alpha", "source", "*", False)  # Only the fixture's temporary rule.

    def test_unknown_question_and_denied_query_share_neutral_response(self):
        self.enable_workflows()
        self.service.planner.enabled = False
        with patch("urllib.request.urlopen") as call:
            unknown, _ = self.service.ask(self.alice.id, "alpha", "UnknownDB 是什么", "keyword")
            self.ids.restrict(self.alice.id, "alpha", "source", "*", True)
            denied, _ = self.service.ask(self.alice.id, "alpha", "TitanDB 是什么", "keyword")
        self.assertEqual(unknown["answer"], denied["answer"])
        call.assert_not_called()

    def test_audit_models_read_only_whitelisted_redacted_events_and_role_guard(self):
        self.enable_workflows()
        normal = self.ask()
        self.assertEqual(self.post("/api/audit/ask", {"q":"谁查询了什么？"}).status_code, 403)
        self.service.record(self.ids.get(self.alice.id), "answer", question="PRIVATE NAME",
            query_plan={"private":"SECRET IN EXTRAS"}, answer="SECRET RAW ANSWER")
        self.login(self.admin)  # Admin has NO implicit business-reading permissions.
        self.calls.clear()
        with patch("urllib.request.urlopen", side_effect=self.transport):
            response = self.post("/api/audit/ask", {"q":"谁查询了什么？", "request_id":normal.json["request_id"]})
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual([m for m,_ in self.calls], ["audit-writer"])
        supplied = json.dumps(self.calls[0][1], ensure_ascii=False)
        self.assertNotIn("TitanDB", supplied)
        self.assertNotIn("SECRET", supplied)
        self.assertNotIn("doc-0", supplied)
        self.assertNotIn("citation_review", response.json)
        self.assertIn("[E", response.json["answer"])
        self.assertNotIn("_delivery_guards", response.json)
        self.assertNotIn("SECRET", json.dumps(self.client.get("/api/audit").json))
        self.assertTrue(self.audit.verify().valid)

    def test_audit_revocation_and_version_change_during_models_and_http_delivery(self):
        self.enable_workflows()
        normal = self.ask()
        self.ids.bind(self.admin.id, "alpha", "alpha:a", True)
        self.login(self.admin)
        original = self.transport
        def revoke(request, **kwargs):
            response = original(request, **kwargs)
            if json.loads(request.data)["model"] == "audit-writer":
                self.ids.bind(self.admin.id, "alpha", "alpha:a", False)
            return response
        with patch("urllib.request.urlopen", side_effect=revoke):
            response = self.post("/api/audit/ask", {"q":"查询了什么", "request_id":normal.json["request_id"]})
        self.assertEqual(response.status_code, 409)
        self.ids.bind(self.admin.id, "alpha", "alpha:a", True)
        from flask import jsonify as real_jsonify
        def change_before_http(*args, **kwargs):
            response = real_jsonify(*args, **kwargs)
            if args and isinstance(args[0], dict) and "events" in args[0]:
                with connect(self.db_path) as db:
                    db.execute("UPDATE documents SET version='changed' WHERE doc_id='doc-0'")
            return response
        with patch("contextledger.web.jsonify", side_effect=change_before_http):
            response = self.client.get("/api/audit?request_id=" + normal.json["request_id"])
        self.assertEqual(response.status_code, 409)
        self.assertNotIn("TitanDB fact", response.get_data(as_text=True))

    def test_audit_empty_selection_skips_models_and_partial_selection_warns(self):
        self.enable_workflows()
        self.login(self.admin)
        with patch("urllib.request.urlopen") as call:
            result = self.post("/api/audit/ask", {"q":"谁查询过信息？", "request_id":"no-matching-request"})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json["events"], [])
        self.assertIn("不能证明", result.json["answer"])
        call.assert_not_called()
        for i in range(22):
            self.service.record(self.ids.get(self.alice.id), "test")
        with patch("urllib.request.urlopen", side_effect=self.transport):
            result = self.post("/api/audit/ask", {"q":"谁查询过信息？"})
        self.assertTrue(result.json["selection"]["truncated"])
        self.assertEqual(result.json["selection"]["model_event_count"], 20)
        self.assertIn("不能据此统计", result.json["answer"])
        self.assertTrue(self.calls[-1][1]["selection"]["truncated"])

    def test_audit_integrity_failure_blocks_models(self):
        self.enable_workflows()
        self.service.record(self.ids.get(self.alice.id), "test")
        self.login(self.admin)
        with self.audit.db() as db:
            db.execute("UPDATE events SET payload='{}' WHERE sequence=1")
        with patch("urllib.request.urlopen") as call:
            result = self.post("/api/audit/ask", {"q":"谁查询过信息？"})
        self.assertEqual(result.status_code, 503)
        call.assert_not_called()


if __name__ == "__main__":
    unittest.main()
