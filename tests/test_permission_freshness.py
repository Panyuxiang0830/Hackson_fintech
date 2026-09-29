import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from src.data import load_documents, load_users
from src.freshness import FreshnessService
from src.service import KnowledgeService


class PermissionAndFreshnessTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.users = load_users()

    def tearDown(self):
        self.temp_dir.cleanup()

    def build_service(self, documents=None):
        return KnowledgeService(
            documents or load_documents(),
            audit_path=Path(self.temp_dir.name) / "audit.jsonl",
            users=self.users,
        )

    def test_revoked_project_access_applies_to_next_query(self):
        service = self.build_service()
        stale_user_object = self.users["alice"]
        question = "SG Batch Payments incident technical root cause"

        before = service.ask(stale_user_object, question)
        self.assertIn("jira-002", {item.document.id for item in before.evidence})

        service.revoke_project_access("carol", "alice", "payments-sg")
        after = service.ask(stale_user_object, question)
        self.assertNotIn("jira-002", {item.document.id for item in after.evidence})
        self.assertEqual(after.user.projects, ())

        service.reset_identity("carol", "alice")
        restored = service.ask("alice", question)
        self.assertIn("jira-002", {item.document.id for item in restored.evidence})

    def test_known_stale_version_is_excluded_before_retrieval(self):
        documents = load_documents()
        stale_documents = [
            replace(document, source_updated_at="2026-09-25T12:00:00+08:00")
            if document.id == "jira-002"
            else document
            for document in documents
        ]
        service = self.build_service(stale_documents)

        result = service.ask("alice", "SG Batch Payments incident technical root cause")
        self.assertNotIn("jira-002", {item.document.id for item in result.evidence})
        self.assertEqual(result.stale_document_count, 1)

    def test_source_update_becomes_servable_after_sync(self):
        service = self.build_service()
        service.mark_source_updated("carol", "jira-002", "2026-09-25T12:00:00+08:00")
        marked = next(document for document in service.list_documents() if document.id == "jira-002")
        self.assertEqual(FreshnessService().evaluate(marked).status, "stale")

        service.sync_document("carol", "jira-002")
        synced = next(document for document in service.list_documents() if document.id == "jira-002")
        freshness = FreshnessService().evaluate(synced)
        self.assertTrue(freshness.servable)
        self.assertIn(freshness.status, {"current", "delayed"})


if __name__ == "__main__":
    unittest.main()
