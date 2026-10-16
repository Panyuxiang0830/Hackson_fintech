"""Radar + PR7 planner integration with real SQLite/Qdrant and simulated LLM."""
import json
import os
import unittest
from unittest.mock import patch
from tests.application import test_integration as fixture
from tests.answering.test_llm_workflows import completion, plan, stage
from contextledger.answering.workflows import QueryPlanner
from contextledger.retrieval.filtered_index import prepare_snapshot
from contextledger.storage.store import connect
from contextledger.answering.service import AnswerService


class RadarIntegrationTests(unittest.TestCase):
    setUp=fixture.IntegrationTests.setUp
    login=fixture.IntegrationTests.login
    post=fixture.IntegrationTests.post

    def configure(self):
        with patch.dict(os.environ,{'LLM_API_KEY':'fixture-key','LLM_PROVIDER':'openai_compatible','LLM_MODEL':'writer'}):
            self.service.answer=AnswerService()
        self.service.planner=QueryPlanner(stage('planner'),True)
        with connect(self.db_path) as db:
            for doc_id, text in [('doc-0','TitanDB ENG-123 incident.'),('doc-1','ENG-123 related PR-109. Native report only.'),('doc-2','ENG-123 hidden PRIVATE canary.')]:
                import hashlib
                digest=hashlib.sha256(text.encode()).hexdigest()
                db.execute('UPDATE documents SET text=?,version=?,content_hash=? WHERE doc_id=?',(text,digest[:12],digest,doc_id))
                db.execute('UPDATE chunks SET text=? WHERE doc_id=?',(text,doc_id))
                db.execute('UPDATE docs_fts SET text=? WHERE doc_id=?',(text,doc_id))
            db.commit();prepare_snapshot(db,'fixture','radar-generation','test-embedding',2);db.execute("UPDATE cl_index_state SET state='ready'");db.commit()
        self.calls=[]

    def transport(self, request, **kwargs):
        body=json.loads(request.data);payload=json.loads(body['messages'][1]['content']);self.calls.append(payload)
        if 'original_query' in payload:
            return completion(plan(payload['original_query'],semantic_queries=[]),'planner')
        if 'decision_radar_result' not in payload:
            return completion({'action':'call_tool','tool_name':'decision_radar','arguments':{'anchor_ids':['ENG-123'],'focus':['history','conflicts']}},'writer')
        return completion({'status':'answered','answer':'工单已有记录 [1]，生产恢复尚缺验证依据。','citation_ids':[1],'uncertainty':'medium',
            'radar_presentation':{'status':'pending_confirmation','headline':'生产恢复仍待确认。',
                'explanation':'现有授权记录未提供正式验证结果 [1]。','citation_ids':[1],
                'needs_confirmation':[{'item':'核实正式监控验证是否通过。','citation_ids':[1]}]}},'writer')

    def ask(self):
        with patch.dict(os.environ,{'LLM_API_KEY':'fixture-key'}), patch('urllib.request.urlopen',side_effect=self.transport):
            return self.post('/api/ask',{'corpus':'alpha','q':'TitanDB ENG-123 history','mode':'keyword'})

    def test_planner_then_optional_tool_then_answer_keep_scope_and_registry(self):
        self.configure();response=self.ask()
        self.assertEqual(response.status_code,200,response.json)
        self.assertEqual(len(self.calls),3)
        self.assertIn('original_query',self.calls[0]);self.assertIn('authorised_evidence',self.calls[1]);self.assertIn('decision_radar_result',self.calls[2])
        self.assertNotIn('PRIVATE',json.dumps(self.calls))
        self.assertNotIn('ENG-999', self.calls[1]['decision_radar_options']['allowed_anchor_ids'])
        self.assertEqual(self.calls[1]['decision_radar_options']['allowed_anchor_ids'], ['ENG-123'])
        self.assertNotIn('doc-2',json.dumps(response.json))
        self.assertTrue(response.json['radar'])
        self.assertEqual([e['citation_id'] for e in response.json['evidence']],list(range(1,len(response.json['evidence'])+1)))
        self.assertEqual(self.audit.query(request_id=response.json['request_id'])[0]['radar_summary']['documents'],2)
        self.assertEqual(response.json['radar_presentation']['status'],'pending_confirmation')
        self.assertEqual(response.json['radar_presentation']['needs_confirmation'][0]['citation_ids'],[1])
        stored=self.audit.query(request_id=response.json['request_id'])[0]
        self.assertEqual(stored['radar_presentation']['headline'],'生产恢复仍待确认。')
        self.login(self.admin)
        audited=self.client.get('/api/audit?request_id='+response.json['request_id']).json['events'][0]
        self.assertFalse(audited['redacted'])
        self.assertEqual(audited['radar_presentation'],stored['radar_presentation'])

    def test_disjoint_native_ids_can_seed_relationship_request(self):
        self.configure()
        scope=self.index.scope(self.ids.get(self.alice.id),'alpha')
        hits,_=self.index.search(scope,'ENG-123、PR-999 的关系',mode='keyword')
        self.assertTrue(hits)
        self.assertFalse(any('PRIVATE' in h['full_text'] for h in hits))

    def test_source_times_and_mismatch_reach_synthesis_without_hidden_records(self):
        self.configure()
        with connect(self.db_path) as db:
            for doc_id, ts in [('doc-0','2026-02-18T09:38:43'),('doc-1','2026-02-17T09:37:07')]:
                db.execute('UPDATE documents SET ts=?,extra_json=? WHERE doc_id=?',
                    (ts,json.dumps({'date':'2026-02-17'}),doc_id))
            db.commit();prepare_snapshot(db,'fixture','radar-times','test-embedding',2)
            db.execute("UPDATE cl_index_state SET state='ready'");db.commit()
        response=self.ask()
        self.assertEqual(response.status_code,200,response.json)
        report=self.calls[-1]['decision_radar_result']
        events=report['event_candidates']
        self.assertEqual([e['source_record_time'] for e in events],
                         ['2026-02-17T09:37:07','2026-02-18T09:38:43'])
        self.assertIsNone(events[1].get('event_time'))
        self.assertEqual(events[1]['time_basis'],'ts')
        self.assertEqual(events[1]['source_time_fields']['date'],'2026-02-17')
        self.assertEqual(events[1]['time_warnings'],['source_date_mismatch'])
        self.assertEqual(report['timeline_order']['groups'],['local_timestamp'])
        self.assertNotIn('PRIVATE',json.dumps(self.calls))

    def test_invalid_radar_summary_falls_back_to_pending_not_confirmed(self):
        self.configure()
        def missing_summary(request, **kwargs):
            body=json.loads(request.data); payload=json.loads(body['messages'][1]['content'])
            self.calls.append(payload)
            if 'original_query' in payload:
                return completion(plan(payload['original_query'],semantic_queries=[]),'planner')
            if 'decision_radar_result' not in payload:
                return completion({'action':'call_tool','tool_name':'decision_radar','arguments':{'anchor_ids':['ENG-123'],'focus':['history','conflicts']}},'writer')
            return completion({'status':'answered','answer':'Recovery is reported [1].','citation_ids':[1],'uncertainty':'low'},'writer')
        self.transport=missing_summary
        response=self.ask()
        self.assertEqual(response.status_code,200,response.json)
        self.assertEqual(response.json['provider'],'mock_fallback')
        self.assertEqual(response.json['radar_presentation']['status'],'pending_confirmation')
        self.assertTrue(response.json['radar_presentation']['needs_confirmation'])

    def test_revocation_during_final_model_discards_everything(self):
        self.configure();original=self.transport
        def revoke(request,**kwargs):
            result=original(request,**kwargs)
            if 'decision_radar_result' in self.calls[-1]:self.ids.restrict(self.alice.id,'alpha','source','*',True)
            return result
        self.transport=revoke;response=self.ask()
        self.assertEqual(response.status_code,409)
        self.assertNotIn('radar',response.json)
        self.assertEqual(next(e for e in self.audit.query() if e['event_type']=='answer_discarded')['decision'],'permission_or_version_changed')

    def test_parent_denial_hides_children_in_open_search_related(self):
        self.configure()
        with connect(self.db_path) as db:
            row=db.execute("SELECT extra_json FROM documents WHERE doc_id='doc-1'").fetchone();meta=json.loads(row[0]);meta['radar_root_doc_id']='doc-0'
            db.execute("UPDATE documents SET extra_json=? WHERE doc_id='doc-1'",(json.dumps(meta),));db.commit()
            prepare_snapshot(db,'fixture','parent-generation','test-embedding',2);db.execute("UPDATE cl_index_state SET state='ready'");db.commit()
        self.ids.restrict(self.alice.id,'alpha','document','doc-0',True)
        scope=self.index.scope(self.ids.get(self.alice.id),'alpha')
        self.assertIsNone(self.index.open(scope,'doc-1')[0])
        self.assertEqual(self.index.related(scope,['ENG-123'])[0],[])
        self.assertEqual(self.index.search(scope,'ENG-123',mode='keyword')[0],[])

    def test_permission_change_inside_tool_prevents_final_model_and_delivery(self):
        self.configure()
        related=self.index.related
        def revoke(*args,**kwargs):
            result=related(*args,**kwargs)
            self.ids.restrict(self.alice.id,'alpha','source','*',True)
            return result
        with patch.object(self.index,'related',side_effect=revoke):
            response=self.ask()
        self.assertEqual(response.status_code,409)
        self.assertEqual(len(self.calls),2)  # Planner + tool selection; no final writer.
        self.assertNotIn('radar',response.json)

    def test_invalid_model_anchor_never_reads_hidden_document(self):
        self.configure()
        def invalid(request,**kwargs):
            body=json.loads(request.data);payload=json.loads(body['messages'][1]['content']);self.calls.append(payload)
            if 'original_query' in payload:return completion(plan(payload['original_query']))
            return completion({'action':'call_tool','tool_name':'decision_radar','arguments':{'anchor_ids':['ENG-999'],'focus':['history']}})
        self.transport=invalid
        with patch.object(self.index,'related',wraps=self.index.related) as expand:
            response=self.ask()
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json['decision'],'insufficient')
        expand.assert_not_called()
        self.assertIsNone(response.json['radar'])
