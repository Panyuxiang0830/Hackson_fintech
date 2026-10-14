import unittest

from scripts.experiment_part_a_ranking import (
    aggregation_query, expand_siblings, fill_aggregation, promote_constraints, rerank,
    window_satisfies, constraint_slots,
)


def doc(title, text):
    return {"title": title, "text": text}


class RankingForkTests(unittest.TestCase):
    def test_scattered_constraints_do_not_count_as_one_condition(self):
        slots = constraint_slots(
            "A100 microbenchmark of 4-bit weights versus half precision on a 7B model at batch=1")
        self.assertGreaterEqual(len(slots), 4)
        scattered = "A100 is installed.\nThe 7B model is loaded.\nTry 4-bit later.\nCompare with fp16.\nUse batch=1 tomorrow."
        together = "NF4 PTQ on 7B gives 1.8x versus fp16 at batch=1 on A100."
        self.assertFalse(window_satisfies(scattered, slots))
        self.assertTrue(window_satisfies(together, slots))

    def test_unique_condition_window_enters_top10_without_reading_gold(self):
        query = "A100 4-bit versus half precision on a 7B model at batch=1"
        docs = {f"d{i}": doc(f"note {i}", "unrelated benchmark") for i in range(10)}
        docs["gold"] = doc("microbench", "NF4 on 7B versus fp16 at batch=1 on A100, about 1.8x.")
        ranked = [f"d{i}" for i in range(10)]
        pool = ["gold"] + ranked
        promoted, hits = promote_constraints(query, ranked, pool, docs)
        self.assertEqual(hits, 1)
        self.assertEqual(promoted[0], "gold")
        self.assertNotIn("reference", promote_constraints.__code__.co_varnames)

    def test_too_many_condition_matches_leave_the_ranking_unchanged(self):
        query = "A100 4-bit versus half precision on a 7B model at batch=1"
        line = "NF4 on 7B versus fp16 at batch=1 on A100."
        docs = {f"d{i}": doc("bench", line) for i in range(12)}
        ranked = [f"d{i}" for i in range(12)]
        promoted, hits = promote_constraints(query, ranked, ranked, docs)
        self.assertGreater(hits, 10)
        self.assertEqual(promoted, ranked[:10])

    def test_single_fact_questions_do_not_lose_their_top_hit_to_siblings(self):
        docs = {
            "keep": doc("SSE truncation after edge handoff", "temporary mitigation for us-east"),
            "sibling": doc("A long sibling procedure document", "mentions SSE truncation after edge handoff in passing"),
        }
        ranked = ["keep"] + [f"x{i}" for i in range(9)]
        docs.update({f"x{i}": doc(f"other {i}", "nothing") for i in range(9)})
        expanded, links = expand_siblings("What mitigation fixed the truncated SSE stream?", ranked,
                                          ["sibling"] + ranked, docs)
        self.assertEqual(links, 0)
        self.assertEqual(expanded[0], "keep")

    def test_cited_sibling_fills_a_coverage_slot_and_keeps_the_seed(self):
        docs = {
            "seed": doc("Production Change Management Standard",
                        "Follow Production secret rotation runbook and the rollback checklist."),
            "child": doc("Production secret rotation runbook", "Rotate production credentials."),
        }
        ranked = ["seed"] + [f"t{i}" for i in range(9)]
        for i in range(9):
            docs[f"t{i}"] = doc(f"tail {i}", "generic notes")
        expanded, links = expand_siblings(
            "What is the complete end-to-end process for rotating production secrets?",
            ranked, ["child"] + ranked, docs, seeds=1, slots=1)
        self.assertEqual(links, 1)
        self.assertEqual(expanded[0], "seed")
        self.assertIn("child", expanded)
        self.assertNotIn("t8", expanded)

    def test_across_all_fill_requires_the_class_and_the_predicate(self):
        query = "Across all incident postmortems, which Redwood team was assigned the most follow-up action items?"
        self.assertEqual(aggregation_query(query), ("postmortem", "follow-up action items"))
        docs = {
            "yes": doc("Postmortem: latency regression", "Follow-up action items\nOwner team: Applied ML."),
            "theme": doc("Postmortem: metrics pipeline", "No owner section here."),
            "mention": doc("Ops cheatsheet", "Follow-up action items for Redwood are listed in chat."),
        }
        ranked = ["mention", "theme", "yes"]
        filled, hits = fill_aggregation(query, ranked, ["yes", "theme", "mention"], docs)
        self.assertEqual(hits, 1)
        self.assertEqual(filled, ranked)
        extra = {f"p{i}": doc(f"Postmortem: case {i}", "Follow-up action items\nOwner team: SRE.") for i in range(3)}
        docs.update(extra)
        ranked = ["p0", "mention", "theme", "yes"]
        pool = ["yes", *extra, "theme", "mention"]
        filled, hits = fill_aggregation(query, ranked, pool, docs)
        self.assertEqual(hits, 4)
        self.assertEqual(filled[0], "p0")
        self.assertIn("yes", filled[:4])
        self.assertNotIn("mention", filled[:4])

    def test_applied_ranking_does_not_replace_the_tuned_list_with_class_fill(self):
        query = "Across all incident postmortems, which team was assigned the most follow-up action items?"
        docs = {f"p{i}": doc(f"Postmortem: case {i}", "Follow-up action items assigned to a team.") for i in range(4)}
        docs["other"] = doc("Weekly notes", "unrelated")
        ranked = ["other"] + [f"p{i}" for i in range(4)]
        result = rerank(query, ranked, ranked, docs)
        self.assertEqual(result["aggregation_hits"], 0)
        self.assertEqual(result["document_ids"][0], "other")


if __name__ == "__main__":
    unittest.main()
