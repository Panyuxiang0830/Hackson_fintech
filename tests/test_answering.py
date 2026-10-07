import io
import json
import os
from pathlib import Path
import unittest
import urllib.error
from unittest.mock import patch

from src.answering import AnswerService
from src.data import load_documents, load_users
from src.models import Evidence


class AnswerServiceTests(unittest.TestCase):
    def setUp(self):
        documents = load_documents()[:2]
        self.evidence = [
            Evidence(document=document, score=1.0, access_reason="test access")
            for document in documents
        ]
        self.user = load_users()["alice"]
        self.live_environment = {
            "LLM_PROVIDER": "openai_compatible",
            "LLM_BASE_URL": "https://example.test/v1",
            "LLM_API_KEY": "test-key",
            "LLM_MODEL": "glm-5.3-flash",
            "LLM_REASONING_EFFORT": "low",
        }

    @staticmethod
    def _response(content: dict) -> io.BytesIO:
        body = {"choices": [{"message": {"content": json.dumps(content)}}]}
        return io.BytesIO(json.dumps(body).encode("utf-8"))

    def test_valid_structured_answer_uses_only_supplied_citations(self):
        captured_request = {}

        def fake_urlopen(request, timeout, context):
            captured_request.update(json.loads(request.data))
            return self._response(
                {
                    "status": "answered",
                    "answer": "The release is approved [1] and tracked in Jira [2].",
                    "citation_ids": [1, 2],
                    "uncertainty": "low",
                }
            )

        with patch.dict(os.environ, self.live_environment, clear=True):
            answerer = AnswerService()
            with patch("urllib.request.urlopen", side_effect=fake_urlopen):
                answer, decision, provider = answerer.answer(
                    self.user,
                    "Is the release approved?",
                    self.evidence,
                )

        self.assertEqual(decision, "answered")
        self.assertEqual(provider, "openai_compatible/glm-5.3-flash")
        self.assertIn("[1]", answer)
        self.assertEqual(captured_request["response_format"], {"type": "json_object"})
        prompt = captured_request["messages"][1]["content"]
        self.assertIn("source=confluence", prompt)
        self.assertIn("source=jira", prompt)

    def test_documented_prompt_snapshot_matches_actual_request(self):
        captured_request = {}

        def fake_urlopen(request, timeout, context):
            captured_request.update(json.loads(request.data))
            return self._response(
                {
                    "status": "answered",
                    "answer": "The evidence supports this answer [1].",
                    "citation_ids": [1],
                    "uncertainty": "medium",
                }
            )

        with patch.dict(os.environ, self.live_environment, clear=True):
            with patch("urllib.request.urlopen", side_effect=fake_urlopen):
                AnswerService().answer(self.user, "What does the evidence say?", self.evidence)

        guide = (
            Path(__file__).resolve().parents[1]
            / "docs/product/prompt-and-login-walkthrough.md"
        ).read_text(encoding="utf-8")
        actual_system = captured_request["messages"][0]["content"]
        self.assertIn(" ".join(actual_system.split()), " ".join(guide.split()))
        actual_user = captured_request["messages"][1]["content"]
        for field in ("Identity:", "Question:", "Authorised Top-K evidence:", "source_updated=", "freshness="):
            self.assertIn(field, actual_user)
        self.assertEqual(captured_request["temperature"], 0)
        self.assertEqual(captured_request["max_tokens"], 1000)

    def test_out_of_range_model_citation_triggers_deterministic_fallback(self):
        unsafe_response = self._response(
            {
                "status": "answered",
                "answer": "An unsupported claim [99].",
                "citation_ids": [99],
                "uncertainty": "low",
            }
        )
        with patch.dict(os.environ, self.live_environment, clear=True):
            answerer = AnswerService()
            with patch("urllib.request.urlopen", return_value=unsafe_response):
                answer, decision, provider = answerer.answer(
                    self.user,
                    "Invent a citation",
                    self.evidence,
                )

        self.assertEqual(decision, "insufficient")
        self.assertEqual(provider, "mock_fallback")
        self.assertIn("No reliable answer", answer)
        self.assertNotIn("[99]", answer)

    def test_endpoint_failure_triggers_deterministic_fallback(self):
        with patch.dict(os.environ, self.live_environment, clear=True):
            answerer = AnswerService()
            with patch(
                "urllib.request.urlopen",
                side_effect=urllib.error.URLError("offline"),
            ):
                answer, decision, provider = answerer.answer(
                    self.user,
                    "Is the service online?",
                    self.evidence,
                )

        self.assertEqual(decision, "insufficient")
        self.assertEqual(provider, "mock_fallback")
        self.assertIn("model API unavailable", answer)

    def test_inconsistent_refusal_gets_one_strict_retry_and_not_fragment_synthesis(self):
        bad = {"status":"insufficient", "answer":"资料不足 [1]", "citation_ids":[], "uncertainty":"high"}
        safe = {"status":"insufficient", "answer":"现有授权资料不足以回答这个问题。", "citation_ids":[], "uncertainty":"high"}
        with patch.dict(os.environ, self.live_environment, clear=True):
            answerer = AnswerService()
            with patch("urllib.request.urlopen", side_effect=[self._response(bad), self._response(safe)]) as transport:
                answer, decision, provider = answerer.answer(self.user, "TibanDB是做什么的", self.evidence)
        self.assertEqual(transport.call_count, 2)
        self.assertEqual(decision, "insufficient")
        self.assertEqual(provider, "openai_compatible/glm-5.3-flash")
        self.assertNotIn("[1]", answer)
        self.assertEqual(answerer.last_diagnostics["failures"], ["citation_validation_failed"])

    def test_repeated_invalid_output_refuses_in_chinese_without_leaking_response(self):
        bad = {"status":"answered", "answer":"UNSAFE GENERATED CONTENT [99]", "citation_ids":[99], "uncertainty":"low"}
        with patch.dict(os.environ, self.live_environment, clear=True):
            answerer = AnswerService()
            with patch("urllib.request.urlopen", side_effect=lambda *a,**k:self._response(bad)) as transport:
                answer, decision, provider = answerer.answer(self.user, "请回答", self.evidence)
        self.assertEqual(transport.call_count, 2)
        self.assertEqual(decision, "insufficient")
        self.assertEqual(provider, "mock_fallback")
        self.assertIn("本次未生成可靠答案", answer)
        self.assertNotIn("UNSAFE", answer)
        self.assertNotIn("test-key", json.dumps(answerer.last_diagnostics))
        self.assertEqual(answerer.last_diagnostics["attempts"], 2)

    def test_permission_guard_stops_retry_before_second_model_call(self):
        bad = {"status":"insufficient", "answer":"不足 [1]", "citation_ids":[], "uncertainty":"high"}
        from unittest.mock import Mock
        guard = Mock(side_effect=[None, PermissionError("revoked")])
        with patch.dict(os.environ, self.live_environment, clear=True):
            with patch("urllib.request.urlopen", side_effect=lambda *a,**k:self._response(bad)) as transport:
                with self.assertRaises(PermissionError):
                    AnswerService().answer(self.user, "请回答", self.evidence, before_call=guard)
        self.assertEqual(transport.call_count, 1)

    def test_network_failure_is_not_retried_and_diagnostics_are_safe(self):
        with patch.dict(os.environ, self.live_environment, clear=True):
            answerer = AnswerService()
            with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("secret-test-key")) as transport:
                answer, decision, provider = answerer.answer(self.user, "请回答", self.evidence)
        self.assertEqual(transport.call_count, 1)
        self.assertEqual(decision, "insufficient")
        self.assertIn("模型服务暂不可用", answer)
        self.assertEqual(answerer.last_diagnostics["failures"], ["api_unavailable"])
        self.assertNotIn("secret-test-key", json.dumps(answerer.last_diagnostics))

    def test_diagnostics_are_isolated_between_concurrent_requests(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        barrier=Barrier(2)
        with patch.dict(os.environ, self.live_environment, clear=True):
            answerer=AnswerService()
            def respond(user, question, evidence):
                barrier.wait(timeout=5)
                if question=="failure":
                    raise urllib.error.URLError("offline")
                return "Approved [1]", "answered"
            def run(question):
                result=answerer.answer(self.user,question,self.evidence)
                return result[2],answerer.last_diagnostics
            with patch.object(answerer,"_openai_compatible",side_effect=respond):
                with ThreadPoolExecutor(max_workers=2) as pool:
                    failed,passed=list(pool.map(run,["failure","success"]))
        self.assertEqual(failed[1]["failures"],["api_unavailable"])
        self.assertEqual(passed[1]["failures"],[])

    def test_missing_api_key_uses_mock_mode(self):
        environment = {
            "LLM_PROVIDER": "openai_compatible",
            "LLM_BASE_URL": "https://tokenhub.tencentmaas.com/v1",
            "LLM_API_KEY": "",
            "LLM_MODEL": "glm-5.3-flash",
        }
        with patch.dict(os.environ, environment, clear=True):
            answer, decision, provider = AnswerService().answer(
                self.user,
                "Is the release approved?",
                self.evidence,
            )

        self.assertEqual(decision, "answered")
        self.assertEqual(provider, "mock")
        self.assertIn("[1]", answer)

    def test_empty_evidence_refuses_without_calling_model(self):
        with patch.dict(os.environ, self.live_environment, clear=True):
            answerer = AnswerService()
            with patch("urllib.request.urlopen") as urlopen:
                answer, decision, provider = answerer.answer(
                    self.user,
                    "What is the secret?",
                    [],
                )

        self.assertEqual(decision, "insufficient")
        self.assertEqual(provider, "deterministic")
        self.assertIn("could not find enough authorised evidence", answer)
        urlopen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
