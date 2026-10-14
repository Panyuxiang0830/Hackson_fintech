import tempfile
import unittest
from pathlib import Path

from src.data import load_documents, load_users
from src.service import KnowledgeService


class AuditQueryTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.users = load_users()
        self.service = KnowledgeService(
            load_documents(),
            audit_path=Path(self.temp_dir.name) / "audit.jsonl",
            users=self.users,
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_compliance_can_query_complete_audit_record(self):
        result = self.service.ask("alice", "What was the incident root cause?")
        records = self.service.query_audit("carol", user_id="alice")

        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record["request_id"], result.request_id)
        self.assertIn("final_answer", record)
        self.assertEqual(len(record["authorization_decisions"]), len(load_documents()))
        self.assertTrue(self.service.audit_integrity().valid)

    def test_non_compliance_audit_query_is_denied_and_logged(self):
        with self.assertRaises(PermissionError):
            self.service.query_audit("bob", user_id="alice")

        records = self.service.query_audit("carol", user_id="bob")
        self.assertEqual(records[0]["event_type"], "audit_query")
        self.assertEqual(records[0]["decision"], "denied")

    def test_natural_language_audit_query_extracts_user_document_and_time(self):
        result = self.service.ask("alice", "What was the incident root cause in jira-002?")
        records = self.service.query_audit_text(
            "carol",
            "Show me what alice accessed related to jira-002 in the last 30 days",
        )

        self.assertEqual([record["request_id"] for record in records], [result.request_id])


if __name__ == "__main__":
    unittest.main()
