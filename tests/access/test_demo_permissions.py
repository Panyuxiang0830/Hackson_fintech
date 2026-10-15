"""Demo annotations remain explicit, scoped, and enforced by real index filters."""
import copy
import json
import unittest

from contextledger.access.demo_permissions import plan_annotations
from contextledger.storage.document_updates import DocumentUpdates
from contextledger.storage.models import Chunk
from contextledger.storage.store import connect
from tests.application import test_integration as fixtures


class DemoPermissionTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.IntegrationTests(); self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.addCleanup(self.f.app.extensions['document_updates'].close)
        self.updates = DocumentUpdates(self.f.index, self.f.ids, self.f.audit,
            embed=lambda texts: [[1.0, 0.0] for _ in texts],
            chunker=lambda doc: [Chunk(doc.doc_id+'-annotation',doc.corpus,doc.doc_id,0,doc.text)],
            autostart=False)
        self.addCleanup(self.updates.close)
        with connect(self.f.db_path) as db:
            self.rows = [dict(r) for r in db.execute('SELECT * FROM documents')]
        self.manifest = {'schema_version':1,'authority':'team_decision','scenario_id':'demo-test',
            'corpus':'alpha','project':'demo:payments','department':'eng',
            'allowed_departments':['eng'],'classification':'confidential',
            'employee_source_principal':'alpha:a','employee_clearance':2,
            'documents':[{'doc_id':r['doc_id'],'expected_content_hash':r['content_hash'],'grant_employee':False}
                         for r in self.rows if r['doc_id'] in {'doc-0','doc-1'}]}

    def publish(self, bodies):
        for body in bodies:
            job = self.updates.submit(self.f.admin.id, body)
            self.updates.process_one()
            self.assertEqual(self.updates.status(self.f.admin.id, job['id'])['state'], 'ready')

    def test_scoped_labels_enforce_clearance_project_and_departments_in_all_retrieval_modes(self):
        before = {r['doc_id']:r for r in self.rows}
        self.publish(plan_annotations(self.manifest, self.rows))
        with connect(self.f.db_path) as db:
            after = {r['doc_id']:dict(r) for r in db.execute('SELECT * FROM documents')}
        self.assertEqual(before['doc-2'], after['doc-2'])
        self.assertEqual(before['doc-3'], after['doc-3'])
        for id in ('doc-0','doc-1'):
            self.assertEqual(after[id]['content_hash'], before[id]['content_hash'])
            self.assertEqual(after[id]['text'], before[id]['text'])
            self.assertEqual(json.loads(after[id]['acl_json']), json.loads(before[id]['acl_json']))
            meta = json.loads(after[id]['extra_json'])
            self.assertEqual(meta['permission_annotation']['kind'], 'manual_demo')
        self.assertEqual(plan_annotations(self.manifest, list(after.values())), [])
        for mode in ('keyword','vector','hybrid'):
            with self.subTest(mode=mode):
                actor = self.f.ids.get(self.f.alice.id)
                hits,_ = self.f.index.search(self.f.index.scope(actor,'alpha'),'TitanDB',mode=mode)
                self.assertEqual(hits, [])  # Internal clearance cannot read confidential material.
        self.f.ids.update(self.f.alice.id, clearance=2, projects=["demo:payments"])
        for mode in ('keyword','vector','hybrid'):
            actor = self.f.ids.get(self.f.alice.id)
            hits,_ = self.f.index.search(self.f.index.scope(actor,'alpha'),'TitanDB',mode=mode)
            self.assertEqual({h['doc_id'] for h in hits}, {'doc-0','doc-1'})
        self.f.ids.restrict(self.f.alice.id,'alpha','project','demo:payments',True)
        actor = self.f.ids.get(self.f.alice.id)
        hits,_ = self.f.index.search(self.f.index.scope(actor,'alpha'),'TitanDB')
        self.assertEqual(hits, [])
        self.assertIsNone(self.f.index.open(self.f.index.scope(actor,'alpha'),'doc-0')[0])
        self.f.ids.restrict(self.f.alice.id,'alpha','project','demo:payments',False)
        changed = copy.deepcopy(self.manifest); changed['allowed_departments'] = ['sales']
        self.publish(plan_annotations(changed, list(after.values())))
        actor = self.f.ids.get(self.f.alice.id)
        for mode in ('keyword','vector','hybrid'):
            hits,_ = self.f.index.search(self.f.index.scope(actor,'alpha'),'TitanDB',mode=mode)
            self.assertEqual(hits, [])  # ACL+clearance allow, but department constraint rejects.
        self.f.login(self.f.admin)
        catalog = self.f.client.get('/api/admin/content-scopes?user_id='+self.f.alice.id).json
        self.assertEqual(catalog[0]['attribute_controls'], {'projects':['demo:payments'],
            'allowed_departments':['sales'],'classifications':[2]})
        self.assertTrue(self.f.audit.verify().valid)

    def test_changed_or_unlisted_content_and_duplicate_ids_are_rejected(self):
        for change in ('hash','missing','duplicate'):
            manifest = copy.deepcopy(self.manifest)
            if change == 'hash': manifest['documents'][0]['expected_content_hash'] = '0'*64
            if change == 'missing': manifest['documents'][0]['doc_id'] = 'missing'
            if change == 'duplicate': manifest['documents'].append(manifest['documents'][0])
            with self.subTest(change=change), self.assertRaises(ValueError):
                plan_annotations(manifest,self.rows)

    def test_private_slack_access_cannot_be_expanded_by_annotation(self):
        row = next(r for r in self.rows if r['doc_id']=='doc-2')
        manifest = copy.deepcopy(self.manifest)
        manifest['documents'] = [{'doc_id':'doc-2','expected_content_hash':row['content_hash'],'grant_employee':True}]
        with self.assertRaisesRegex(ValueError,'Slack'):
            plan_annotations(manifest,self.rows)

    def test_manual_annotation_cannot_claim_verified_source_authority(self):
        body = plan_annotations(self.manifest,self.rows)[0]
        body['permission_annotation']['authority'] = 'source_verified'
        with self.assertRaises(ValueError):
            self.updates.submit(self.f.admin.id, body)


if __name__ == '__main__': unittest.main()
