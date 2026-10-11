"""Real local Qdrant/SQLite + synthetic deterministic LLM transport, NOT model-quality proof."""
import json
import os
import unittest
import urllib.error
from unittest.mock import patch

import test_integration as fixture
from test_llm_workflows import completion, plan, stage
from contextledger.llm_workflows import AuditAnswerer, CitationReviewer, QueryPlanner, markers
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
        self.service.reviewer = CitationReviewer(stage("judge"), True)
        self.service.audit_answerer = AuditAnswerer(stage("audit-writer"))
        self.calls = []

    def transport(self, request, **kwargs):
        body = json.loads(request.data)
        payload = json.loads(body["messages"][1]["content"])
        model = body["model"]
        self.calls.append((model, payload))
        if "claims" in payload:
            evidence = {e["id"]:e["content"] for e in payload["authorised_evidence"]}
            result = {"claims": [{"claim_id":c["claim_id"], "verdict":"supported", "citations":[
                {"id":i, "quote":evidence[i][:100]} for i in sorted(markers(c["text"], "[E" in c["text"]))]} for c in payload["claims"]]}
        elif "original_query" in payload:
            result = plan(payload["original_query"], semantic_queries=[])
        elif "visible_events" in payload:
            eid = payload["visible_events"][0]["id"]
            result = {"status":"answered", "answer":f"本次记录显示有一次回答请求 [{eid}]。", "citation_ids":[eid], "uncertainty":"medium"}
        else:
            text = "TitanDB 的决定已获批准 [1]。" if "revision_context" not in payload else "本次资料提供 TitanDB 的说明，但审批状态需要另行确认 [1]。"
            result = {"status":"answered", "answer":text, "citation_ids":[1], "uncertainty":"low"}
        return completion(result, model)

    def ask(self, **extra):
        # Actual generation transport reads the environment key, never an exposed fixture login.
        with patch.dict(os.environ, {"LLM_API_KEY":"fixture-key"}), patch("urllib.request.urlopen", side_effect=self.transport):
            return self.post("/api/ask", {"corpus":"alpha","q":"TitanDB 用途","mode":"keyword",**extra})

    def test_full_pipeline_plan_first_filtered_branches_and_separate_review(self):
        self.enable_workflows()
        with patch.object(self.index, "search", wraps=self.index.search) as search:
            response = self.ask()
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual([m for m,_ in self.calls], ["planner","writer","judge"])
        self.assertEqual(self.calls[0][1], {"original_query":"TitanDB 用途"})
        self.assertEqual(self.calls[1][1]["original_question"], "TitanDB 用途")
        self.assertEqual({e["doc_id"] for e in response.json["evidence"]}, {"doc-0","doc-1"})
        self.assertEqual(response.json["citation_review"]["status"], "supported")
        self.assertIn("probabilistic", response.json["citation_review"]["guarantee"])
        self.assertEqual([c.kwargs["mode"] for c in search.call_args_list], ["keyword","keyword","vector"])
        self.assertTrue(all(c.args[0].actor.id == self.alice.id for c in search.call_args_list))
        event = self.audit.query(request_id=response.json["request_id"])[0]
        self.assertEqual(event["citation_review"]["status"], "supported")
        self.assertNotIn("fixture-key", json.dumps(event))

    def test_same_model_business_and_audit_use_separate_review_prompts(self):
        self.enable_workflows()
        self.service.reviewer.stage.model = "writer"
        response = self.ask(planning=False)
        self.assertEqual(response.json["decision"], "answered")
        self.assertEqual([m for m,_ in self.calls], ["writer", "writer"])
        self.assertNotIn("claims", self.calls[0][1])
        self.assertIn("claims", self.calls[1][1])
        self.assertEqual(response.json["citation_review"]["model_relation"], "same_model")
        self.login(self.admin)
        self.service.reviewer.stage.model = "audit-writer"
        self.calls.clear()
        with patch("urllib.request.urlopen", side_effect=self.transport):
            result = self.post("/api/audit/ask", {"q":"谁进行了查询？"})
        self.assertEqual(result.status_code, 200, result.json)
        self.assertEqual(result.json["decision"], "answered")
        self.assertEqual([m for m,_ in self.calls], ["audit-writer", "audit-writer"])
        self.assertIn("visible_events", self.calls[0][1])
        self.assertIn("claims", self.calls[1][1])
        self.assertEqual(result.json["citation_review"]["model_relation"], "same_model")
        event = self.audit.query(request_id=result.json["request_id"])[0]
        self.assertEqual(event["citation_review"]["independence"], "not_established")

    def test_baseline_switch_and_planner_failure_retain_original_query(self):
        self.enable_workflows()
        result = self.ask(planning=False)
        self.assertEqual(result.json["query_plan"]["status"], "disabled")
        self.assertEqual([m for m,_ in self.calls], ["writer","judge"])
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

    def test_unsupported_review_rewrites_once_without_second_review(self):
        self.enable_workflows()
        real_transport = self.transport
        def unsupported(request, **kwargs):
            if json.loads(request.data)["model"] == "judge":
                self.calls.append(("judge", json.loads(json.loads(request.data)["messages"][1]["content"])))
                return completion({"claims":[{"claim_id":"C1","verdict":"unsupported","reason":"请删除未证实的审批结论。","citations":[]}]}, "judge")
            return real_transport(request, **kwargs)
        self.transport = unsupported
        response = self.ask()
        self.assertEqual(response.json["decision"], "answered")
        self.assertEqual(response.json["citation_review"]["status"], "unsupported")
        self.assertNotIn("决定已获批准", response.json["answer"])
        self.assertNotIn("决定已获批准", self.audit.query(request_id=response.json["request_id"])[0]["answer"])
        self.assertEqual(len(response.json["evidence"]), 2)
        self.assertEqual([m for m,_ in self.calls], ["planner", "writer", "judge", "writer"])
        retry = self.calls[-1][1]
        self.assertEqual(retry["authorised_evidence"], self.calls[1][1]["authorised_evidence"])
        self.assertEqual(retry["original_question"], "TitanDB 用途")
        self.assertIn("请删除", retry["revision_context"]["review_feedback"][0]["reason"])
        self.assertEqual(response.json["regeneration"]["status"], "revised_not_reviewed")
        self.assertIn("未再次", response.json["answer_notice"])
        event = self.audit.query(request_id=response.json["request_id"])[0]
        self.assertEqual(event["regeneration"]["attempts"], 1)
        self.assertNotIn("请删除", json.dumps(event, ensure_ascii=False))
        self.assertNotIn("_feedback", event["citation_review"])

    def test_review_not_configured_is_not_success_and_disabled_is_explicit(self):
        self.enable_workflows()
        self.service.reviewer.stage.key = ""
        response = self.ask()
        self.assertEqual(response.json["decision"], "answered")
        self.assertEqual(response.json["citation_review"]["status"], "not_configured")
        self.assertEqual(response.json["regeneration"]["status"], "revised_not_reviewed")
        self.service.reviewer.enabled = False
        response = self.ask()
        self.assertEqual(response.json["decision"], "answered")
        self.assertEqual(response.json["citation_review"]["status"], "disabled")

    def test_review_network_failure_rewrites_once_but_does_not_retry_reviewer(self):
        self.enable_workflows()
        original = self.transport
        attempted = []
        def fail(request, **kwargs):
            if json.loads(request.data)["model"] == "judge":
                attempted.append("judge")
                raise urllib.error.URLError("fixture-key")
            return original(request, **kwargs)
        self.transport = fail
        response = self.ask()
        self.assertEqual(response.json["citation_review"]["status"], "api_unavailable")
        self.assertEqual(attempted, ["judge"])
        self.assertEqual(response.json["decision"], "answered")
        self.assertNotIn("决定已获批准", response.json["answer"])
        self.assertEqual(response.json["regeneration"]["attempts"], 1)

    def test_revision_invalid_citations_api_failure_or_insufficient_are_not_released(self):
        self.enable_workflows()
        original = self.transport
        for failure in ("citations", "api", "insufficient"):
            self.calls.clear()
            def respond(request, **kwargs):
                body = json.loads(request.data)
                payload = json.loads(body["messages"][1]["content"])
                if body["model"] == "judge":
                    self.calls.append(("judge", payload))
                    return completion({"claims":[{"claim_id":"C1","verdict":"uncertain","reason":"审批依据不明确。","citations":[]}]}, "judge")
                if "revision_context" in payload:
                    self.calls.append(("writer", payload))
                    if failure == "api":
                        raise urllib.error.URLError("fixture-key")
                    return completion({"status":"answered" if failure == "citations" else "insufficient",
                        "answer":"BAD SECOND DRAFT [99]" if failure == "citations" else "PRIVATE UNSUPPORTED PROSE",
                        "citation_ids":[99] if failure == "citations" else [], "uncertainty":"high"}, "writer")
                return original(request, **kwargs)
            self.transport = respond
            with self.subTest(failure=failure):
                result = self.ask(planning=False)
                self.assertEqual(result.status_code, 200)
                self.assertEqual(result.json["decision"], "insufficient")
                self.assertEqual([m for m,_ in self.calls], ["writer", "judge", "writer"])
                self.assertNotIn("BAD SECOND", result.json["answer"])
                self.assertNotIn("PRIVATE UNSUPPORTED", result.json["answer"])
                self.assertNotIn("fixture-key", json.dumps(result.json))

    def test_revision_revocation_version_and_http_delivery_fences(self):
        for change in ("revoke", "version", "delivery"):
            with self.subTest(change=change):
                self.ids.restrict(self.alice.id, "alpha", "source", "*", False)
                self.login(self.alice)
                self.enable_workflows()
                original = lambda request, **kwargs: LLMIntegrationTests.transport(self, request, **kwargs)
                def respond(request, **kwargs):
                    body = json.loads(request.data)
                    payload = json.loads(body["messages"][1]["content"])
                    if body["model"] == "judge":
                        return completion({"claims":[{"claim_id":"C1","verdict":"uncertain","citations":[]}]}, "judge")
                    result = original(request, **kwargs)
                    if "revision_context" in payload:
                        if change == "revoke":
                            self.ids.restrict(self.alice.id, "alpha", "source", "*", True)
                        if change == "version":
                            with connect(self.db_path) as db:
                                db.execute("UPDATE cl_index_state SET generation='changed'")
                    return result
                self.transport = respond
                from flask import jsonify as real_jsonify
                def deliver(*args, **kwargs):
                    result = real_jsonify(*args, **kwargs)
                    if args and isinstance(args[0], dict) and args[0].get("regeneration", {}).get("status") == "revised_not_reviewed":
                        self.ids.restrict(self.alice.id, "alpha", "source", "*", True)
                    return result
                with patch("contextledger.web.jsonify", side_effect=deliver if change == "delivery" else real_jsonify):
                    result = self.ask(planning=False)
                self.assertIn(result.status_code, (409, 503))
                self.assertNotIn("本次资料提供", result.get_data(as_text=True))
                self.assertNotIn("review_feedback", result.json)
                if change == "version":
                    with connect(self.db_path) as db:
                        db.execute("UPDATE cl_index_state SET generation='test-generation'")

    def test_audit_review_feedback_regenerates_once_with_only_redacted_events(self):
        self.enable_workflows()
        normal = self.ask()
        self.login(self.admin)
        self.calls.clear()
        original = self.transport
        def respond(request, **kwargs):
            body = json.loads(request.data)
            payload = json.loads(body["messages"][1]["content"])
            if body["model"] == "judge":
                self.calls.append(("judge", payload))
                return completion({"claims":[{"claim_id":"C1","verdict":"uncertain",
                    "reason":"REVIEW ONLY: 不能由局部结果推出完整统计。", "citations":[]}]}, "judge")
            return original(request, **kwargs)
        with patch("urllib.request.urlopen", side_effect=respond):
            result = self.post("/api/audit/ask", {"q":"谁查询了信息？", "request_id":normal.json["request_id"]})
        self.assertEqual(result.status_code, 200, result.json)
        self.assertEqual([m for m,_ in self.calls], ["audit-writer", "judge", "audit-writer"])
        self.assertEqual(self.calls[0][1]["visible_events"], self.calls[-1][1]["visible_events"])
        self.assertNotIn("TitanDB", json.dumps(self.calls[-1][1]))
        self.assertEqual(result.json["decision"], "answered")
        self.assertEqual(result.json["citation_review"]["status"], "uncertain")
        self.assertEqual(result.json["regeneration"]["status"], "revised_not_reviewed")
        self.assertIn("未再次", result.json["answer_notice"])
        event = self.audit.query(request_id=result.json["request_id"])[0]
        self.assertNotIn("REVIEW ONLY", json.dumps(event, ensure_ascii=False))
        self.assertTrue(self.audit.verify().valid)

    def test_audit_revision_wrong_namespace_falls_back_and_role_revocation_blocks(self):
        self.enable_workflows()
        normal = self.ask()
        self.login(self.admin)
        original = self.transport
        for failure in ("citations", "role", "integrity"):
            self.ids.update(self.admin.id, role="admin")
            self.login(self.admin)
            def respond(request, **kwargs):
                body = json.loads(request.data)
                payload = json.loads(body["messages"][1]["content"])
                if body["model"] == "judge":
                    return completion({"claims":[{"claim_id":"C1","verdict":"uncertain","citations":[]}]}, "judge")
                if "revision_context" in payload:
                    if failure == "citations":
                        return completion({"status":"answered", "answer":"BAD AUDIT SECOND [1]",
                            "citation_ids":["1"], "uncertainty":"low"}, "audit-writer")
                    if failure == "role":
                        self.ids.update(self.admin.id, role="member")
                    if failure == "integrity":
                        with self.audit.db() as db:
                            db.execute("UPDATE events SET payload='{}' WHERE sequence=1")
                return original(request, **kwargs)
            with self.subTest(failure=failure), patch("urllib.request.urlopen", side_effect=respond):
                result = self.post("/api/audit/ask", {"q":"谁查询？", "request_id":normal.json["request_id"]})
            if failure == "citations":
                self.assertEqual(result.status_code, 200)
                self.assertEqual(result.json["provider"], "deterministic")
                self.assertNotIn("BAD AUDIT SECOND", result.json["answer"])
                self.assertEqual(result.json["regeneration"]["attempts"], 1)
            else:
                self.assertIn(result.status_code, (403, 409, 503))
                self.assertNotIn("review_feedback", result.json)

    def test_new_ui_controls_and_api_input_types(self):
        html = self.client.get("/").get_data(as_text=True)
        self.assertIn('id="planning"', html)
        self.assertIn('id="auditask"', html)
        self.assertIn('id="auditanswer"', html)
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

    def test_revocation_during_planning_generation_and_review_never_delivers(self):
        self.enable_workflows()
        original = self.transport
        for during in ("planner", "writer", "judge"):
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

    def test_snapshot_change_during_review_blocks_delivery_without_draft(self):
        self.enable_workflows()
        original = self.transport
        def change(request, **kwargs):
            response = original(request, **kwargs)
            if json.loads(request.data)["model"] == "judge":
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
        self.assertEqual([m for m,_ in self.calls], ["audit-writer","judge"])
        supplied = json.dumps(self.calls[0][1], ensure_ascii=False)
        self.assertNotIn("TitanDB", supplied)
        self.assertNotIn("SECRET", supplied)
        self.assertNotIn("doc-0", supplied)
        self.assertEqual(response.json["citation_review"]["status"], "supported")
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
