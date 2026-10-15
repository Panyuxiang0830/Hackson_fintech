"""Time mapping regressions using the deployed Slack record shapes, without text data."""
import unittest
from contextledger.radar.timing import source_timing, order_events, parsed_time, model_event
from contextledger.radar.tool import DecisionRadarTool


class RadarTimingTests(unittest.TestCase):
    def event(self, ts=None, metadata=None, citation=1, **fields):
        return {"citation_id": citation, **source_timing({"metadata": metadata or {}, "ts": ts, **fields})}

    def test_slack_ts_fallback_orders_records_and_preserves_date_conflict(self):
        # Search rank puts the merge notification first; citation registry stays fixed.
        hits = [{"doc_id": str(i), "title": "PR-135", "full_text": "PR-135",
                 "text": "PR-135", "source": "slack", "version": "v1", "chunk_id": str(i),
                 "ts": ts, "day": 0, "metadata": {"date": "2026-02-17"}}
                for i, ts in enumerate(["2026-02-18T09:38:43", "2026-02-17T09:37:07"])]
        class Index:
            def related(self, *args, **kwargs):
                return [], "g1", False
        selected, report = DecisionRadarTool(Index()).execute(query="PR-135 history", scope=None,
            generation="g1", seeds=hits, arguments={"anchor_ids": ["PR-135"]}, guard=lambda: None)
        self.assertEqual(selected, hits)
        events = report["event_candidates"]
        self.assertEqual([e["citation_id"] for e in events], [2, 1])
        self.assertEqual(events[0]["source_record_time"], "2026-02-17T09:37:07")
        self.assertEqual(events[1]["source_record_time"], "2026-02-18T09:38:43")
        self.assertIsNone(events[0]["event_time"])
        self.assertEqual(events[1]["source_time_fields"], {"ts": "2026-02-18T09:38:43", "date": "2026-02-17", "day": 0})
        self.assertIn("date=2026-02-17", events[1]["time_warnings"][0])
        self.assertEqual(events[1]["time_group"], "local_timestamp")
        self.assertIn("Timezone unspecified", events[0]["time_warnings"][0])

    def test_offsets_sort_by_instant_without_comparing_against_local_or_day(self):
        events = [self.event("2026-02-18T00:00:00", citation=1),
                  self.event("2026-02-17T23:00:00Z", citation=2),
                  self.event("2026-02-18T06:00:00+08:00", citation=3),
                  self.event("2026-02-16", citation=4), self.event(citation=5)]
        ordered, policy = order_events(events)
        self.assertEqual([e["citation_id"] for e in ordered], [3, 2, 1, 4, 5])
        self.assertEqual(policy["groups"], ["offset_timestamp", "local_timestamp", "day", "unknown"])
        self.assertEqual(ordered[2]["source_record_time"], "2026-02-18T00:00:00")

    def test_native_snapshot_does_not_borrow_parent_or_observation_time(self):
        event = self.event("2026-02-17T09:00:00", {"record_type": "native_state",
            "event_time": None, "source_date": "2026-02-17", "observed_at": "2026-03-01T00:00:00Z"})
        self.assertIsNone(event["source_record_time"])
        self.assertEqual(event["time_precision"], "unknown")
        self.assertEqual(event["source_time_fields"]["ts"], "2026-02-17T09:00:00")

    def test_missing_invalid_and_day_precision_are_not_fabricated(self):
        for value in [None, "", "1700000000", "yesterday", "2026-02-30", "2026-02-17T25:00:00", 123]:
            with self.subTest(value=value):
                self.assertIsNone(parsed_time(value))
                self.assertIsNone(self.event(value)["source_record_time"])
        event = self.event(metadata={"date": "2026-02-17"}, day=0)
        self.assertEqual(event["time_precision"], "day")
        self.assertEqual(event["source_record_time"], "2026-02-17")
        self.assertEqual(event["source_time_fields"]["day"], 0)

    def test_explicit_event_time_compatibility_and_raw_mismatch(self):
        event = self.event(metadata={"event_time": "2026-02-18T09:00:00Z", "source_date": "2026-02-17"})
        self.assertEqual(event["time_basis"], "metadata.event_time")
        self.assertIn("source_date=2026-02-17", event["time_warnings"][0])

    def test_model_time_payload_keeps_mismatch_without_repeated_ui_prose(self):
        import json
        event = {"type": "artifact", "event_time": None, "historical": False,
                 **self.event("2026-02-18T09:38:43", {"date": "2026-02-17"}, day=0)}
        compact = model_event(event)
        self.assertEqual(compact['source_record_time'], '2026-02-18T09:38:43')
        self.assertEqual(compact['source_time_fields'], {'date': '2026-02-17', 'day': 0})
        self.assertEqual(compact['time_warnings'], ['source_date_mismatch'])
        self.assertLess(len(json.dumps([compact]*120)), 36000)
