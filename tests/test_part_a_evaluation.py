import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from contextledger.benchmark_quality import (
    build_prompt, compose_extractive_answer, measure_ingest, score_answer,
)
from contextledger.__main__ import main
from contextledger.eval_scenarios import _fixture, evaluate_scenarios
from contextledger.evaluation import Question, document_scores, evaluate_retrieval, percentile, run_evaluation
from contextledger.search import search


class PartAEvaluationTests(unittest.TestCase):
    def test_document_recall_deduplicates_chunks_and_keeps_full_denominator(self):
        scores = document_scores(("a", "b", "b"), ["a", "a", "unlabelled"], 2)
        self.assertEqual(scores["recall"], .5)
        self.assertEqual(scores["all_evidence"], 0)
        self.assertEqual(scores["reciprocal_rank"], 1)
        self.assertEqual(scores["reference_precision"], .5)
        self.assertNotIn("precision", scores)

    def test_missing_reference_does_not_become_zero_or_perfect_score(self):
        self.assertIsNone(document_scores((), ["a"], 10))
        self.assertEqual(document_scores(("a",), [], 10)["recall"], 0)
        self.assertIsNone(document_scores(("a",), [], 10)["reference_precision"])

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
            covered = next(row for row in report["queries"] if row["question_id"] == "covered")
            self.assertNotIn("precision", covered["scores"]["20"])
            self.assertGreater(covered["scores"]["20"]["reference_precision"], 0)
            self.assertEqual(covered["extractive_diagnostics"]["nonverbatim_sentence_rate"], 0)
            self.assertIn("acl_filter", covered["stage_measurements"][0])
            unanswered = next(row for row in report["queries"] if row["question_id"] == "no-answer")
            self.assertTrue(unanswered["extractive_diagnostics"]["abstained"])
            self.assertIsNone(unanswered["extractive_diagnostics"]["abstention_matches_label"])
            self.assertEqual(summary["extractive_diagnostics"]["future_hit_rate"], 0)
            self.assertIsNone(report["cost"]["llm_usd"])
            self.assertEqual(report["cost"]["llm_api_calls"], 0)
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

    def test_scoring_cutoffs_do_not_change_retrieval_depth(self):
        with tempfile.TemporaryDirectory() as directory:
            connection = self.fixture_connection(directory)
            questions = [Question("one", "eval_alpha", "budget", ("jira-private",), "basic", "eval_alpha:alice", 60)]
            with patch("contextledger.evaluation.search", wraps=search) as lookup:
                first = evaluate_retrieval(connection, questions, modes=("keyword",), cutoffs=(10,), repeats=1, seed=42)
                second = evaluate_retrieval(connection, questions, modes=("keyword",), cutoffs=(1, 5, 10, 20), repeats=1, seed=42)
            self.assertEqual([call.kwargs["limit"] for call in lookup.call_args_list], [20, 20])
            self.assertEqual(first["queries"][0]["document_ids"], second["queries"][0]["document_ids"])
            self.assertEqual(first["queries"][0]["scores"]["10"], second["queries"][0]["scores"]["10"])
            self.assertEqual(first["sampling"]["selected_questions_sha256"], second["sampling"]["selected_questions_sha256"])

    def test_stage_percentiles_include_all_repeats(self):
        with tempfile.TemporaryDirectory() as directory:
            connection = self.fixture_connection(directory)
            questions = [Question("one", "eval_alpha", "budget", ("jira-private",), "basic", "eval_alpha:alice", 60)]
            responses = [{"hits": [], "stages_ms": {"retrieve": value}} for value in (1.0, 9.0)]
            with patch("contextledger.evaluation.search", side_effect=responses):
                report = evaluate_retrieval(connection, questions, modes=("keyword",), cutoffs=(10,), repeats=2, seed=42)
            stages = report["summary"]["eval_alpha"]["keyword"]["stages_ms"]["retrieve"]
            self.assertEqual(stages["measurements"], 2)
            self.assertEqual(stages["p50"], 5)

    def test_large_reference_sets_keep_their_denominator_and_recall_ceiling(self):
        with tempfile.TemporaryDirectory() as directory:
            connection = self.fixture_connection(directory)
            gold = tuple(f"{source}-{kind}" for source in ("slack", "jira", "confluence", "google_drive")
                         for kind in ("public", "private", "future"))
            questions = [Question("many", "eval_alpha", "budget release", gold, "basic", "eval_alpha:alice", 60)]
            report = evaluate_retrieval(connection, questions, modes=("keyword",), cutoffs=(10,), repeats=1, seed=42)
            scores = report["summary"]["eval_alpha"]["keyword"]["top_k"]["10"]
            self.assertAlmostEqual(scores["recall_ceiling"], 10 / 12)
            self.assertAlmostEqual(scores["document_recall"], 10 / 12)
            self.assertEqual(scores["questions_with_more_references_than_k"], 1)
            self.assertEqual(scores["all_evidence_rate"], 0)

    def test_imported_but_unauthorised_gold_is_not_silently_removed(self):
        with tempfile.TemporaryDirectory() as directory:
            connection = self.fixture_connection(directory)
            questions = [Question("denied", "eval_alpha", "jira private", ("jira-private",), "basic", "eval_alpha:bob", 60)]
            report = evaluate_retrieval(connection, questions, modes=("keyword",), cutoffs=(10,), repeats=1, seed=42)
            row = report["queries"][0]
            self.assertEqual(row["coverage"], "fully_covered")
            self.assertEqual(row["reference_document_ids"], ["jira-private"])
            self.assertEqual(row["scores"]["10"]["recall"], 0)

    def test_scenarios_cover_positive_controls_revocation_time_and_audit(self):
        report = evaluate_scenarios(modes=("keyword",))
        self.assertEqual(report["passed"], report["total"])
        self.assertGreater(report["positive_cases"], 0)
        self.assertGreater(report["negative_cases"], 0)
        self.assertEqual(report["unauthorised_target_leak_rate"], 0)
        self.assertEqual(report["mvp_audit"]["passed"], report["mvp_audit"]["total"])
        names = {case["case"] for case in report["cases"]}
        self.assertTrue({"revoked_next_request", "permission_restored", "future_excluded", "cross_corpus_identity",
                         "as_of_open_visible", "as_of_closed_hidden", "as_of_closed_visible"} <= names)
        self.assertTrue(all(case["passed"] for case in report["cases"] if case["case"].startswith("as_of_")))
        self.assertIn("not_met", report["gates"]["pre_retrieval_candidate_isolation"])
        self.assertEqual(report["gates"]["extractive_prompt_and_answer_leak"], "passed")
        self.assertEqual(report["extensions"]["prompt_leak_cases"], 0)
        self.assertEqual(report["extensions"]["answer_leak_cases"], 0)
        self.assertEqual(report["extensions"]["identity_switch_leak_cases"], 0)
        self.assertTrue(report["extensions"]["revocation_next_request_passed"])
        observed = report["extensions"]["authority_and_stale"][0]
        self.assertEqual(observed["top_is_preferred"], observed["top_source"] == observed["preferred_source"])
        if observed["current_ahead_of_superseded"]:
            self.assertEqual(report["gates"]["stale_evidence"], "passed")
        else:
            self.assertTrue(report["gates"]["stale_evidence"].startswith("not_met"))
        if observed["top_is_preferred"]:
            self.assertEqual(report["gates"]["authority_source"], "passed")
        else:
            self.assertTrue(report["gates"]["authority_source"].startswith("not_met"))

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
            self.assertIn("generated_answer_quality", report["not_measured"])
            self.assertEqual(report["evaluation_scope"]["kind"], "regression")
            self.assertEqual(report["final_assessment"]["status"], "not_measured")
            self.assertFalse(report["evaluation_scope"]["serving_pipeline_verified"])
            self.assertIn("llm_judge_api_usd_and_ttft", report["not_measured"])
            self.assertIn("full_corpus_ingest_and_embedding_throughput", report["not_measured"])
            self.assertIsNone(report["retrieval"]["extractive_method"]["llm_usd"])
            self.assertEqual(report["retrieval"]["extractive_method"]["llm_api_calls"], 0)
            self.assertGreater(report["ingest_fixture"]["docs_per_second"], 0)
            self.assertEqual(report["ingest_fixture"]["embedding"], "not_measured")
            self.assertFalse(report["ingest_fixture"]["live_store"])
            self.assertEqual(report["scenarios"]["gates"]["extractive_prompt_and_answer_leak"], "passed")
            self.assertIn("not_met", report["scenarios"]["gates"]["pre_retrieval_candidate_isolation"])
            self.assertEqual(json.loads((out_dir / "evaluation.json").read_text())["schema_version"], 2)
            self.assertEqual(report["scenarios"]["gates"]["deployed_prompt_and_answer_leak"], "not_measured")

    def test_custom_report_preserves_saved_baseline_and_rejects_vector_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            out_dir = Path(directory)
            _fixture(out_dir)
            baseline = out_dir / "evaluation.json"
            baseline.write_text('{"baseline": true}\n')
            custom = out_dir / "reports" / "smoke.json"
            questions = [Question("one", "eval_alpha", "budget", ("jira-private",), "basic", "eval_alpha:alice", 60)]
            with patch("contextledger.evaluation.load_questions", return_value=(questions, {})):
                run_evaluation(out_dir, modes=("keyword",), ann_queries=0, report_path=custom)
            self.assertTrue(json.loads(baseline.read_text())["baseline"])
            self.assertEqual(json.loads(custom.read_text())["schema_version"], 2)
            with self.assertRaises(ValueError):
                run_evaluation(out_dir, report_path=out_dir / "vectors" / "status.json")
            with self.assertRaises(ValueError):
                run_evaluation(out_dir, cutoffs=(20,), retrieval_depth=10)

    def test_cli_forwards_protocol_options_and_fails_a_prompt_fixture_leak(self):
        report = {"scenarios": {"passed": 1, "total": 1, "mvp_audit": {"passed": 1, "total": 1},
                                "gates": {"extractive_prompt_and_answer_leak": "failed"}}}
        with patch("contextledger.evaluation.run_evaluation", return_value=report) as run:
            self.assertEqual(main(["eval", "--retrieval-depth", "30", "--report", "reports/test.json"]), 1)
        self.assertEqual(run.call_args.kwargs["retrieval_depth"], 30)
        self.assertEqual(run.call_args.kwargs["report_path"], Path("reports/test.json"))

    def test_extractive_answers_cite_only_supplied_hits_and_cover_numbers(self):
        hits = [
            {"doc_id": "kept", "title": "Kept", "source": "confluence", "day": 1,
             "snippet": "The upload limit is 10 MiB for each file."},
            {"doc_id": "other", "title": "Other", "source": "slack", "day": 2,
             "snippet": "Lunch is at noon."},
        ]
        composed = compose_extractive_answer("upload limit", hits)
        self.assertEqual(composed["citations"], ["kept"])
        self.assertNotIn("Lunch", composed["answer"])
        self.assertNotIn("eval_alpha_jira-private", build_prompt("upload limit", hits))
        empty = compose_extractive_answer("upload limit", [])
        self.assertTrue(empty["abstained"])
        self.assertEqual(empty["citations"], [])
        scored = score_answer(gold_doc_ids=("kept",), citations=composed["citations"], answer=composed["answer"],
                              evidence=composed["evidence"], gold_answer="The upload limit is 10 MiB.",
                              answer_facts=("The upload limit is 10 MiB.", "The upload limit is 50 MiB."))
        self.assertEqual(scored["lexical_fact_overlap"], .5)
        self.assertEqual(scored["lexical_gold_answer_overlap"], 1)
        self.assertEqual(scored["nonverbatim_sentence_rate"], 0)
        self.assertEqual(scored["citation_recall"], 1)
        self.assertEqual(scored["citation_reference_precision"], 1)
        self.assertNotIn("precision", scored)
        abstained = score_answer(gold_doc_ids=(), citations=(), answer="", evidence="", is_answerable=False)
        self.assertTrue(abstained["abstention_matches_label"])
        self.assertIsNone(abstained["nonverbatim_sentence_rate"])

    def test_empty_gold_does_not_label_answerability_or_make_short_facts_perfect(self):
        unknown = score_answer(gold_doc_ids=(), citations=[], answer="", evidence="", answer_facts=("US",))
        self.assertIsNone(unknown["abstention_matches_label"])
        self.assertIsNone(unknown["lexical_fact_overlap"])
        self.assertEqual(unknown["scorable_answer_facts"], 0)
        answerable = score_answer(gold_doc_ids=(), citations=[], answer="", evidence="", is_answerable=True)
        self.assertFalse(answerable["abstention_matches_label"])
        self.assertNotIn("hallucination_rate", unknown)
        self.assertNotIn("answer_correctness", unknown)

    def test_extraction_uses_the_same_snippet_as_the_prompt(self):
        hits = [{"doc_id": "one", "snippet": "The upload limit is 10 MiB.",
                 "text": "The upload limit is 99 MiB."}]
        answer = compose_extractive_answer("upload limit", hits)["answer"]
        self.assertIn("10 MiB", answer)
        self.assertNotIn("99 MiB", answer)
        self.assertIn(answer, build_prompt("upload limit", hits))

    def test_profile_timings_stay_out_of_the_default_search_response(self):
        with tempfile.TemporaryDirectory() as directory:
            connection = self.fixture_connection(directory)
            query = "jira private budget release evidence"
            quiet = search(connection, corpus="eval_alpha", query=query, principal_id="eval_alpha:alice",
                           as_of_day=60, mode="keyword", limit=5)
            profiled = search(connection, corpus="eval_alpha", query=query, principal_id="eval_alpha:alice",
                              as_of_day=60, mode="keyword", limit=5, profile=True)
            self.assertNotIn("stages_ms", quiet)
            self.assertEqual(set(profiled["stages_ms"]), {"identity", "retrieve", "acl_filter", "materialize"})
            self.assertEqual([hit["doc_id"] for hit in quiet["hits"]], [hit["doc_id"] for hit in profiled["hits"]])
            connection.close()

    def test_fixture_ingest_does_not_load_an_embedding_model(self):
        report = measure_ingest()
        self.assertGreater(report["docs_per_second"], 0)
        self.assertGreaterEqual(report["chunks"], report["documents"])
        self.assertGreater(report["index_bytes"], 0)
        self.assertEqual(report["embedding"], "not_measured")
        self.assertIn("paragraph-400", report["chunking"])


if __name__ == "__main__":
    unittest.main()
