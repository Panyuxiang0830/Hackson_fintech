import json
import tempfile
import unittest
from pathlib import Path

from src.data import load_documents, load_users
from src.service import KnowledgeService


class EndToEndTests(unittest.TestCase):
    def test_answer_has_authorised_citations_and_audit_record(self):
        with tempfile.TemporaryDirectory() as directory:
            audit_path = Path(directory) / "audit.jsonl"
            service = KnowledgeService(load_documents(), audit_path=audit_path)
            user = load_users()["bob"]
            result = service.ask(
                user,
                "Can Operations tell customers the service has recovered?",
            )

            self.assertEqual(result.decision, "answered")
            self.assertTrue(result.evidence)
            self.assertTrue(audit_path.exists())
            lines = audit_path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 1)
            record = json.loads(lines[0])
            self.assertEqual(record["request_id"], result.request_id)
            self.assertEqual(record["user_id"], "bob")
            self.assertEqual(
                set(record["retrieved_document_ids"]),
                {item.document.id for item in result.evidence},
            )


if __name__ == "__main__":
    unittest.main()

