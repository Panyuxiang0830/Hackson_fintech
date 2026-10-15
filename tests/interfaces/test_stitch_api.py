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
            self.assertEqual(event["evidence_visibility"], "current_access_unavailable")
            self.assertFalse(event["authorization_decisions"])
        self.fixture.login(self.fixture.alice)
        source = self.client.get("/api/doc?corpus=alpha&doc_id=doc-0")
        self.assertEqual(source.status_code, 404)
        self.assertFalse(source.json["available"])

    def test_empty_event_and_authorised_evidence_have_distinct_audit_states(self):
        event=self.fixture.service.record(self.fixture.ids.get(self.fixture.admin.id),"permission_change")
        self.fixture.login(self.fixture.admin)
        data=self.client.get('/api/audit?request_id='+event['request_id']).json
        self.assertEqual(data['events'][0]['evidence_visibility'],'not_recorded')
        self.assertEqual(data['events'][0]['returned_evidence_count'],0)
        self.fixture.ids.update(self.fixture.alice.id,role='compliance')
        self.fixture.login(self.fixture.ids.get(self.fixture.alice.id))
        answer=self.fixture.post('/api/ask',{'q':'TitanDB','corpus':'alpha','mode':'keyword','planning':False})
        data=self.client.get('/api/audit?request_id='+answer.json['request_id']).json
        item=data['events'][0]
        self.assertEqual(item['evidence_visibility'],'visible')
        self.assertFalse(item['redacted'])
        self.assertTrue(item['authorization_decisions'])
        actor=self.fixture.ids.get(self.fixture.alice.id)
        hits,_=self.fixture.index.search(self.fixture.index.scope(actor,'alpha'),'TitanDB',mode='keyword')
        historical=self.fixture.service.record(actor,'answer',hits=[hits[0]|{'version':'older-recorded-version'}])
        data=self.client.get('/api/audit?request_id='+historical['request_id']).json
        self.assertEqual(data['events'][0]['evidence_visibility'],'version_mismatch')
        self.assertFalse(data['events'][0]['evidence'])
        from unittest.mock import patch
        from contextledger.retrieval.filtered_index import IndexUnavailable
        with patch.object(self.fixture.index,'open',side_effect=IndexUnavailable('unverified index')):
            data=self.client.get('/api/audit?request_id='+answer.json['request_id']).json
        self.assertEqual(data['events'][0]['evidence_visibility'],'index_unavailable')

    def test_english_interface_refusal_and_language_validation(self):
        result=self.fixture.post('/api/ask',{'q':'未知的测试项目','corpus':'alpha','mode':'keyword','planning':False,'output_language':'en'})
        self.assertEqual(result.status_code,200)
        self.assertNotRegex(result.json['answer'],r'[\u4e00-\u9fff]')
        result=self.fixture.post('/api/ask',{'q':'TitanDB','corpus':'alpha','output_language':'invalid'})
        self.assertEqual(result.status_code,400)


if __name__ == "__main__":
    unittest.main()
