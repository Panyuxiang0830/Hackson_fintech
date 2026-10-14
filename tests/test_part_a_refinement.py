import math
from pathlib import Path
import sqlite3
import tempfile
import unittest

from contextledger.eval_scenarios import _fixture
from contextledger.evaluation import Question
from scripts.refine_part_a_retrieval import meets_target, replace_tail, select_setting, shortlist
from scripts.tune_part_a_retrieval import visible_rankings


class RefinementTests(unittest.TestCase):
    def test_new_route_adds_unique_documents_without_displacing_the_old_pool(self):
        base = [f"d{i}" for i in range(10)]
        old = base + [f"old{i}" for i in range(100)]
        ids = shortlist(base, old, ["d0", "v0", "v0", "v1", "v2"], 2)
        self.assertEqual(ids[:80], old[:80])
        self.assertEqual(ids[80:], ["v0", "v1"])
        self.assertEqual(shortlist(base, old, ["v0"], 0), old[:80])

    def test_replacements_are_bounded_and_require_the_score_margin(self):
        base = [f"d{i}" for i in range(10)]
        ids = base + ["n0", "n1", "n2"]
        scores = {did: float(i) for i, did in enumerate(base)}
        scores.update(n0=11, n1=10.5, n2=2)
        changed = replace_tail(base, ids, scores, 2, 1)
        self.assertEqual(len(changed), 10)
        self.assertEqual(set(changed) - set(base), {"n0", "n1"})
        self.assertEqual(set(base) - set(changed), {"d0", "d1"})
        self.assertEqual(replace_tail(base, ids, scores, 2, 12), base)
        self.assertEqual(replace_tail(base, ids, scores, 0, 0), base)

    def test_revoked_base_documents_can_be_replaced_without_duplicates(self):
        ids = ["a", "b", "c"]
        self.assertEqual(replace_tail(["a"], ids, {"a": 0, "b": 1, "c": 2}, 1, 0), ["c", "b", "a"])

    def test_invalid_model_outputs_are_rejected(self):
        for scores in ({"a": math.nan}, {"a": math.inf}, {}):
            with self.assertRaises(ValueError):
                replace_tail(["a"], ["a"], scores, 1, 0)
        with self.assertRaises(ValueError):
            replace_tail(["a"], ["a", "a"], {"a": 1}, 1, 0)
        with self.assertRaises(ValueError):
            replace_tail(["x"], ["a"], {"a": 1}, 1, 0)

    def test_development_selection_keeps_the_conservative_tie(self):
        options = [((0, 0), .9), ((1, 0), .95), ((2, 0), .9666666666666666),
                   ((2, 1), .9666666666666667), ((3, 0), .9666666666666666)]
        self.assertEqual(select_setting(options), (2, 0))
        self.assertNotIn("validation", select_setting.__code__.co_varnames)

    def test_target_requires_complete_validation_and_development(self):
        rows = [{"question_id": "d", "split": "development", "document_recall10": 1},
                {"question_id": "v", "split": "validation", "document_recall10": .89}]
        self.assertFalse(meets_target(rows, 2, .9))
        rows[1]["document_recall10"] = .9
        self.assertTrue(meets_target(rows, 2, .9))
        self.assertFalse(meets_target(rows[:1], 2, .9))
        self.assertFalse(meets_target(rows[:1], 1, .9))
        self.assertFalse(meets_target([rows[0], rows[0]], 2, .9))
        rows[1]["split"] = "unknown"
        self.assertFalse(meets_target(rows, 2, .9))

    def test_all_routes_drop_denied_future_and_cross_corpus_documents_before_scoring(self):
        with tempfile.TemporaryDirectory() as directory:
            _fixture(Path(directory))
            connection = sqlite3.connect(Path(directory) / "canonical.sqlite")
            connection.row_factory = sqlite3.Row
            try:
                q = Question("q", "eval_alpha", "private", (), "basic", "eval_alpha:bob", 49)
                routes = {key: ["jira-private", "jira-public", "jira-future", "foreign"]
                          for key in ("base", "rrf", "vector")}
                allowed = visible_rankings(connection, q, routes)
                ids = shortlist(allowed["base"], allowed["rrf"], allowed["vector"], 40)
                self.assertEqual(ids, ["jira-public"])
            finally:
                connection.close()


if __name__ == "__main__":
    unittest.main()
