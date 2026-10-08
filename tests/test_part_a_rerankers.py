import argparse
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from contextledger.evaluation import Question
from scripts.compare_part_a_rerankers import candidate_cache_signature, rank_scores, run, summarize_rows
from scripts.expand_part_a_candidates import faithful_rewrites, parse_rewrites


class RerankerComparisonTests(unittest.TestCase):
    def test_query_rewrites_reject_guessed_thresholds_and_allow_equivalent_terms(self):
        self.assertEqual(faithful_rewrites("What hit rate and max sequence length are required?",
                                         ["hit rate 0.95, length 8192", "Required hit rate and length?"]),
                         ["Required hit rate and length?"])
        self.assertEqual(faithful_rewrites("7B 4-bit vs half precision with single-item batching",
                                         ["7B INT4 vs FP16, batch=1", "7B INT8, batch=8"]),
                         ["7B INT4 vs FP16, batch=1"])
        self.assertEqual(parse_rewrites('["first query"]\n["second query"]'),
                         ["first query", "second query"])

    def test_candidate_cache_rejects_changed_store_questions_and_configuration(self):
        original = candidate_cache_signature("store", ["q1", "q2"], {"nprobe": 768})
        for snapshot, ids, config in [("updated-acl", ["q1", "q2"], {"nprobe": 768}),
                                      ("store", ["q2", "q1"], {"nprobe": 768}),
                                      ("store", ["q1", "q2"], {"nprobe": 128})]:
            self.assertNotEqual(original, candidate_cache_signature(snapshot, ids, config))

    def test_prescreen_loss_is_reported_without_injecting_reference_documents(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            ids = [f"d{i}" for i in range(11)]
            connection = sqlite3.connect(out / "canonical.sqlite")
            connection.execute("CREATE TABLE documents(doc_id,title,text,source,corpus)")
            connection.executemany("INSERT INTO documents VALUES(?,?,?,?,?)",
                                   [(did, f"Title {i}", f"Evidence {i}", "jira", "enterpriserag")
                                    for i, did in enumerate(ids)])
            connection.commit()
            connection.close()
            questions = [Question("q1", "enterpriserag", "first question", (ids[-1],), "basic", "alice"),
                         Question("q2", "enterpriserag", "second question", (ids[0],), "basic", "alice")]
            previous = {"store_sha256": "snapshot", "datasets": {}, "configuration": {},
                        "rows": [{"question_id": q.question_id, "split": split, "document_recall10": .5}
                                 for q, split in zip(questions, ["development", "validation"])]}
            (out / "retrieval_tuning.json").write_text(json.dumps(previous))
            (out / "evaluation.json").write_text(json.dumps({"resources": {"store_sha256": "snapshot"}}))
            calls = []

            class FakeReranker:
                def __init__(self, name, *args):
                    self.name = name

                def predict(self, query, texts):
                    calls.append((self.name, query, list(texts)))
                    return list(range(len(texts), 0, -1))

                def close(self):
                    pass

            args = argparse.Namespace(out=out, cache=out / "cache", candidates=None, report=None,
                device="cpu", limit=0, models=["qwen"], rerank_limit=11, max_tokens=768,
                batch_size=1, preselect_limit=10)
            with patch("scripts.compare_part_a_rerankers.load_questions", return_value=(questions, {})), \
                 patch("scripts.compare_part_a_rerankers.resources", return_value={"store_sha256": "snapshot"}), \
                 patch("scripts.compare_part_a_rerankers.collect_candidates", return_value=(
                     {q.question_id: {"rrf": ids} for q in questions}, 1)), \
                 patch("scripts.compare_part_a_rerankers.Reranker", FakeReranker):
                report = run(args)
            summary = report["results"]["qwen"]["summary"]["all"]
            self.assertEqual(summary["retrieval_pool_oracle_recall"], 1)
            self.assertEqual(summary["candidate_oracle_recall"], .5)
            self.assertEqual(summary["document_recall10"], .5)
            self.assertFalse(report["target_met"])
            self.assertFalse(report["applied_to_serving"])
            self.assertTrue(report["complete"])
            self.assertEqual([len(texts) for name, _, texts in calls if name == "qwen"], [10, 10])
            self.assertTrue(all("d10" not in query for _, query, _ in calls))

    def test_rewrite_parse_errors_and_invented_document_ids_are_rejected(self):
        for value in ['[]', '["one"]', '["a", 4]', '["", "b"]',
                      '["dsid_123abc", "query"]', 'no JSON']:
            with self.assertRaises(ValueError):
                parse_rewrites(value)
        self.assertEqual(parse_rewrites('```json\n["FP16 throughput", "4-bit batch=1"]\n```'),
                         ["FP16 throughput", "4-bit batch=1"])

    def test_invalid_model_outputs_cannot_be_scored(self):
        for ids, scores in [(["a", "b"], [1]), (["a", "a"], [1, 2]),
                            (["a"], [float("nan")]), (["a"], [float("inf")])]:
            with self.assertRaises(ValueError):
                rank_scores(ids, scores)

    def test_raw_logits_keep_order_before_sigmoid_saturation(self):
        self.assertEqual(rank_scores(["weak", "strong", "tie"], [20, 24, 24]),
                         ["strong", "tie", "weak"])

    def test_aggregation_reports_partial_evidence_and_candidate_loss(self):
        rows = [{"split": "development", "question_type": "completeness",
                 "document_recall10": .5, "all_evidence_hit10": 0,
                 "candidate_oracle_recall": .75, "rerank_ms": 100},
                {"split": "validation", "question_type": "basic",
                 "document_recall10": 1, "all_evidence_hit10": 1,
                 "candidate_oracle_recall": 1, "rerank_ms": 300}]
        report = summarize_rows(rows)
        self.assertEqual(report["all"]["document_recall10"], .75)
        self.assertEqual(report["all"]["all_evidence_hit10"], .5)
        self.assertEqual(report["all"]["candidate_oracle_recall"], .875)
        self.assertEqual(report["development"]["questions"], 1)
        self.assertEqual(report["type:completeness"]["document_recall10"], .5)


if __name__ == "__main__":
    unittest.main()
