import contextlib
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest

from contextledger.freshness_eval import main, replay, score_results, score_row
from contextledger.freshness_workload import Workload, digest, example_workload, reference


def workload():
    def revision(doc_id, version, text, actors=("alice",)):
        return {"corpus": "fixture", "doc_id": doc_id, "version": version, "title": doc_id,
                "text": text, "source": "jira", "content_hash": digest(text), "allowed_actors": list(actors)}
    old = revision("a", "v1", "old policy")
    new = revision("a", "v2", "new policy")
    companion = revision("b", "v1", "supporting evidence")
    events = [{"id": "initial-a", "at_ms": 0, "corpus": "fixture", "doc_id": "a", "op": "upsert", "version": "v1", "initial": True},
              {"id": "initial-b", "at_ms": 0, "corpus": "fixture", "doc_id": "b", "op": "upsert", "version": "v1", "initial": True},
              {"id": "change", "at_ms": 100, "corpus": "fixture", "doc_id": "a", "op": "upsert", "version": "v2"},
              {"id": "delete", "at_ms": 200, "corpus": "fixture", "doc_id": "b", "op": "delete"}]
    queries = []
    for identity, at_ms, actor, targets, gold in [
            ("before", 10, "alice", ["a"], [reference(old)]),
            ("after", 100, "alice", ["a"], [reference(new)]),
            ("multi", 150, "alice", ["a", "b"], [reference(new), reference(companion)]),
            ("denied", 150, "outside", ["a"], []),
            ("deleted", 200, "alice", ["b"], [])]:
        queries.append({"id": identity, "at_ms": at_ms, "actor_id": actor, "corpus": "fixture",
                        "query": "current policy", "kind": "chasing", "targets": targets,
                        "gold": gold, "expect_empty": not gold})
    return Workload({"schema_version": 1, "name": "fixture", "actors": [{"id": "alice"}, {"id": "outside"}],
                     "revisions": [old, new, companion], "events": events, "queries": queries, "horizon_ms": 200})


def observation(work, query_id="after", hits=None, status="ok", arm="target", mode="keyword"):
    query = work.query_map[query_id]
    return {"arm": arm, "mode": mode, "query_id": query_id, "at_ms": query["at_ms"],
            "workload_sha256": work.sha256, "status": status, "hits": query["gold"] if hits is None else hits}


class FreshnessScoringTests(unittest.TestCase):
    def setUp(self):
        self.work = workload()

    def test_same_document_id_with_old_version_is_a_miss(self):
        query = self.work.query_map["after"]
        row = score_row(self.work, query, observation(self.work, hits=self.work.query_map["before"]["gold"]))
        self.assertEqual(row["doc_id_recall"], 1)
        self.assertEqual(row["recall"], 0)
        self.assertEqual(row["violations"]["stale"], 1)

    def test_claimed_current_version_with_wrong_hash_cannot_hit(self):
        hit = {**self.work.query_map["after"]["gold"][0], "content_hash": digest("tampered")}
        row = score_row(self.work, self.work.query_map["after"], observation(self.work, hits=[hit]))
        self.assertEqual(row["recall"], 0)
        self.assertEqual(row["violations"]["unverified"], 1)

    def test_future_revision_and_deleted_resource_are_detected(self):
        future = observation(self.work, "before", hits=self.work.query_map["after"]["gold"])
        row = score_row(self.work, self.work.query_map["before"], future)
        self.assertEqual(row["violations"]["future"], 1)
        deleted = observation(self.work, "deleted", hits=[self.work.query_map["multi"]["gold"][1]])
        row = score_row(self.work, self.work.query_map["deleted"], deleted)
        self.assertFalse(row["correct_empty"])
        self.assertEqual(row["violations"]["withdrawn"], 1)

    def test_permissions_are_scored_against_source_truth(self):
        result = observation(self.work, "denied", hits=self.work.query_map["after"]["gold"])
        row = score_row(self.work, self.work.query_map["denied"], result)
        self.assertEqual(row["violations"]["unauthorized"], 1)
        self.assertFalse(row["correct_empty"])

    def test_duplicate_hits_consume_slots_without_extra_credit(self):
        query = self.work.query_map["multi"]
        result = observation(self.work, "multi", hits=[query["gold"][0], query["gold"][0], query["gold"][1]])
        self.assertEqual(score_row(self.work, query, result, k=2)["recall"], .5)

    def test_missing_and_failed_queries_remain_in_denominator(self):
        report = score_results(self.work, [observation(self.work)], arms=("target",), modes=("keyword",))
        summary = next(row for row in report["summaries"] if row["kind"] == "all")
        self.assertEqual(summary["issued_queries"], 5)
        self.assertEqual(summary["answerable_queries"], 3)
        self.assertEqual(summary["missing_results"], 4)
        self.assertAlmostEqual(summary["version_recall"], 1 / 3)
        failed = observation(self.work, status="timeout")
        self.assertEqual(score_row(self.work, self.work.query_map["after"], failed)["recall"], 0)

    def test_unavailable_is_not_a_successful_expected_refusal(self):
        result = observation(self.work, "denied", status="unavailable")
        self.assertFalse(score_row(self.work, self.work.query_map["denied"], result)["correct_empty"])

    def test_duplicate_out_of_population_and_wrong_clock_results_rejected(self):
        good = observation(self.work)
        for records in ([good, good], [{**good, "query_id": "extra"}], [{**good, "at_ms": 99}],
                        [{**good, "workload_sha256": "wrong"}], [{**good, "latency_ms": float("nan")} ]):
            with self.subTest(records=records):
                with self.assertRaises(ValueError):
                    score_results(self.work, records, arms=("target",), modes=("keyword",))

    def test_gold_cannot_silently_follow_serving_versions(self):
        data = copy.deepcopy(self.work.data)
        data["queries"][1]["gold"] = data["queries"][0]["gold"]
        with self.assertRaises(ValueError):
            Workload(data)

    def test_empty_gold_requires_an_explicit_label(self):
        data = copy.deepcopy(self.work.data)
        del data["queries"][3]["expect_empty"]
        with self.assertRaises(ValueError):
            Workload(data)

    def test_rollback_is_current_even_when_content_version_is_older(self):
        data = copy.deepcopy(self.work.data)
        data["events"].append({"id": "rollback", "at_ms": 300, "corpus": "fixture", "doc_id": "a", "op": "upsert", "version": "v1"})
        query = {**data["queries"][0], "id": "rollback-query", "at_ms": 300}
        data["queries"].append(query)
        data["horizon_ms"] = 300
        work = Workload(data)
        row = score_row(work, query, observation(work, "rollback-query"))
        self.assertEqual(row["recall"], 1)
        self.assertEqual(row["violations"]["stale"], 0)

    def test_cross_corpus_evidence_cannot_hit(self):
        hit = {**self.work.query_map["after"]["gold"][0], "corpus": "other"}
        row = score_row(self.work, self.work.query_map["after"], observation(self.work, hits=[hit]))
        self.assertEqual(row["recall"], 0)

    def test_malformed_evidence_is_unverified_without_breaking_population(self):
        result = observation(self.work, hits=[{"corpus": [], "doc_id": "a", "version": "v2"}])
        report = score_results(self.work, [result], arms=("target",), modes=("keyword",))
        row = next(row for row in report["rows"] if row["query_id"] == "after")
        self.assertEqual(row["recall"], 0)
        self.assertEqual(row["violations"]["unverified"], 1)

    def test_repeated_version_activation_has_independent_visibility_samples(self):
        data = copy.deepcopy(self.work.data)
        first = {**data["queries"][1], "case_id": "same-resource", "anchor_event_id": "change"}
        data["events"].append({"id": "reactivate", "at_ms": 400, "corpus": "fixture", "doc_id": "a", "op": "upsert", "version": "v2"})
        second = {**first, "id": "again", "at_ms": 400, "anchor_event_id": "reactivate"}
        data["queries"] = [first, second]
        data["horizon_ms"] = 400
        work = Workload(data)
        report = score_results(work, [observation(work)], arms=("target",), modes=("keyword",))
        self.assertEqual(len(report["visibility"]), 2)
        self.assertEqual(sum(row["censored"] for row in report["visibility"]), 1)


class FreshnessReplayTests(unittest.TestCase):
    def test_resource_ids_with_slashes_cannot_collide_in_chunks(self):
        from contextledger.freshness_replay import Encoder, SnapshotReplay
        from contextledger.store import connect
        data = copy.deepcopy(workload().data)
        for row in data["revisions"] + data["events"]:
            row["corpus"], row["doc_id"] = ("one/two", "three") if row["doc_id"] == "a" else ("one", "two/three")
        query = data["queries"][1]
        query.update(corpus="one/two", targets=["three"])
        query["gold"][0].update(corpus="one/two", doc_id="three")
        data["queries"] = [query]
        work = Workload(data)
        with tempfile.TemporaryDirectory() as directory:
            backend = SnapshotReplay(work, Path(directory), Encoder(work, "fixture"))
            try:
                with connect(backend.db_path) as db:
                    self.assertEqual(db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0], 2)
            finally:
                backend.close()

    def test_controlled_replay_exposes_staleness_outages_and_late_regression(self):
        work = example_workload(cases=6)
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
            report = replay(work, Path(directory), embedding="fixture", modes=("keyword", "vector"))
            reference_rows = [row for row in report["rows"] if row["arm"] == "fully_synced" and row["gold_count"]]
            self.assertTrue(reference_rows)
            self.assertTrue(all(row["recall"] == 1 for row in reference_rows))
            stale = [row for row in report["rows"] if row["arm"] == "stale_snapshot" and row["kind"] == "chasing"]
            self.assertTrue(any(row["doc_id_recall"] == 1 and row["recall"] == 0 for row in stale))
            current = [row for row in report["rows"] if row["arm"] == "current_snapshot"]
            self.assertTrue(any(row["kind"] == "regular" and row["status"] == "unavailable" for row in current))
            self.assertTrue(any(row["violations"]["stale"] for row in current if row["case_id"] == "case-06"))
            self.assertTrue(any(row["phase"] == "recovery" for row in report["rows"]))
            self.assertEqual(report["population"]["observed_results"], report["population"]["expected_results"])
            self.assertFalse(report["execution"]["post_horizon_flush"])
            paired = [row for row in report["rows"] if row["query_id"] == "case-02-regular-100"]
            self.assertTrue(all(row["age_ms"] == 100 for row in paired))
            for filename in ("workload.json", "results.jsonl", "report.json", "curves.csv", "visibility.csv", "failures.jsonl", "report.html"):
                self.assertTrue((Path(directory) / filename).is_file())

    def test_offline_rescore_matches_replay_and_failed_runs_replace_status(self):
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
            root = Path(directory)
            source, output = root / "run", root / "rescore"
            report = replay(example_workload(cases=1), source, embedding="fixture", modes=("keyword",))
            self.assertEqual(main(["score", "--workload", str(source / "workload.json"), "--results", str(source / "results.jsonl"),
                                   "--out", str(output), "--arms", *ARMS_FOR_TEST, "--modes", "keyword"]), 0)
            rescored = json.loads((output / "report.json").read_text())
            self.assertEqual(rescored["summaries"], report["summaries"])
            invalid = root / "invalid.json"
            invalid.write_text('{"schema_version":999}')
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                main(["run", "--workload", str(invalid), "--out", str(output), "--embedding", "fixture"])
            self.assertEqual(json.loads((output / "report.json").read_text())["status"], "failed")


ARMS_FOR_TEST = ("current_snapshot", "fully_synced", "stale_snapshot")
