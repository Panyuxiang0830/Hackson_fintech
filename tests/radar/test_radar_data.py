from contextledger.paths import PROJECT_ROOT
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from contextledger.radar.data import source_documents, load_records, canonical_documents
from contextledger.radar.store import SourceRevisionStore
from contextledger.storage.models import SourceDoc
from contextledger.storage.store import connect, init_db, insert_principals
from contextledger.storage.models import Principal
from contextledger.retrieval.filtered_index import FilteredIndex, IndexUnavailable
from contextledger.access.identity_store import IdentityStore
from qdrant_client import QdrantClient
from contextledger.evaluation.radar_demo import publish

FIXTURES=PROJECT_ROOT/'fixtures/radar'


class RadarDataTests(unittest.TestCase):
    def test_fixture_has_four_real_business_pools_and_no_eval_labels(self):
        manifest=json.loads((FIXTURES/'manifest.json').read_text())
        self.assertEqual(len(manifest['cases']),4)
        for case in manifest['cases'].values():
            rows=load_records(FIXTURES/case['file'])
            self.assertEqual(len(rows),case['business_records'])
            self.assertTrue(any(r['record_kind']=='native_business_record' for r in rows))
            self.assertTrue(source_documents(rows))
        with self.assertRaises(ValueError):
            source_documents([{'facts':[],'payload':{}}])

    def test_actual_postmortems_are_loaded_with_full_business_content(self):
        records=load_records(FIXTURES/'04-recurrence-revision.jsonl')
        docs=source_documents(records)
        native=next(d for d in docs if d.doc_id=='native:CONF-ENG-438')
        self.assertIn('8 partitions',native.text)
        self.assertIn('ENG',native.text)
        self.assertEqual(native.extra['native_resource_id'],'CONF-ENG-438')

    def test_final_state_never_backdated_and_future_description_not_in_early_cut(self):
        record={'record_kind':'native_business_record','source_type':'pr_registry','resource_id':'PR-1',
                'payload':{'created_at':'2026-01-05','description':'future deployed secret','status':'merged',
                           'comments':[{'date':'2026-01-06','text':'review requested'},{'date':'2026-02-20','text':'later accepted'}]}}
        early=source_documents([record],cutoff='2026-01-10',final=False)
        self.assertEqual(len(early),2)
        self.assertNotIn('future deployed secret',str(early))
        self.assertNotIn('later accepted',str(early))
        self.assertFalse(any(d.extra.get('native_status') for d in early))
        final=source_documents([record])
        state=next(d for d in final if d.extra['record_type']=='native_state')
        self.assertIsNone(state.extra['event_time'])

    def test_imported_revisions_are_immutable_and_removed_roots_not_returned(self):
        old=SourceDoc('orgforge','ENG-1','jira','Old','ENG-1 initial',None,None,'eng',[],{})
        store=SourceRevisionStore();store.observe(old,observed_at='t1')
        old.text='ENG-1 changed'
        old.extra['private']='mutation'
        history=store.documents([old])
        self.assertEqual(history[0].text,'ENG-1 initial')
        self.assertNotIn('private',history[0].extra)
        self.assertEqual(store.documents([]),[])

    def test_current_search_excludes_archives_but_tool_can_read_them(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);path=root/'content'/'canonical.sqlite'
            with connect(path) as db:
                init_db(db);insert_principals(db,[Principal('orgforge','radar:engineering','E','engineer','engineering')],{});db.commit()
            ids=IdentityStore(root/'security'/'ids.sqlite');actor=ids.register('https://fixture','e','E');ids.bind(actor.id,'orgforge','radar:engineering',True)
            client=QdrantClient(':memory:');self.addCleanup(client.close)
            old=SourceDoc('orgforge','ENG-1','jira','ENG-1','ENG-1 initial',None,None,'engineering',[],{})
            archive=SourceRevisionStore();archive.observe(old,observed_at='t1');old.text='ENG-1 current'
            publish(path,client,[old]+archive.documents([old]))
            index=FilteredIndex(path,client,ids,embed=lambda _: [1.,0.]);scope=index.scope(ids.get(actor.id),'orgforge')
            hits,_=index.search(scope,'ENG-1',mode='keyword')
            self.assertEqual([h['doc_id'] for h in hits],['ENG-1'])
            expanded,_,_=index.related(scope,['ENG-1'])
            self.assertEqual(len(expanded),2)

    def test_publication_changes_generation_and_failed_vectors_block_reads(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);path=root/'content'/'canonical.sqlite'
            with connect(path) as db:
                init_db(db);insert_principals(db,[Principal('orgforge','radar:engineering','E','engineer','engineering')],{});db.commit()
            ids=IdentityStore(root/'security'/'ids.sqlite');actor=ids.register('https://fixture','e','E');ids.bind(actor.id,'orgforge','radar:engineering',True)
            client=QdrantClient(':memory:');self.addCleanup(client.close)
            doc=SourceDoc('orgforge','ENG-1','jira','ENG-1','ENG-1 initial',None,None,'engineering',[],{})
            one=publish(path,client,[doc]);index=FilteredIndex(path,client,ids,embed=lambda _: [1.,0.]);scope=index.scope(ids.get(actor.id),'orgforge')
            hit,_=index.open(scope,'ENG-1');self.assertIn('initial',hit['full_text'])
            doc.text='ENG-1 revised'
            two=publish(path,client,[doc]);self.assertNotEqual(one,two)
            self.assertIn('revised',index.open(scope,'ENG-1')[0]['full_text'])
            with patch.object(client,'upsert',side_effect=RuntimeError('failed')):
                with self.assertRaises(RuntimeError):publish(path,client,[doc])
            with self.assertRaises(IndexUnavailable):index.open(scope,'ENG-1')
