import io
import json
import os
import unittest
import urllib.error
from unittest.mock import Mock, patch

from contextledger.llm_workflows import (AuditAnswerer, CitationReviewer, ModelStage,
                                        QueryPlanner, MAX_BRANCHES)


def completion(payload, model="fixture-model", **extra):
    return io.BytesIO(json.dumps({"model": model, "choices": [{"finish_reason": "stop",
        "message": {"content": json.dumps(payload, ensure_ascii=False)}}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}, **extra}).encode())


def plan(query="TitanDB 用途", **changes):
    return {"original_query": query, "sub_questions": ["What is TitanDB?"],
            "keywords": ["TitanDB"], "semantic_queries": ["TitanDB purpose"],
            "entity_candidates": [], "possible_interpretations": [],
            "needs_clarification": False, **changes}


def stage(model="fixture-model"):
    return ModelStage(model, "https://example.test/v1", "fixture-key")


class WorkflowTests(unittest.TestCase):
    def test_transport_bounds_parameters_usage_and_guard(self):
        guard = Mock()
        captured = {}
        def respond(request, **kwargs):
            captured.update(json.loads(request.data))
            return completion({"safe": True})
        with patch("urllib.request.urlopen", side_effect=respond):
            raw, diag = stage().complete("system", {"original_question": "q"}, "v1", guard)
        self.assertEqual(raw, {"safe": True})
        self.assertEqual(guard.call_count, 2)
        self.assertEqual(diag["usage"]["total_tokens"], 120)
        self.assertEqual(diag["attempts"], 1)
        self.assertEqual(captured["temperature"], 0)
        self.assertEqual(captured["response_format"], {"type": "json_object"})
        self.assertNotIn("fixture-key", json.dumps(diag))

    def test_network_failure_has_no_retry_and_no_secret(self):
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("fixture-key")) as call:
            raw, diag = stage().complete("s", {}, "v", Mock())
        self.assertIsNone(raw)
        self.assertEqual(diag["status"], "api_unavailable")
        self.assertEqual(call.call_count, 1)
        self.assertNotIn("fixture-key", json.dumps(diag))

    def test_response_and_input_budgets_invalid_json_and_security_guard(self):
        for response in (io.BytesIO(b"x" * 131073), completion([], finish_reason="stop"),
                         io.BytesIO(b"not json")):
            with self.subTest(response=response), patch("urllib.request.urlopen", return_value=response):
                self.assertEqual(stage().complete("s", {}, "v", Mock())[1]["status"], "invalid_output")
        with patch("urllib.request.urlopen") as call:
            self.assertEqual(stage().complete("s", {"text": "x" * 60001}, "v", Mock())[1]["status"], "input_budget_exceeded")
            call.assert_not_called()
        with self.assertRaises(PermissionError):
            stage().complete("s", {}, "v", Mock(side_effect=PermissionError("revoked")))

    def test_planner_only_original_question_and_bounded_branches(self):
        planner = QueryPlanner(stage(), enabled=True)
        captured = {}
        def respond(request, **kwargs):
            captured.update(json.loads(request.data))
            return completion(plan(sub_questions=["TitanDB purpose", "TitanDB clients", "TitanDB status"],
                                   semantic_queries=["TitanDB responsibilities", "TitanDB data", "TitanDB usage"]))
        with patch("urllib.request.urlopen", side_effect=respond):
            result, diag = planner.plan("TitanDB 用途", Mock())
        payload = json.loads(captured["messages"][1]["content"])
        self.assertEqual(payload, {"original_query": "TitanDB 用途"})
        branches = planner.branches("TitanDB 用途", "hybrid", result)
        self.assertEqual(branches[0], ("hybrid", "TitanDB 用途"))
        self.assertIn(("keyword", "TitanDB"), branches)
        self.assertEqual(len(branches), MAX_BRANCHES)
        self.assertEqual(diag["status"], "planned")

    def test_planner_rejects_overbudget_filters_changed_question_and_negation(self):
        bad_plans = [plan(keywords=["TitanDB"] * 9), plan(principal="admin"),
                     plan(original_query="another question"), plan(keywords=["secret"]),
                     plan("TitanDB not approved before 2026-10-01", sub_questions=["TitanDB approved"],
                          semantic_queries=[])]
        for payload in bad_plans:
            q = "TitanDB not approved before 2026-10-01" if "not" in payload["original_query"] else "TitanDB 用途"
            with self.subTest(payload=payload), patch("urllib.request.urlopen", return_value=completion(payload)):
                result, diag = QueryPlanner(stage(), True).plan(q, Mock())
            self.assertIsNone(result)
            self.assertEqual(diag["status"], "invalid_plan")

    def test_planner_entity_changes_require_confirmation_and_no_auto_replacement(self):
        payload = plan(entity_candidates=["TiDB"])
        with patch("urllib.request.urlopen", return_value=completion(payload)):
            result, diag = QueryPlanner(stage(), True).plan("TitanDB 用途", Mock())
        self.assertTrue(result["needs_clarification"])
        self.assertEqual(diag["status"], "clarification_required")
        self.assertEqual(QueryPlanner.branches("TitanDB 用途", "keyword", result), [("keyword", "TitanDB 用途")])

    def test_multiple_named_entities_can_split_without_silent_new_entity(self):
        query = "比较 TitanDB 和 Redis 的用途"
        payload = plan(query, sub_questions=["What is TitanDB?", "What is Redis?"],
                       keywords=["TitanDB", "Redis"], semantic_queries=[])
        with patch("urllib.request.urlopen", return_value=completion(payload)):
            result, diag = QueryPlanner(stage(), True).plan(query, Mock())
        self.assertEqual(diag["status"], "planned")
        self.assertFalse(result["needs_clarification"])

    def test_reviewer_requires_different_configured_and_reported_model(self):
        reviewer = CitationReviewer(stage("writer"), True)
        with patch("urllib.request.urlopen") as call:
            self.assertEqual(reviewer.review("q", "Approved [1]", [{"id":"1","content":"Approved"}], "writer", Mock())["status"], "same_model_rejected")
            self.assertEqual(reviewer.review("q", "Approved [1]", [{"id":"1","content":"Approved"}], "writer-v2", Mock(),
                             generation_configured_model="writer")["status"], "same_model_rejected")
            call.assert_not_called()
        reviewer.stage.model = "alias"
        payload = {"claims": [{"claim_id":"C1", "verdict":"supported", "citations":[{"id":"1","quote":"Approved"}]}]}
        with patch("urllib.request.urlopen", return_value=completion(payload, "writer")):
            self.assertEqual(reviewer.review("q", "Approved [1]", [{"id":"1","content":"Approved"}], "writer", Mock())["status"], "same_model_rejected")

    def test_reviewer_coverage_quote_membership_and_verdict(self):
        good = {"claims": [{"claim_id":"C1", "verdict":"supported", "citations":[{"id":"1","quote":"Approved"}]},
                           {"claim_id":"C2", "verdict":"supported", "citations":[{"id":"2","quote":"Pending"}]}]}
        variants = [(good, "supported"), ({"claims":good["claims"][:1]}, "invalid_review")]
        for field, value, expected in (("quote", "Fabricated", "invalid_review"), ("id", "99", "invalid_review")):
            wrong = json.loads(json.dumps(good))
            wrong["claims"][0]["citations"][0][field] = value
            variants.append((wrong, expected))
        for verdict in ("uncertain", "unsupported"):
            wrong = json.loads(json.dumps(good))
            wrong["claims"][0]["verdict"] = verdict
            variants.append((wrong, verdict))
        for payload, expected in variants:
            with self.subTest(expected=expected), patch("urllib.request.urlopen", return_value=completion(payload, "judge")):
                diag = CitationReviewer(stage("judge"), True).review("q", "Approved [1]\n\nPending [2]",
                    [{"id":"1","content":"Approved"},{"id":"2","content":"Pending"}], "writer", Mock())
            self.assertEqual(diag["status"], expected)

    def test_reviewer_uncited_block_cannot_be_omitted_or_approved(self):
        with patch("urllib.request.urlopen") as call:
            diag = CitationReviewer(stage("judge"), True).review("q", "Approved [1]\n\nUnsupported extra fact",
                [{"id":"1","content":"Approved"}], "writer", Mock())
        self.assertEqual(diag["status"], "unsupported")
        call.assert_not_called()

    def test_audit_answer_validates_event_namespace_and_selection(self):
        valid = {"status":"answered","answer":"A query occurred [E8].","citation_ids":["E8"],"uncertainty":"low"}
        for payload, expected in ((valid, "completed"), (dict(valid, citation_ids=["E9"]), "invalid_audit_answer"),
                                  (dict(valid, answer="A query occurred [1]."), "invalid_audit_answer")):
            with self.subTest(expected=expected), patch("urllib.request.urlopen", return_value=completion(payload)):
                answer, diag = AuditAnswerer(stage()).answer("What happened?", [{"id":"E8","decision":"allowed"}],
                    {"truncated":False}, Mock())
            self.assertEqual(diag["status"], expected)
            self.assertEqual(answer is not None, expected == "completed")


if __name__ == "__main__":
    unittest.main()
