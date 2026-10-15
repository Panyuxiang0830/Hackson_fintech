"""Exercise the approved UI contract against the refactored Flask application."""
from pathlib import Path
import unittest

from tests.application import test_integration as integration_fixture


class StitchAPIContractTests(unittest.TestCase):
    def setUp(self):
        self.fixture = integration_fixture.IntegrationTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.addCleanup(self.fixture.app.extensions["document_updates"].close)
        self.client = self.fixture.client

    def test_default_entry_and_assets_resolve_from_interfaces_package(self):
        expected = Path(__file__).resolve().parents[2] / "contextledger/interfaces/static/stitch/index.html"
        with self.client.get("/") as response:
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data, expected.read_bytes())
            self.assertIn("script-src 'self'", response.headers["Content-Security-Policy"])
        for asset in ("app.js", "design.css", "responsive.css", "fonts.css", "assets/vectorized.svg.svg"):
            with self.subTest(asset=asset), self.client.get("/static/stitch/" + asset) as response:
                self.assertEqual(response.status_code, 200)

    def test_session_query_and_passport_keep_the_frontend_contract(self):
        session = self.client.get("/api/session").json
        self.assertEqual(session["user"]["id"], self.fixture.alice.id)
        self.assertFalse(session["demo_auto_entry"])
        self.assertIn("planner_configured", session["workflows"])
        answer = self.fixture.post("/api/ask", {"q": "TitanDB", "corpus": "alpha", "mode": "keyword", "planning": False})
        self.assertEqual(answer.status_code, 200, answer.json)
        self.assertEqual({item["doc_id"] for item in answer.json["evidence"]}, {"doc-0", "doc-1"})
        self.assertNotIn("radar_presentation", answer.json)  # Ordinary answers do not imply Confirmed.
        source = self.client.get("/api/doc?corpus=alpha&doc_id=doc-0")
        self.assertEqual(source.status_code, 200, source.json)
        self.assertTrue(source.json["available"])
        for field in ("title", "text", "version", "content_hash", "acl_basis", "metadata", "source_check"):
            self.assertIn(field, source.json["doc"])

    def test_permission_change_blocks_old_source_and_redacts_audit(self):
        answer = self.fixture.post("/api/ask", {"q": "TitanDB", "corpus": "alpha", "mode": "keyword", "planning": False})
        self.assertEqual(answer.status_code, 200)
        self.fixture.login(self.fixture.admin)
        changed = self.fixture.post("/api/admin/permissions", {"user_id": self.fixture.alice.id,
            "action": "binding", "corpus": "alpha", "principal_id": "alpha:a", "enabled": False})
        self.assertEqual(changed.status_code, 200, changed.json)
        audited = self.client.get("/api/audit?request_id=" + answer.json["request_id"])
        self.assertEqual(audited.status_code, 200, audited.json)
        self.assertTrue(audited.json["events"])
        for event in audited.json["events"]:
            self.assertTrue(event["redacted"])
            self.assertFalse(event["evidence"])
            self.assertIsNone(event.get("radar_presentation"))
        self.fixture.login(self.fixture.alice)
        source = self.client.get("/api/doc?corpus=alpha&doc_id=doc-0")
        self.assertEqual(source.status_code, 404)
        self.assertFalse(source.json["available"])


if __name__ == "__main__":
    unittest.main()
