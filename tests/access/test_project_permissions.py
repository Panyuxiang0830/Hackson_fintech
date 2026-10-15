"""Project membership is mandatory for tagged resources, never for untagged ones."""
import copy
import json
from pathlib import Path
import unittest

from contextledger.access.project_permissions import plan_project_annotations
from contextledger.storage.store import connect
from tests.access import test_demo_permissions as demo_fixtures


class ProjectPermissionTests(unittest.TestCase):
    def setUp(self):
        self.demo = demo_fixtures.DemoPermissionTests(); self.demo.setUp()
        self.addCleanup(self.demo.doCleanups)
        self.f = self.demo.f
        self.manifest = {'schema_version':1,'authority':'team_decision','corpus':'alpha',
            'projects':[{'id':'alpha:telemetry','name':'Telemetry dashboard',
                         'previous_project':'payments',
                         'documents':[{'doc_id':'doc-0','expected_content_hash':self.demo.rows[0]['content_hash']}]}]}
        self.f.ids.register_project('alpha','alpha:telemetry','Telemetry dashboard')
        self.demo.publish(plan_project_annotations(self.manifest,self.demo.rows))
        # The other employee-readable document has no project restriction.
        self.demo.publish([{'corpus':'alpha','doc_id':'doc-1',
            **{k:next(r[k] for r in self.demo.rows if r['doc_id']=='doc-1') for k in ('title','text')},
            'expected_version':next(r['version'] for r in self.demo.rows if r['doc_id']=='doc-1'),'project':''}])

    def hits(self, mode):
        actor = self.f.ids.get(self.f.alice.id)
        return {h['doc_id'] for h in self.f.index.search(self.f.index.scope(actor,'alpha'),'TitanDB',mode=mode)[0]}

    def test_empty_memberships_deny_tagged_but_preserve_untagged_in_every_mode(self):
        self.f.ids.update(self.f.alice.id, projects=[])
        for mode in ('keyword','vector','hybrid'):
            self.assertEqual(self.hits(mode), {'doc-1'})
        self.assertIsNone(self.f.index.open(self.f.index.scope(self.f.ids.get(self.f.alice.id),'alpha'),'doc-0')[0])
        self.f.ids.project_membership(self.f.alice.id,'alpha','alpha:telemetry',True)
        for mode in ('keyword','vector','hybrid'):
            self.assertEqual(self.hits(mode), {'doc-0','doc-1'})
        self.f.ids.project_membership(self.f.alice.id,'alpha','alpha:telemetry',False)
        self.assertEqual(self.hits('hybrid'), {'doc-1'})

    def test_membership_does_not_bypass_source_acl_or_other_restrictions(self):
        self.f.ids.project_membership(self.f.bob.id,'alpha','alpha:telemetry',True)
        scope = self.f.index.scope(self.f.ids.get(self.f.bob.id),'alpha')
        self.assertIsNone(self.f.index.open(scope,'doc-0')[0])
        self.f.ids.project_membership(self.f.alice.id,'alpha','alpha:telemetry',True)
        self.f.ids.restrict(self.f.alice.id,'alpha','source','confluence',True)
        for mode in ('keyword','vector','hybrid'):
            self.assertEqual(self.hits(mode), {'doc-1'})
        self.f.ids.restrict(self.f.alice.id,'alpha','source','confluence',False)
        self.f.ids.update(self.f.alice.id, clearance=0)
        self.assertEqual(self.hits('hybrid'), set())

    def test_admin_catalog_membership_epochs_and_ordinary_employee_denial(self):
        body={'user_id':self.f.alice.id,'corpus':'alpha','action':'project_membership',
              'project':'alpha:telemetry','enabled':True}
        self.assertEqual(self.f.post('/api/admin/permissions',body).status_code,403)
        self.f.login(self.f.admin)
        catalog=self.f.client.get('/api/admin/content-scopes?user_id='+self.f.alice.id).json
        self.assertEqual(catalog[0]['project_catalog'],[{'id':'alpha:telemetry','name':'Telemetry dashboard'}])
        epoch=self.f.ids.get(self.f.alice.id).epoch
        self.assertEqual(self.f.post('/api/admin/permissions',body).status_code,200)
        self.assertEqual(self.f.ids.get(self.f.alice.id).epoch,epoch+1)
        self.assertEqual(self.f.post('/api/admin/permissions',{**body,'project':'alpha:missing'}).status_code,400)
        self.assertEqual(self.f.post('/api/admin/permissions',{**body,'corpus':'beta'}).status_code,400)
        self.assertTrue(self.f.audit.verify().valid)

    def test_project_assignment_is_hash_pinned_and_keeps_body_and_acl(self):
        with connect(self.f.db_path) as db:
            after=[dict(r) for r in db.execute('SELECT * FROM documents')]
        old=next(r for r in self.demo.rows if r['doc_id']=='doc-0')
        new=next(r for r in after if r['doc_id']=='doc-0')
        for field in ('text','content_hash','acl_json'):
            self.assertEqual(old[field],new[field])
        self.assertEqual(plan_project_annotations(self.manifest,after),[])
        broken=copy.deepcopy(self.manifest);broken['projects'][0]['documents'][0]['expected_content_hash']='0'*64
        with self.assertRaises(ValueError):plan_project_annotations(broken,after)
        duplicate=copy.deepcopy(self.manifest);duplicate['projects']*=2
        with self.assertRaises(ValueError):plan_project_annotations(duplicate,after)


class RadarProjectCatalogTests(unittest.TestCase):
    def test_every_fixture_resource_is_tagged_or_explicitly_absent_from_preview(self):
        root = Path(__file__).resolve().parents[2]
        index = json.loads((root/'config/radar-project-permissions.json').read_text())
        fixtures = json.loads((root/'fixtures/radar/manifest.json').read_text())
        self.assertEqual(set(index['cases']), set(fixtures['cases']))
        absent = {
            '01-dashboard-review': {'PR-135'},
            '02-kafka-incident': {'PR-109'},
            '03-customer-incident': {'PR-139', 'ZD-101'},
            '04-recurrence-revision': {'PR-159'},
        }
        assigned = set()
        catalog = {}
        for case, mapping in index['cases'].items():
            with self.subTest(case=case):
                manifest = json.loads((root/mapping['annotation_manifest']).read_text())
                self.assertEqual(manifest['authority'], 'team_decision')
                self.assertEqual(manifest['corpus'], 'orgforge')
                self.assertLessEqual(sum(len(p['documents']) for p in manifest['projects']), 50)
                for project in manifest['projects']:
                    catalog[project['id']] = project
                project = next(p for p in manifest['projects'] if p['id']==mapping['project'])
                entries = project['documents']
                ids = {e['doc_id'] for e in entries}
                fixture_ids = {json.loads(line)['resource_id'] for line in
                    (root/'fixtures/radar'/fixtures['cases'][case]['file']).read_text().splitlines()}
                exceptions = {e['doc_id'] for e in mapping['unavailable_resources']}
                self.assertEqual(exceptions, absent[case])
                self.assertTrue(all(e['reason']=='not_in_preview_corpus' for e in mapping['unavailable_resources']))
                self.assertEqual(ids | exceptions, fixture_ids)
                self.assertFalse(ids & exceptions)
                self.assertFalse(ids & assigned)
                self.assertEqual(len(ids), len(entries))
                for entry in entries:
                    self.assertRegex(entry['expected_content_hash'], r'^[0-9a-f]{64}$')
                assigned.update(ids)
        self.assertEqual(len(assigned), 65)
        self.assertEqual(len(catalog), 9)

    def test_incremental_fixture_manifests_preserve_membership_configuration(self):
        root = Path(__file__).resolve().parents[2]
        index = json.loads((root/'config/radar-project-permissions.json').read_text())
        for case, mapping in index['cases'].items():
            if case=='01-dashboard-review':
                continue
            manifest = json.loads((root/mapping['annotation_manifest']).read_text())
            # Reapplying these additions must not restore an administrator's old grants.
            self.assertFalse(manifest.get('initial_memberships'))
            self.assertEqual(len(manifest['projects']), 1)


if __name__=='__main__':unittest.main()
