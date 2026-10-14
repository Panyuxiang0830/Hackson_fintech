import json
import tempfile
import unittest
from pathlib import Path

from contextledger.audit.store import AuditStore
from contextledger.evaluation.audit_fixture import tamper


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
        self.path = Path(self.temp_dir.name) / "audit.sqlite"
        self.audit = AuditStore(self.path)

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
        tamper(self.audit, "modify")

        verification = self.audit.verify()
        self.assertFalse(verification.valid)
        self.assertIn("content hash mismatch", verification.error or "")

    def test_deleted_tail_event_is_detected_by_checkpoint(self):
        self.audit.append(audit_record("req-1"))
        self.audit.append(audit_record("req-2"))
        tamper(self.audit, "delete_tail")

        verification = self.audit.verify()
        self.assertFalse(verification.valid)
        self.assertIn("checkpoint", verification.error or "")

    def test_reordered_events_are_detected(self):
        self.audit.append(audit_record("req-1"))
        self.audit.append(audit_record("req-2"))
        tamper(self.audit, "reorder")

        verification = self.audit.verify()
        self.assertFalse(verification.valid)
        self.assertIn("sequence/chain mismatch", verification.error or "")


if __name__ == "__main__":
    unittest.main()
