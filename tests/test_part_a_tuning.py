import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from contextledger.eval_scenarios import _fixture
from contextledger.evaluation import Question
from scripts.tune_part_a_retrieval import calibrate_reranking, document_recall, summarize, visible_rankings


class PartATuningTests(unittest.TestCase):
    def test_model_candidates_exclude_denied_future_and_unknown_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            _fixture(Path(directory))
            connection = sqlite3.connect(Path(directory) / "canonical.sqlite")
            connection.row_factory = sqlite3.Row
            try:
                q = Question("q", "eval_alpha", "jira private", (), "basic", "eval_alpha:bob", 49)
                candidates = {"keyword": ["jira-public", "jira-private", "jira-future"]}
                self.assertEqual(visible_rankings(connection, q, candidates), {"keyword": ["jira-public"]})
                unknown = Question("q", "eval_alpha", "private", (), "basic", "missing-user", 60)
                self.assertEqual(visible_rankings(connection, unknown, candidates), {"keyword": []})
            finally:
                connection.close()

    def test_duplicate_results_do_not_inflate_document_recall(self):
        self.assertEqual(document_recall(("a", "b"), ["a", "a"]), .5)

    def test_reranker_calibration_does_not_fit_validation_labels(self):
        docs = {f"bad{i}": {"title": "Memo", "text": "", "source": "jira"} for i in range(10)}
        docs["good"] = {"title": "Postmortem: outage", "text": "", "source": "confluence"}
        prediction = {f"bad{i}": 3.0 for i in range(10)}
        prediction["good"] = 2.0
        questions = [Question("dev", "x", "incident postmortem", ("good",), "basic", "alice", 1),
                     Question("val", "x", "incident postmortem", ("bad9",), "basic", "alice", 1)]
        config, rankings = calibrate_reranking(questions, [prediction, prediction], docs, 1)
        self.assertEqual(config["selected"]["kind_bonus"], 2)
        self.assertEqual(document_recall(questions[0].gold, rankings[0]), 1)
        self.assertEqual(document_recall(questions[1].gold, rankings[1]), 0)

    def test_development_success_cannot_hide_a_failed_validation_target(self):
        baseline = {"resources": {"store_sha256": "fixture"},
                    "retrieval": {"summary": {"enterpriserag": {"hybrid": {"top_k": {"10": {"document_recall": .5}}}}},
                                  "coverage_all_questions": {"enterpriserag": {"fully_covered": 2}}}}
        rows = [{"split": split, "document_recall10": score, "candidate_oracle_recall": 1,
                 "rerank_input_oracle_recall": 1, "rerank_ms": 1}
                for split, score in [("development", 1), ("validation", .9)]]
        report = summarize(rows, baseline, {}, .99, {}, 42, "cpu", 768, 800)
        self.assertFalse(report["target_met"])
        self.assertFalse(report["applied_to_serving"])
        self.assertEqual(report["validation_recall10"], .9)


if __name__ == "__main__":
    unittest.main()
