"""Shared deterministic query parser uses local DTOs, never legacy JSON."""
from datetime import datetime, timedelta, timezone
import unittest

from contextledger.answering.models import Document, User
from contextledger.audit.query import AuditQueryParser


class AuditQueryParserTests(unittest.TestCase):
    def setUp(self):
        self.user = User("employee-fixture", "Alice", "engineering", "member", "internal")
        self.doc = Document("jira-fixture", "jira", "Decision", "Approved",
                            "2026-01-01", "2026-01-01", "2026-01-01", "2026-01-01", "internal")
        self.now = datetime(2026, 10, 14, 12, tzinfo=timezone.utc)

    def parse(self, query):
        return AuditQueryParser().parse(query, {self.user.id: self.user}, [self.doc], now=self.now)

    def test_user_document_and_relative_time_are_preserved(self):
        parsed = self.parse("What did Alice access about jira-fixture in the last 30 days?")
        self.assertEqual(parsed["user_id"], self.user.id)
        self.assertEqual(parsed["document_id"], self.doc.id)
        self.assertEqual(parsed["start"], (self.now - timedelta(days=30)).isoformat())
        self.assertEqual(parsed["end"], self.now.isoformat())

    def test_request_id_and_stable_identity_match(self):
        request_id = "018271a8-03cd-43a2-bce8-ceb3ff039da0"
        parsed = self.parse(f"Show employee-fixture request {request_id}")
        self.assertEqual(parsed["request_id"], request_id)
        self.assertEqual(parsed["user_id"], self.user.id)

    def test_unknown_identity_or_document_is_not_invented(self):
        parsed = self.parse("Show an unknown employee and unknown document")
        self.assertIsNone(parsed["user_id"])
        self.assertIsNone(parsed["document_id"])
