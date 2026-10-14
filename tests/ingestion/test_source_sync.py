"""Real queue/SQLite/local-Qdrant orchestration; no live platform or LLM calls."""
from dataclasses import replace
import json
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from contextledger.application.service import PermissionChanged
from contextledger.ingestion.source_adapters import NativeDocument, SourceError
from contextledger.ingestion.source_sync import SourceSync
from contextledger.retrieval.filtered_index import IndexUnavailable
from contextledger.storage.document_updates import DocumentUpdates
from contextledger.storage.models import Chunk
from contextledger.storage.store import connect
from tests.application import test_integration as integration_fixture


class SourceSyncTests(unittest.TestCase):
    def setUp(self):
        self.fixture = integration_fixture.IntegrationTests('test_chinese_adjoining_entity_is_tokenised_and_authorised')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.service, self.ids, self.index = self.fixture.service, self.fixture.ids, self.fixture.index
        self.actor, self.admin = self.fixture.alice, self.fixture.admin
        self.ids.bind(self.actor.id, 'beta', 'beta:a', True)
        self.updates = DocumentUpdates(self.index, self.ids, self.fixture.audit,
            embed=lambda texts: [[1., 0.] for _ in texts],
            chunker=lambda doc: [Chunk('temporary', doc.corpus, doc.doc_id, 0, doc.text)], autostart=False)
        self.addCleanup(self.updates.close)
        self.syncer = SourceSync(self.service, self.updates, self.fixture.security / 'source-raw.sqlite')

    @staticmethod
    def config(source='jira'):
        return {'source': source, 'corpus': 'alpha', 'enabled': True, 'acl_ttl_seconds': 300}

    @staticmethod
    def document(resource='one', **changes):
        return replace(NativeDocument(resource, 'TitanDB ENG-101 live reference',
            'TitanDB ENG-101 live fact.', 'https://source.example/resource', 'r1', None,
            ['alpha:a'], 'verified_subset', 'verified fixture source permission', {}), **changes)

    @staticmethod
    def reader(documents=(), hook=lambda: None):
        def records():
            hook()
            yield from documents
        return SimpleNamespace(mapping={'native-a': 'alpha:a'}, records=records)

    def drain(self, actor, job_id, timeout):
        # Drive the real worker synchronously, retaining its three-attempt budget.
        for _ in range(3):
            self.updates.process_one()
            status = self.updates.status(actor, job_id)
            if status['state'] == 'ready':
                return status
            with connect(self.index.db_path) as db:
                db.execute('UPDATE cl_update_jobs SET retry_at=0 WHERE id=?', (job_id,))
        return status

    def sync(self, docs=(), source='jira', hook=lambda: None):
        with patch.object(self.updates, 'start'), patch.object(self.updates, 'wait', side_effect=self.drain):
            return self.syncer.sync(self.admin.id, self.config(source), adapter=self.reader(docs, hook))

    def visible(self, corpus='alpha', mode='keyword'):
        result, _ = self.service.search(self.actor.id, corpus, 'TitanDB', mode, planning=False)
        return {hit['doc_id'] for hit in result['hits']}

    def assert_static(self):
        for mode in ('keyword', 'vector', 'hybrid'):
            self.assertTrue({'doc-0', 'doc-1'} <= self.visible(mode=mode))
            self.assertEqual(self.visible('beta', mode), {'doc-3'})
        self.assertTrue(self.service.open(self.actor.id, 'alpha', 'doc-0')[0]['available'])

    def test_each_source_refresh_failure_and_expiry_only_excludes_its_live_docs(self):
        sources = ('jira', 'confluence', 'slack', 'google_drive')
        for source in sources:
            self.sync([self.document(source)], source)
        for source in sources:
            for state, expiry in (('refreshing', 0), ('blocked', 0), ('ready', time.time()-1)):
                with self.subTest(source=source, state=state):
                    self.syncer.gate('alpha', source, state, expiry)
                    expected = {'doc-0', 'doc-1'} | {f'live:{s}:{s}' for s in sources if s != source}
                    for mode in ('keyword', 'vector', 'hybrid'):
                        self.assertEqual(self.visible(mode=mode), expected)
                    self.assertEqual(self.service.open(self.actor.id, 'alpha', f'live:{source}:{source}')[0], {'available': False})
                    self.assert_static()
                    self.syncer.gate('alpha', source, 'ready', time.time()+300)

    def test_actual_failed_enumeration_quarantine_and_missing_resource(self):
        first = self.sync([self.document()])
        self.assertEqual(first['submitted'], 1)
        self.assertIn('live:jira:one', self.visible())
        def fail():
            self.assertEqual(self.visible(), {'doc-0', 'doc-1'})
            raise SourceError('upstream_failure')
        with self.assertRaises(SourceError):
            self.sync(hook=fail)
        self.assert_static()
        self.assertNotIn('live:jira:one', self.visible())
        result = self.sync([self.document(permission_state='unknown')])
        self.assertEqual(result['quarantined'], 1)
        self.assertFalse(self.service.open(self.actor.id, 'alpha', 'live:jira:one')[0]['available'])
        self.sync([self.document()])
        self.sync([])
        self.assertFalse(self.service.open(self.actor.id, 'alpha', 'live:jira:one')[0]['available'])
        with connect(self.index.db_path) as db:
            self.assertEqual(json.loads(db.execute("SELECT acl_json FROM documents WHERE doc_id='live:jira:one'").fetchone()[0]), [])
        self.assertTrue(self.fixture.audit.verify().valid)

    def test_blocked_docs_never_enter_vector_candidates_even_for_legacy_payloads(self):
        self.sync([self.document()])
        with connect(self.index.db_path) as db:
            collection = self.index.state(db)['collection']
        points, _ = self.fixture.qdrant.scroll(collection, limit=100)
        for point in points:
            self.fixture.qdrant.delete_payload(collection, keys=['live_source'], points=[point.id], wait=True)
        self.syncer.gate('alpha', 'jira', 'blocked')
        original = self.fixture.qdrant.query_points
        observed = []
        def inspect(*args, **kwargs):
            response = original(*args, **kwargs)
            ids = {point.payload['doc_id'] for point in response.points}
            self.assertNotIn('live:jira:one', ids)
            observed.append(ids)
            return response
        with patch.object(self.fixture.qdrant, 'query_points', side_effect=inspect):
            self.assertEqual(self.visible(mode='vector'), {'doc-0', 'doc-1'})
        self.assertTrue(observed)

    def test_source_publication_does_not_lock_static_or_other_valid_source(self):
        self.sync([self.document('slack')], 'slack')
        def embedding(texts):
            for mode in ('keyword', 'vector', 'hybrid'):
                self.assertEqual(self.visible(mode=mode), {'doc-0', 'doc-1', 'live:slack:slack'})
            self.assert_static()
            self.assertFalse(self.service.open(self.actor.id, 'alpha', 'live:jira:one')[0]['available'])
            return [[1., 0.] for _ in texts]
        with patch.object(self.updates, 'embed', side_effect=embedding) as embed:
            self.assertEqual(self.sync([self.document()])['state'], 'ready')
            self.assertEqual(embed.call_count, 1)
        self.assertIn('live:jira:one', self.visible(mode='hybrid'))

    def test_partial_vector_failure_restart_and_retry_remain_resource_scoped(self):
        with patch.object(self.fixture.qdrant, 'upsert', side_effect=RuntimeError('offline')):
            with self.assertRaises(SourceError):
                self.sync([self.document()])
        self.assert_static()
        # Other sources can publish even while the failed resource has no vectors.
        self.assertEqual(self.sync([self.document('slack')], 'slack')['state'], 'ready')
        self.assertIn('live:slack:slack', self.visible(mode='vector'))
        replacement = DocumentUpdates(self.index, self.ids, self.fixture.audit,
            embed=self.updates.embed, chunker=self.updates.chunker, autostart=False)
        self.addCleanup(replacement.close)
        with connect(self.index.db_path) as db:
            job = db.execute("SELECT id FROM cl_update_jobs WHERE doc_id='live:jira:one' AND state='failed'").fetchone()[0]
        replacement.retry(self.admin.id, job)
        self.assertTrue(replacement.process_one())
        self.assertEqual(replacement.status(self.admin.id, job)['state'], 'ready')
        self.assertNotIn('live:jira:one', self.visible())  # Failed source still closed.
        self.sync([self.document()])
        self.assertIn('live:jira:one', self.visible())

    def test_stale_scope_rechecks_gate_and_radar_and_suggestions_are_filtered(self):
        self.sync([self.document(title='TitanSecretDB ENG-101 live reference', text='TitanSecretDB ENG-101 live fact.')])
        scope = self.index.scope(self.ids.get(self.actor.id), 'alpha')
        self.syncer.gate('alpha', 'jira', 'blocked')
        for mode in ('keyword', 'vector', 'hybrid'):
            hits, _ = self.index.search(scope, 'TitanSecretDB', mode)
            self.assertEqual(hits, [])
        self.assertIsNone(self.index.open(scope, 'live:jira:one')[0])
        self.assertEqual(self.index.related(scope, ['ENG-101'])[0], [])
        self.assertEqual(self.index.suggestions(scope, 'TitanSecretD'), [])

    def test_gate_change_before_model_and_during_model_blocks_old_evidence(self):
        self.sync([self.document()])
        self.service.answer.provider = 'openai_compatible'
        original = self.service.retrieve
        def close_after_retrieval(*args, **kwargs):
            result = original(*args, **kwargs)
            self.syncer.gate('alpha', 'jira', 'blocked')
            return result
        with patch.object(self.service, 'retrieve', side_effect=close_after_retrieval), patch.object(self.service.answer, '_openai_compatible') as model:
            with self.assertRaises(PermissionChanged):
                self.service.ask(self.actor.id, 'alpha', 'TitanDB', 'keyword', planning=False)
            model.assert_not_called()
        self.syncer.gate('alpha', 'jira', 'ready', time.time()+300)
        def close_during_model(*args, **kwargs):
            self.syncer.gate('alpha', 'jira', 'blocked')
            return 'TitanDB live fact [1].', 'answered'
        with patch.object(self.service.answer, '_openai_compatible', side_effect=close_during_model):
            with self.assertRaises(PermissionChanged):
                self.service.ask(self.actor.id, 'alpha', 'TitanDB', 'keyword', planning=False)
        self.assert_static()

    def test_missing_gate_blocks_live_not_static_and_rebuild_gate_is_not_bypassed(self):
        self.sync([self.document()])
        with self.ids.db() as db:
            db.execute("DELETE FROM live_source_guards WHERE corpus='alpha' AND source='jira'")
        self.assertEqual(self.visible(), {'doc-0', 'doc-1'})
        with connect(self.index.db_path) as db:
            db.execute("UPDATE cl_index_state SET state='building'")
        with self.assertRaises(IndexUnavailable):
            self.visible()
        self.syncer.gate('alpha', 'jira', 'refreshing')
        with self.assertRaises(IndexUnavailable):
            self.updates.submit(self.admin.id, {'corpus': 'alpha', 'source': 'jira', 'doc_id': 'live:jira:two',
                'title': 'TitanDB', 'text': 'TitanDB fact', 'expected_version': None, 'acl': ['alpha:a']}, source_refresh=True)

    def test_scoped_queue_flag_cannot_be_supplied_by_http_or_for_static_resource(self):
        self.fixture.login(self.admin)
        response = self.fixture.post('/api/admin/documents', {'corpus': 'alpha', 'source_scope': 'jira',
            'doc_id': 'live:jira:two', 'title': 'TitanDB', 'text': 'TitanDB fact', 'source': 'jira',
            'acl': ['alpha:a'], 'expected_version': None})
        self.assertEqual(response.status_code, 400)
        self.syncer.gate('alpha', 'jira', 'refreshing')
        with self.assertRaises(ValueError):
            self.updates.submit(self.admin.id, {'corpus': 'alpha', 'source': 'jira', 'doc_id': 'static-new',
                'title': 'TitanDB', 'text': 'TitanDB fact', 'expected_version': None, 'acl': ['alpha:a']}, source_refresh=True)
        with self.assertRaises(PermissionError):
            self.syncer.sync(self.actor.id, self.config(), adapter=self.reader())

    def test_gate_change_after_search_audit_blocks_http_delivery(self):
        self.sync([self.document(title='Sensitive live title')])
        original = self.fixture.audit.append
        def close_after_audit(record):
            event = original(record)
            if record.get('event_type') == 'search':
                self.syncer.gate('alpha', 'jira', 'blocked')
            return event
        with patch.object(self.fixture.audit, 'append', side_effect=close_after_audit):
            response = self.fixture.client.get('/api/search', query_string={'corpus': 'alpha', 'q': 'TitanDB', 'mode': 'keyword', 'planning': 'false'})
        self.assertEqual(response.status_code, 409)
        self.assertNotIn('Sensitive live title', response.get_data(as_text=True))
        self.assertNotIn('live:jira:one', response.get_data(as_text=True))
        self.assert_static()

    def test_source_queue_cannot_legitimise_unrelated_canonical_edits(self):
        self.syncer.gate('alpha', 'jira', 'refreshing')
        job = self.updates.submit(self.admin.id, {'corpus': 'alpha', 'source': 'jira', 'doc_id': 'live:jira:two',
            'title': 'TitanDB', 'text': 'TitanDB fact', 'expected_version': None, 'acl': ['alpha:a']}, source_refresh=True)
        with connect(self.index.db_path) as db:
            db.execute("UPDATE documents SET acl_json='[]' WHERE corpus='alpha' AND doc_id='doc-0'")
        self.updates.process_one()
        self.assertEqual(self.updates.status(self.admin.id, job['id'])['state'], 'failed')
        with self.assertRaises(IndexUnavailable):
            self.visible()
        self.assertEqual(self.visible('beta'), {'doc-3'})

    def test_real_background_worker_keeps_static_queries_available(self):
        # Exercise SourceSync's actual start/wait path, not only synchronous drain.
        def embedding(texts):
            self.assert_static()
            self.assertNotIn('live:jira:one', self.visible())
            return [[1., 0.] for _ in texts]
        with patch.object(self.updates, 'embed', side_effect=embedding):
            result = self.syncer.sync(self.admin.id, self.config(), adapter=self.reader([self.document()]))
        self.assertEqual(result['state'], 'ready')
        self.assertIn('live:jira:one', self.visible())

    def test_pending_resource_stays_filtered_even_if_source_is_marked_ready(self):
        with patch.object(self.fixture.qdrant, 'upsert', side_effect=RuntimeError('offline')):
            with self.assertRaises(SourceError):
                self.sync([self.document()])
        self.syncer.gate('alpha', 'jira', 'ready', time.time()+300)
        for mode in ('keyword', 'vector', 'hybrid'):
            self.assertEqual(self.visible(mode=mode), {'doc-0', 'doc-1'})
        self.assertFalse(self.service.open(self.actor.id, 'alpha', 'live:jira:one')[0]['available'])

    def test_failure_after_resource_commit_does_not_mark_whole_index_failed(self):
        original = self.updates._record
        def fail_ready(actor, event_type, job, **details):
            if event_type == 'document_update_ready':
                raise RuntimeError('post-publication audit unavailable')
            return original(actor, event_type, job, **details)
        with patch.object(self.updates, '_record', side_effect=fail_ready):
            with self.assertRaises(SourceError):
                self.sync([self.document()])
        self.assert_static()
        self.assertNotIn('live:jira:one', self.visible())
        with connect(self.index.db_path) as db:
            self.assertEqual(self.index.state(db)['state'], 'ready')
        with self.assertRaises(SourceError):
            self.sync([self.document()])
        with self.ids.db() as db:
            self.assertEqual(db.execute("SELECT state FROM live_source_guards WHERE corpus='alpha' AND source='jira'").fetchone()[0], 'blocked')
