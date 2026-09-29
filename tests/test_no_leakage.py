import tempfile
import unittest
from pathlib import Path

from src.data import load_documents, load_users
from src.service import KnowledgeService


class LeakageTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.service = KnowledgeService(
            load_documents(),
            audit_path=Path(self.temp_dir.name) / "audit.jsonl",
        )
        self.users = load_users()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_contractor_prompt_evidence_never_contains_restricted_documents(self):
        result = self.service.ask(
            self.users["dave"],
            "What was the technical root cause of the SG Batch Payments incident?",
        )
        self.assertTrue(result.evidence)
        self.assertTrue(all(item.document.classification != "restricted" for item in result.evidence))
        self.assertNotIn("jira-002", result.audit_record["retrieved_document_ids"])
        self.assertNotIn("confluence-002", result.audit_record["retrieved_document_ids"])

    def test_same_question_produces_different_evidence_by_identity(self):
        question = "SG Batch Payments incident root cause and customer recovery"
        engineer = self.service.ask(self.users["alice"], question)
        operations = self.service.ask(self.users["bob"], question)
        engineer_ids = {item.document.id for item in engineer.evidence}
        operations_ids = {item.document.id for item in operations.evidence}

        self.assertIn("jira-002", engineer_ids)
        self.assertNotIn("jira-002", operations_ids)
        self.assertIn("drive-002", operations_ids)


if __name__ == "__main__":
    unittest.main()

