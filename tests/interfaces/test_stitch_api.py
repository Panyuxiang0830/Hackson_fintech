"""Exercise the approved UI contract against the refactored Flask application."""
from pathlib import Path
import unittest
from unittest.mock import patch

from contextledger.access.identity_store import IdentityStore

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
        for asset in ("app.js", "design.css", "responsive.css", "fonts.css", "assets/vectorized.svg.svg", "assets/contextledger-logo.svg"):
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

    def test_permission_change_blocks_old_source_but_preserves_admin_history(self):
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
            self.assertFalse(event['redacted'])
            self.assertTrue(event['evidence'])
            self.assertEqual(event['evidence_visibility'],'visible')
            self.assertTrue(event['authorization_decisions'])
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

    def test_dataset_directory_survives_content_and_mapping_revocation(self):
        f = self.fixture
        self.assertEqual([c['id'] for c in self.client.get('/api/corpora').json], ['alpha'])
        f.ids.restrict(f.alice.id, 'alpha', 'corpus', 'alpha', True)
        self.assertEqual([c['id'] for c in self.client.get('/api/corpora').json], ['alpha'])
        f.ids.bind(f.alice.id, 'alpha', 'alpha:a', False)
        reopened = IdentityStore(f.ids.path)
        self.assertEqual(reopened.associated_corpora(f.alice.id), {'alpha'})
        self.assertEqual([c['id'] for c in self.client.get('/api/corpora').json], ['alpha'])
        self.assertEqual(self.client.get('/api/doc?corpus=alpha&doc_id=doc-0').status_code, 404)
        self.assertEqual(self.client.get('/api/search?corpus=beta&q=TitanDB').json['hits'], [])

    def test_source_and_document_permissions_change_actual_retrieval(self):
        f = self.fixture
        def change(kind, value, denied):
            f.login(f.admin)
            response = f.post('/api/admin/permissions', {'user_id': f.alice.id,
                'action': 'restriction', 'corpus': 'alpha', 'kind': kind,
                'value': value, 'denied': denied})
            self.assertEqual(response.status_code, 200, response.json)
            f.login(f.alice)
        original_epoch = f.ids.get(f.alice.id).epoch
        change('source', 'jira', True)
        for mode in ('keyword', 'vector', 'hybrid'):
            response = self.client.get('/api/search', query_string={
                'corpus': 'alpha', 'q': 'TitanDB', 'mode': mode, 'planning': 'false'})
            self.assertEqual({h['doc_id'] for h in response.json['hits']}, {'doc-0'})
        self.assertEqual(self.client.get('/api/doc?corpus=alpha&doc_id=doc-1').status_code, 404)
        change('document', 'doc-0', True)
        self.assertEqual(self.client.get('/api/search?corpus=alpha&q=TitanDB').json['hits'], [])
        change('document', 'doc-0', False)
        change('source', 'jira', False)
        response = self.client.get('/api/search?corpus=alpha&q=TitanDB').json
        self.assertEqual({h['doc_id'] for h in response['hits']}, {'doc-0', 'doc-1'})
        # Restoring local permissions cannot grant Bob's Slack document to Alice.
        self.assertEqual(self.client.get('/api/doc?corpus=alpha&doc_id=doc-2').status_code, 404)
        self.assertGreater(f.ids.get(f.alice.id).epoch, original_epoch)
        events = [e for e in f.audit.query(limit=100) if e['event_type'] == 'permission_change']
        self.assertEqual(len(events), 4)
        self.assertTrue(f.audit.verify().valid)

    def test_all_reading_revoked_keeps_dataset_and_never_calls_models(self):
        f = self.fixture
        unknown = f.post('/api/ask', {'corpus': 'alpha', 'q': 'CompletelyUnknownEntity',
                                      'planning': False, 'output_language': 'en'}).json
        f.login(f.admin)
        changed = f.post('/api/admin/permissions', {'user_id': f.alice.id,
            'action': 'restriction', 'corpus': 'alpha', 'kind': 'corpus',
            'value': 'alpha', 'denied': True})
        self.assertEqual(changed.status_code, 200)
        f.login(f.alice)
        with patch.object(f.service.planner, 'plan', side_effect=AssertionError('planner called')), \
                patch.object(f.service.answer, 'answer', side_effect=AssertionError('answer model called')):
            answer = f.post('/api/ask', {'corpus': 'alpha', 'q': 'TitanDB', 'planning': True,
                                       'output_language': 'en'})
        self.assertEqual(answer.status_code, 200, answer.json)
        self.assertEqual(answer.json['decision'], 'insufficient')
        self.assertEqual(answer.json['evidence'], [])
        self.assertEqual(answer.json['answer'], unknown['answer'])  # No permission/existence oracle.
        self.assertEqual(answer.json['llm_diagnostics']['attempts'], 0)
        self.assertEqual([c['id'] for c in self.client.get('/api/corpora').json], ['alpha'])
        self.assertEqual(self.client.get('/api/doc?corpus=alpha&doc_id=doc-0').status_code, 404)

    def test_content_scope_catalog_is_admin_only_and_contains_no_business_details(self):
        f = self.fixture
        endpoint = '/api/admin/content-scopes?user_id=' + f.alice.id
        self.assertEqual(self.client.get(endpoint).status_code, 403)
        f.login(f.admin)
        response = self.client.get(endpoint)
        self.assertEqual(response.json, [{'id': 'alpha', 'sources': ['confluence', 'jira', 'slack']}])
        self.assertNotIn('Title', response.get_data(as_text=True))
        self.assertEqual(self.client.get('/api/admin/content-scopes?user_id=unknown').status_code, 400)
        f.login(f.alice)
        self.assertEqual(f.post('/api/admin/permissions', {'action': 'restriction',
            'user_id': f.alice.id, 'corpus': 'alpha', 'kind': 'source',
            'value': 'jira', 'denied': False}).status_code, 403)


if __name__ == "__main__":
    unittest.main()
