import io
import json
import os
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

        self.assertEqual(decision, "answered")
        self.assertEqual(provider, "mock_fallback")
        self.assertIn("unsafe output", answer)
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

        self.assertEqual(decision, "answered")
        self.assertEqual(provider, "mock_fallback")
        self.assertIn("deterministic evidence synthesis", answer)

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
