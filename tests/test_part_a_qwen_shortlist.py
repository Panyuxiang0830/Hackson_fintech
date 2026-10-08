import unittest

from scripts.experiment_part_a_qwen_shortlist import (
    apply_setting, build_shortlist, choose_setting, order_by_score,
)


class QwenShortlistTests(unittest.TestCase):
    def test_shortlist_keeps_fork_then_new_rrf_documents(self):
        ranked = [f"d{i}" for i in range(10)]
        rrf = ["d0", "new", "d1"] + [f"r{i}" for i in range(40)]
        short = build_shortlist(ranked, rrf, 40)
        self.assertEqual(short[:10], ranked)
        self.assertEqual(short[10], "new")
        self.assertNotIn("r38", short)
        self.assertNotIn("gold", build_shortlist.__code__.co_varnames)

    def test_score_order_breaks_ties_by_position(self):
        self.assertEqual(order_by_score(["a", "b", "c"], [1.0, 1.0, 0.5]), ["a", "b", "c"])

    def test_tail_swap_replaces_the_weaker_insider_only_past_the_margin(self):
        fork = [f"d{i}" for i in range(10)]
        rrf = fork + ["outside"]
        scores = {did: 0.1 for did in fork}
        scores["d9"] = 0.0
        scores["outside"] = 0.4
        swapped = apply_setting(
            {"kind": "tail", "k": 40, "margin": 0.0, "slots": 1}, fork, rrf, scores)
        self.assertEqual(swapped[9], "outside")
        self.assertNotIn("d9", swapped)
        held = apply_setting(
            {"kind": "tail", "k": 40, "margin": 1.0, "slots": 1}, fork, rrf, scores)
        self.assertEqual(held, fork)
        self.assertNotIn("gold", apply_setting.__code__.co_varnames)

    def test_development_tie_keeps_the_fork(self):
        self.assertEqual(choose_setting([("fork", 0.90), ("reorder-40", 0.90)]), "fork")
        self.assertEqual(
            choose_setting([("fork", 0.90), ("reorder-40", 0.95), ("reorder-80", 0.95)]),
            "reorder-40")
        self.assertEqual(choose_setting([("fork", 0.90), ("reorder-40", 0.89)]), "fork")
        self.assertEqual(choose_setting([("fork", 0.80), ("reorder-40", 0.89)]), "reorder-40")
        self.assertNotIn("validation", choose_setting.__code__.co_varnames)
