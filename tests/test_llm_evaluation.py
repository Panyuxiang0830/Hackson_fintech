import io
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import Mock, patch

from scripts.evaluate_llm_review import evaluate, main

ROOT = Path(__file__).resolve().parents[1]


class LLMReviewEvaluationTests(unittest.TestCase):
    def test_cli_can_use_current_glm_without_a_separate_reviewer_model(self):
        output = io.StringIO()
        with patch.dict(os.environ, {"LLM_MODEL":"glm-5.3-flash", "LLM_API_KEY":"fixture-key",
                                    "LLM_BASE_URL":"https://example.test/v1"}, clear=True), \
                patch("sys.argv", ["evaluate_llm_review.py", "--run-models"]), \
                patch("dotenv.load_dotenv"), patch("sys.stdout", output), \
                patch("scripts.evaluate_llm_review.evaluate", return_value={"quality":"fixture only"}) as evaluate_mock:
            main()
        reviewer = evaluate_mock.call_args.args[1]
        self.assertEqual(reviewer.stage.model, "glm-5.3-flash")
        self.assertEqual(evaluate_mock.call_args.args[2], "glm-5.3-flash")
        self.assertNotIn("fixture-key", output.getvalue())

    def test_fixed_synthetic_labels_and_dry_run_do_not_call_api(self):
        cases = json.loads((ROOT / "tests/fixtures/llm_review_cases.json").read_text())
        self.assertEqual(len(cases), 9)
        self.assertEqual(len({c["id"] for c in cases}), len(cases))
        self.assertTrue(all(c["expected"] in {"supported", "unsupported"} for c in cases))
        result = subprocess.run([sys.executable, str(ROOT / "scripts/evaluate_llm_review.py")],
                                capture_output=True, text=True, check=True)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["api_calls"], 0)
        self.assertEqual(payload["quality"], "not measured")

    def test_quality_denominators_exclude_not_run_failed_and_deterministic_checks(self):
        cases = [{"id":str(i), "question":"q", "draft":"d", "evidence":[], "expected":truth}
                 for i,truth in enumerate(["supported", "unsupported", "unsupported", "supported", "unsupported"])]
        reviewer = Mock()
        reviewer.review.side_effect = [
            {"status":"supported", "attempts":1, "usage":{"total_tokens":10}},
            {"status":"supported", "attempts":1, "usage":{"total_tokens":20}},
            {"status":"api_unavailable", "attempts":1},
            {"status":"not_configured", "attempts":0},
            {"status":"unsupported", "attempts":0}]
        report = evaluate(cases, reviewer, "writer")
        self.assertEqual(report["measured_verdicts"], 2)
        self.assertEqual(report["false_accept_count"], 1)
        self.assertEqual(report["negative_denominator"], 1)
        self.assertEqual(report["positive_denominator"], 1)
        self.assertEqual(report["deterministic_rejections"], 1)
        self.assertEqual(report["api_calls"], 3)
        self.assertEqual(report["total_tokens_reported"], 30)


if __name__ == "__main__":
    unittest.main()
