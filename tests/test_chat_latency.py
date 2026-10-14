"""Latency comparisons retain failures and keep workloads separate."""
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock, patch

import requests

from scripts.evaluate_chat import score
from scripts.evaluate_chat_latency import (summarize, measured_question, ReadOnlyQdrant,
                                           validate_frozen_snapshot, frozen_application)


class ChatLatencyTests(unittest.TestCase):
    def row(self, case, profile, latency, passed=True, calls=1, docs=1, failures=None):
        return {'case': {'id': case}, 'profile': profile, 'latency_ms': latency,
                'passed': passed, 'result': {'evidence': [{}] * docs,
                    'llm_diagnostics': {'model_calls': calls, 'failures': failures or []}}}

    def test_failed_requests_remain_in_denominator_and_latency(self):
        rows = [self.row('same', 'baseline', 100),
                self.row('same', 'baseline', 900, False, failures=['api_unavailable'])]
        result = summarize(rows)[0]
        self.assertEqual((result['observations'], result['passed']), (2, 1))
        self.assertEqual(result['median_ms'], 500)
        self.assertEqual(result['range_ms'], [100, 900])
        self.assertEqual(result['failures'], [[], ['api_unavailable']])

    def test_case_and_profile_are_not_averaged_together(self):
        rows = [self.row('simple', 'baseline', 100), self.row('complex', 'baseline', 5000),
                self.row('simple', 'candidate', 200)]
        groups = {(r['case'], r['profile']): r for r in summarize(rows)}
        self.assertEqual(len(groups), 3)
        self.assertEqual(groups['simple', 'baseline']['median_ms'], 100)
        self.assertEqual(groups['complex', 'baseline']['median_ms'], 5000)

    def test_refusal_and_tool_call_counts_are_not_lost(self):
        groups = summarize([self.row('negative', 'baseline', 10, calls=0, docs=0),
                            self.row('complex', 'baseline', 5000, calls=2, docs=16)])
        self.assertEqual(groups[0]['model_calls'], [0])
        self.assertEqual(groups[0]['documents'], [0])
        self.assertEqual(groups[1]['model_calls'], [2])
        self.assertEqual(groups[1]['documents'], [16])

    def test_transport_failures_are_observations_and_next_request_can_run(self):
        case = {'id': 'negative', 'question': 'Unknown', 'gold': [], 'decision': 'insufficient'}
        state = {'trace': [], 'retrieval': [], 'radar': []}
        session = Mock()
        safe = {'decision': 'insufficient', 'evidence': [], 'answer': 'Insufficient',
                'llm_diagnostics': {'attempts': 0, 'model_calls': 0}}
        response = Mock(status_code=200)
        response.json.return_value = safe
        session.post.side_effect = [requests.Timeout('private-do-not-log'),
                                   requests.ConnectionError('private-do-not-log'), response]
        rows = []
        for repeat in range(3):
            with patch('scripts.evaluate_chat_latency.time.perf_counter', side_effect=[1., 2.]):
                result, status, elapsed = measured_question(session, 'http://loopback', {}, case, 'fixture', state)
            rows.append({'case': case, 'profile': 'baseline', 'latency_ms': elapsed,
                         'result': result, **score(case, result, status, {})})
        summary = summarize(rows)[0]
        self.assertEqual((summary['observations'], summary['passed']), (3, 1))
        self.assertEqual(summary['failures'][:2], [['http_timeout'], ['http_connection_failed']])
        self.assertNotIn('private-do-not-log', json.dumps(rows))
        self.assertEqual(summary['median_ms'], 1000.)

    def test_invalid_http_json_and_server_errors_are_retained(self):
        case = {'id': 'negative', 'question': 'Unknown', 'gold': [], 'decision': 'insufficient'}
        state = {'trace': [{'stage': 'route_or_direct'}]}
        for status, value in [(200, ValueError('raw-secret-response')), (200, []),
                              (503, {'error': 'unavailable'})]:
            with self.subTest(status=status, value=value):
                response = Mock(status_code=status)
                if isinstance(value, Exception):
                    response.json.side_effect = value
                else:
                    response.json.return_value = value
                result, code, elapsed = measured_question(Mock(post=Mock(return_value=response)),
                    'http://loopback', {}, case, 'fixture', state)
                self.assertEqual(code, status)
                self.assertGreaterEqual(elapsed, 0)
                self.assertFalse(score(case, result, code, {})['passed'])
                self.assertTrue(result['llm_diagnostics']['failures'])
                self.assertNotIn('raw-secret-response', json.dumps(result))

    def test_pending_or_unpublished_snapshot_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'canonical.sqlite'
            with sqlite3.connect(path) as db:
                db.execute('CREATE TABLE cl_index_state (id INTEGER,state TEXT)')
                db.execute("INSERT INTO cl_index_state VALUES (1,'ready')")
                db.execute('CREATE TABLE cl_update_jobs (state TEXT)')
            validate_frozen_snapshot(path)
            for state in ['queued', 'running', 'failed']:
                with self.subTest(state=state):
                    with sqlite3.connect(path) as db:
                        db.execute('DELETE FROM cl_update_jobs')
                        db.execute('INSERT INTO cl_update_jobs VALUES (?)', (state,))
                    with self.assertRaises(ValueError):
                        validate_frozen_snapshot(path)
            with sqlite3.connect(path) as db:
                db.execute('DELETE FROM cl_update_jobs')
                db.execute("UPDATE cl_index_state SET state='building'")
            with self.assertRaises(ValueError):
                validate_frozen_snapshot(path)

    def test_vector_client_rejects_mutations(self):
        client = Mock()
        readonly = ReadOnlyQdrant(client)
        readonly.scroll('shared')
        client.scroll.assert_called_once_with('shared')
        for name in ['delete', 'upsert', 'create_collection', 'set_payload', 'delete_collection']:
            with self.subTest(name=name), self.assertRaises(PermissionError):
                getattr(readonly, name)('shared')
        client.delete.assert_not_called()
        client.upsert.assert_not_called()

    def test_read_proxy_works_with_native_qdrant_engine(self):
        from qdrant_client import QdrantClient, models as qm
        client = QdrantClient(':memory:')
        self.addCleanup(client.close)
        client.create_collection('shared', vectors_config=qm.VectorParams(size=2, distance=qm.Distance.COSINE))
        client.upsert('shared', [qm.PointStruct(id=1, vector=[1., 0.], payload={'doc_id': 'fixture'})])
        readonly = ReadOnlyQdrant(client)
        self.assertEqual(readonly.count('shared', exact=True).count, 1)
        points = readonly.query_points('shared', query=[1., 0.], with_payload=True).points
        self.assertEqual(points[0].payload['doc_id'], 'fixture')
        with self.assertRaises(PermissionError):
            readonly.delete_collection('shared')
        self.assertEqual(client.count('shared', exact=True).count, 1)

    def test_frozen_application_disables_worker_and_admin_writes(self):
        from flask import Flask
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / 'content/canonical.sqlite'
            path.parent.mkdir()
            with sqlite3.connect(path) as db:
                db.execute('CREATE TABLE cl_index_state (id INTEGER,state TEXT)')
                db.execute("INSERT INTO cl_index_state VALUES (1,'ready')")
            index = Mock(db_path=path)
            updates = Mock()
            app = Flask(__name__)
            @app.post('/api/admin/documents')
            def mutate():
                self.fail('Management route must never execute in the benchmark')
            with patch('contextledger.filtered_index.FilteredIndex', return_value=index) as factory, \
                    patch('contextledger.document_updates.DocumentUpdates', return_value=updates) as worker, \
                    patch('contextledger.web.create_app', return_value=app):
                actual = frozen_application(path, root / 'security', 'http://127.0.0.1:17864', client=Mock())
            self.assertIs(actual, app)
            self.assertIsInstance(factory.call_args.args[1], ReadOnlyQdrant)
            self.assertFalse(worker.call_args.kwargs['autostart'])
            updates.start.assert_not_called()
            self.assertEqual(actual.test_client().post('/api/admin/documents').status_code, 403)


if __name__ == '__main__':
    unittest.main()
