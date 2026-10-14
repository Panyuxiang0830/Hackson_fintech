import json
import tempfile
import unittest
from pathlib import Path

from src.audit import AuditService


def audit_record(request_id: str) -> dict:
    return {
        "event_type": "knowledge_query",
        "request_id": request_id,
        "timestamp": "2026-09-29T10:00:00+00:00",
        "user_id": "alice",
        "question": "status",
        "authorization_decisions": [],
        "retrieved_document_ids": [],
        "final_answer": "answer",
        "decision": "answered",
        "provider": "mock",
    }


class AuditChainTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.path = Path(self.temp_dir.name) / "audit.jsonl"
        self.audit = AuditService(self.path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_hash_chain_and_checkpoint_are_valid(self):
        first = self.audit.append(audit_record("req-1"))
        second = self.audit.append(audit_record("req-2"))

        verification = self.audit.verify()
        self.assertTrue(verification.valid)
        self.assertEqual(verification.event_count, 2)
        self.assertEqual(second["previous_hash"], first["event_hash"])
        self.assertEqual(verification.head_hash, second["event_hash"])

    def test_modified_event_is_detected(self):
        self.audit.append(audit_record("req-1"))
        record = json.loads(self.path.read_text(encoding="utf-8"))
        record["final_answer"] = "tampered"
        self.path.write_text(json.dumps(record) + "\n", encoding="utf-8")

        verification = self.audit.verify()
        self.assertFalse(verification.valid)
        self.assertIn("content hash mismatch", verification.error or "")

    def test_deleted_tail_event_is_detected_by_checkpoint(self):
        self.audit.append(audit_record("req-1"))
        self.audit.append(audit_record("req-2"))
        first_line = self.path.read_text(encoding="utf-8").splitlines()[0]
        self.path.write_text(first_line + "\n", encoding="utf-8")

        verification = self.audit.verify()
        self.assertFalse(verification.valid)
        self.assertIn("checkpoint", verification.error or "")

    def test_reordered_events_are_detected(self):
        self.audit.append(audit_record("req-1"))
        self.audit.append(audit_record("req-2"))
        lines = self.path.read_text(encoding="utf-8").splitlines()
        self.path.write_text("\n".join(reversed(lines)) + "\n", encoding="utf-8")

        verification = self.audit.verify()
        self.assertFalse(verification.valid)
        self.assertIn("sequence mismatch", verification.error or "")


if __name__ == "__main__":
    unittest.main()
