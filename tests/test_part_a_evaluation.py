import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from contextledger.eval_scenarios import _fixture, evaluate_scenarios
from contextledger.evaluation import Question, document_scores, evaluate_retrieval, percentile, run_evaluation


class PartAEvaluationTests(unittest.TestCase):
    def test_document_recall_deduplicates_chunks_and_keeps_full_denominator(self):
        scores = document_scores(("a", "b", "b"), ["a", "a", "unlabelled"], 2)
        self.assertEqual(scores["recall"], .5)
        self.assertEqual(scores["all_evidence"], 0)
        self.assertEqual(scores["reciprocal_rank"], 1)
        self.assertNotIn("precision", scores)

    def test_missing_reference_does_not_become_zero_or_perfect_score(self):
        self.assertIsNone(document_scores((), ["a"], 10))
        self.assertEqual(document_scores(("a",), [], 10)["recall"], 0)

    def test_percentiles_include_empty_and_single_samples(self):
        self.assertIsNone(percentile([], .95))
        self.assertEqual(percentile([9], .99), 9)
        self.assertAlmostEqual(percentile([0, 10], .95), 9.5)

    def fixture_connection(self, directory):
        _fixture(Path(directory))
        connection = sqlite3.connect(Path(directory) / "canonical.sqlite")
        connection.row_factory = sqlite3.Row
        self.addCleanup(connection.close)
        return connection

    def test_missing_evidence_is_reported_and_never_removed_from_gold(self):
        with tempfile.TemporaryDirectory() as directory:
            connection = self.fixture_connection(directory)
            questions = [
                Question("covered", "eval_alpha", "jira private", ("jira-private",), "basic", "eval_alpha:alice", 60),
                Question("partial", "eval_alpha", "jira private", ("jira-private", "not-imported"), "basic", "eval_alpha:alice", 60),
                Question("no-answer", "eval_alpha", "unknown", (), "unanswerable", "eval_alpha:alice", 60),
            ]
            report = evaluate_retrieval(connection, questions, modes=("keyword",), cutoffs=(20,), repeats=1, seed=7)
            summary = report["summary"]["eval_alpha"]["keyword"]
            self.assertEqual(summary["scored_fully_covered_queries"], 1)
            self.assertEqual(summary["top_k"]["20"]["document_recall"], 1)
            self.assertEqual(summary["top_k"]["20"]["all_reference_questions_recall"], .75)
            partial = next(row for row in report["queries"] if row["question_id"] == "partial")
            self.assertEqual(partial["missing_evidence"], ["not-imported"])
            self.assertEqual(partial["scores"]["20"]["recall"], .5)
            connection.close()

    def test_question_sampling_is_repeatable(self):
        with tempfile.TemporaryDirectory() as directory:
            connection = self.fixture_connection(directory)
            questions = [Question(str(i), "eval_alpha", "budget", ("jira-private",), "basic", "eval_alpha:alice", 60) for i in range(20)]
            params = dict(modes=("keyword",), cutoffs=(10,), repeats=1, seed=42, limit=5)
            first = evaluate_retrieval(connection, questions, **params)
            second = evaluate_retrieval(connection, questions, **params)
            self.assertEqual([row["question_id"] for row in first["queries"]], [row["question_id"] for row in second["queries"]])
            self.assertEqual(len(first["queries"]), 5)
            connection.close()

    def test_scenarios_cover_positive_controls_revocation_time_and_audit(self):
        report = evaluate_scenarios(modes=("keyword",))
        self.assertEqual(report["passed"], report["total"])
        self.assertGreater(report["positive_cases"], 0)
        self.assertGreater(report["negative_cases"], 0)
        self.assertEqual(report["unauthorised_target_leak_rate"], 0)
        self.assertEqual(report["mvp_audit"]["passed"], report["mvp_audit"]["total"])
        names = {case["case"] for case in report["cases"]}
        self.assertTrue({"revoked_next_request", "permission_restored", "future_excluded", "cross_corpus_identity"} <= names)
        self.assertIn("not_met", report["gates"]["pre_retrieval_candidate_isolation"])

    def test_scenario_oracle_detects_a_broken_authorisation_check(self):
        with patch("contextledger.search.can_see", return_value=True):
            report = evaluate_scenarios(modes=("keyword",))
        self.assertGreater(report["unauthorised_target_leak_cases"], 0)
        self.assertLess(report["passed"], report["total"])
        self.assertEqual(report["gates"]["returned_evidence_and_open_access"], "failed")

    def test_keyword_run_is_read_only_and_marks_unmeasured_metrics(self):
        with tempfile.TemporaryDirectory() as directory:
            out_dir = Path(directory)
            _fixture(out_dir)
            database = out_dir / "canonical.sqlite"
            before = hashlib.sha256(database.read_bytes()).hexdigest()
            questions = [Question("one", "eval_alpha", "jira private", ("jira-private",), "basic", "eval_alpha:alice", 60)]
            with patch("contextledger.evaluation.load_questions", return_value=(questions, {})):
                report = run_evaluation(out_dir, modes=("keyword",), ann_queries=0)
            self.assertEqual(before, hashlib.sha256(database.read_bytes()).hexdigest())
            self.assertEqual(report["ann"]["status"], "not_measured")
            self.assertIn("answer_quality_citations_abstention_tokens_ttft_cost", report["not_measured"])
            self.assertEqual(json.loads((out_dir / "evaluation.json").read_text())["schema_version"], 1)


if __name__ == "__main__":
    unittest.main()
