"""Employee-style name discovery, bounded expansion and security regressions."""
import hashlib
import json
import os
import unittest
from unittest.mock import patch

from tests.application import test_integration as fixture
from contextledger.retrieval.filtered_index import prepare_snapshot
from contextledger.answering.workflows import QueryPlanner
from contextledger.radar.protocol import RadarBudget
from contextledger.radar.resolution import NameSearchPlanner
from contextledger.radar.tool import DecisionRadarTool
from contextledger.storage.store import connect
from contextledger.answering.service import AnswerService
from tests.answering.test_llm_workflows import completion, stage
from tests.answering.test_llm_workflows import plan as workflow_plan


class NamePlanTests(unittest.TestCase):
    def test_translation_can_find_descriptive_terms_without_inventing_ids(self):
        planner = NameSearchPlanner(stage('name-search'))
        raw = {'search_phrases': ['telemetry dashboard review approval'], 'required_names': []}
        with patch('urllib.request.urlopen', return_value=completion(raw)):
            result, diag = planner.plan('遥测仪表盘的评审过程是什么？', lambda: None)
        self.assertEqual(diag['status'], 'planned')
        self.assertIn('telemetry', result['search_phrases'][0])

    def test_fabricated_ids_names_and_substitutions_rejected(self):
        planner = NameSearchPlanner(stage('name-search'))
        for raw in [
            {'search_phrases':['ENG-195 dashboard'], 'required_names':[]},
            {'search_phrases':['OtherDB review'], 'required_names':['OtherDB']},
            {'search_phrases':['OtherDB review'], 'required_names':[]},
            {'search_phrases':['TitanDB review'], 'required_names':['TitanDB'], 'actor':'admin'}]:
            with self.subTest(raw=raw), patch('urllib.request.urlopen', return_value=completion(raw)):
                result, diag = planner.plan('TitanDB 的评审过程', lambda: None)
                self.assertIsNone(result)
                self.assertEqual(diag['status'], 'invalid_name_plan')

    def test_translated_phrase_keeps_literal_user_name_as_required_anchor(self):
        planner=NameSearchPlanner(stage('name-search'))
        with patch('urllib.request.urlopen',return_value=completion({
            'search_phrases':['telemetry dashboard review'], 'required_names':['SwiftUI']})):
            result,diag=planner.plan('SwiftUI 遥测仪表盘评审过程',lambda:None)
        self.assertEqual(diag['status'],'planned')
        self.assertEqual(result['search_phrases'],['SwiftUI telemetry dashboard review'])
        self.assertEqual(result['required_names'],['SwiftUI'])

    def test_invalid_budget_not_silently_unbounded(self):
        for value in ['0','301','unlimited']:
            with patch.dict(os.environ, {'RADAR_MAX_DOCUMENTS':value}), self.assertRaises(ValueError):
                RadarBudget.configured()
        with patch.dict(os.environ, {'RADAR_MAX_DOCUMENTS':'150'}):
            self.assertEqual(RadarBudget.configured().documents,150)


class NameDiscoveryIntegrationTests(unittest.TestCase):
    setUp = fixture.IntegrationTests.setUp
    login = fixture.IntegrationTests.login
    post = fixture.IntegrationTests.post

    def configure(self):
        with patch.dict(os.environ, {'LLM_API_KEY':'fixture-key','LLM_PROVIDER':'openai_compatible','LLM_MODEL':'writer'}):
            self.service.answer = AnswerService()
        self.service.planner = QueryPlanner(enabled=False)
        self.service.name_planner = NameSearchPlanner(stage('name-search'))
        self.calls = []
        with connect(self.db_path) as db:
            for doc_id, text in [('doc-0','SwiftUI telemetry health dashboard ENG-195: development review.'),
                                 ('doc-1','ENG-195 PR-135 approval: MainActor changes requested.'),
                                 ('doc-2','SwiftUI telemetry health dashboard ENG-999: PRIVATE canary.')]:
                digest = hashlib.sha256(text.encode()).hexdigest()
                db.execute('UPDATE documents SET text=?,version=?,content_hash=? WHERE doc_id=?',(text,digest[:12],digest,doc_id))
                db.execute('UPDATE chunks SET text=? WHERE doc_id=?',(text,doc_id))
                db.execute('UPDATE docs_fts SET text=? WHERE doc_id=?',(text,doc_id))
                family = 'ENG-999' if doc_id == 'doc-2' else 'ENG-195'
                db.execute('UPDATE documents SET title=? WHERE doc_id=?',(family + ' · SwiftUI dashboard',doc_id))
            db.commit()
            prepare_snapshot(db,'fixture','name-generation','test-embedding',2)
            db.execute("UPDATE cl_index_state SET state='ready'");db.commit()

    def transport(self, request, **kwargs):
        payload = json.loads(json.loads(request.data)['messages'][1]['content'])
        self.calls.append(payload)
        if 'name_search_question' in payload:
            return completion({'search_phrases':['telemetry dashboard review'], 'required_names':[]})
        if 'decision_radar_result' not in payload:
            return completion({'action':'call_tool','tool_name':'decision_radar','arguments':{'anchor_ids':['ENG-195'],'focus':['history']}})
        return completion({'status':'answered','answer':'评审过程涉及主线程整改 [2]。','citation_ids':[2],'uncertainty':'medium',
            'radar_presentation':{'status':'pending_confirmation','headline':'主线程整改已有评审记录',
                'explanation':'评审要求可核对，整改完成状态仍需后续记录。','citation_ids':[2],
                'needs_confirmation':[{'item':'核对整改完成与批准记录。','citation_ids':[2]}]}})

    def ask(self):
        with patch.dict(os.environ, {'LLM_API_KEY':'fixture-key'}), patch('urllib.request.urlopen', side_effect=self.transport):
            return self.post('/api/ask', {'corpus':'alpha','q':'遥测健康仪表盘的评审过程是什么？','mode':'keyword'})

    def test_no_id_question_discovers_source_id_and_expands_behind_acl(self):
        self.configure()
        response = self.ask()
        self.assertEqual(response.status_code,200,response.json)
        self.assertEqual(response.json['decision'],'answered')
        self.assertEqual(response.json['radar']['entity_candidates'],['ENG-195'])
        self.assertEqual({e['doc_id'] for e in response.json['evidence']},{'doc-0','doc-1'})
        self.assertNotIn('PRIVATE',json.dumps(self.calls))
        self.assertNotIn('ENG-999',json.dumps(response.json))
        self.assertEqual(self.calls[1]['original_question'],'遥测健康仪表盘的评审过程是什么？')

    def test_unknown_explicit_name_keeps_no_correction_or_model_call(self):
        self.configure()
        with patch('urllib.request.urlopen') as call:
            result,_ = self.service.ask(self.alice.id,'alpha','UnknownDB 的历史是什么？',mode='keyword')
        call.assert_not_called()
        self.assertEqual(result['decision'],'insufficient')

    def test_revocation_during_name_stage_discards_before_writer(self):
        self.configure()
        original = self.transport
        def revoke(request, **kwargs):
            result = original(request, **kwargs)
            self.ids.restrict(self.alice.id,'alpha','source','*',True)
            return result
        self.transport = revoke
        response = self.ask()
        self.assertEqual(response.status_code,409)
        self.assertEqual(len(self.calls),1)
        self.assertNotIn('radar',response.json)

    def test_same_feature_name_keeps_distinct_incidents_as_candidates(self):
        self.configure()
        with connect(self.db_path) as db:
            text='SwiftUI telemetry health dashboard ENG-321: separate accessibility incident.'
            digest=hashlib.sha256(text.encode()).hexdigest()
            db.execute('UPDATE documents SET text=?,version=?,content_hash=? WHERE doc_id=?',(text,digest[:12],digest,'doc-1'))
            db.execute('UPDATE chunks SET text=? WHERE doc_id=?',(text,'doc-1'))
            db.execute('UPDATE docs_fts SET text=? WHERE doc_id=?',(text,'doc-1'))
            db.execute('UPDATE documents SET title=? WHERE doc_id=?',('ENG-321 · SwiftUI dashboard','doc-1'))
            db.commit();prepare_snapshot(db,'fixture','distinct-generation','test-embedding',2)
            db.execute("UPDATE cl_index_state SET state='ready'");db.commit()
        with patch('urllib.request.urlopen',side_effect=self.transport):
            hits,generation,scope,_=self.service.retrieve(self.ids.get(self.alice.id),'alpha',
                '遥测仪表盘的问题演变',mode='keyword',day=None,resolve_names=True)
        self.assertEqual({h['doc_id'] for h in hits},{'doc-0','doc-1'})
        _, report=DecisionRadarTool(self.index).execute(query='遥测仪表盘的问题演变',scope=scope,
            generation=generation,seeds=hits,arguments={'anchor_ids':['ENG-195','ENG-321']},guard=lambda:None)
        self.assertEqual(report['relations'],[])  # Same feature name is not a causal edge.

    def test_supplied_name_clarification_searches_and_resolves_single_visible_family(self):
        self.configure()
        self.service.planner = QueryPlanner(stage('planner'),True)
        original = self.transport
        def transport(request, **kwargs):
            payload=json.loads(json.loads(request.data)['messages'][1]['content'])
            if 'original_query' in payload:
                return completion(workflow_plan(payload['original_query'],semantic_queries=[],
                    sub_questions=[],keywords=['SwiftUI'],
                    entity_candidates=['SwiftUI'],possible_interpretations=['feature history or generic workflow']))
            return original(request,**kwargs)
        self.transport=transport
        with patch.dict(os.environ,{'LLM_API_KEY':'fixture-key'}), patch('urllib.request.urlopen',side_effect=transport):
            response=self.post('/api/ask',{'corpus':'alpha','q':'SwiftUI 仪表盘评审过程','mode':'keyword'})
        self.assertEqual(response.json['decision'],'answered',response.json)
        self.assertEqual(response.json['query_plan']['status'],'resolved_candidate')
        self.assertFalse(response.json['query_plan']['name_resolution']['global_identity_confirmed'])

    def test_more_than_forty_documents_and_precise_cap_reporting(self):
        self.configure()
        with connect(self.db_path) as db:
            for number in range(65):
                doc_id = f'extra-{number}'
                text = f'ENG-195 independent update {number}'
                digest = hashlib.sha256(text.encode()).hexdigest()
                db.execute("INSERT INTO documents SELECT corpus,?,source,title,?,day,ts,dept,actors_json,acl_json,acl_basis,?,?,extra_json FROM documents WHERE doc_id='doc-0'",
                           (doc_id,text,digest[:12],digest))
                db.execute('INSERT INTO chunks VALUES (?,?,?,?,?)',(doc_id+'-0','alpha',doc_id,0,text))
                db.execute('INSERT INTO docs_fts (corpus,doc_id,title,text) VALUES (?,?,?,?)',('alpha',doc_id,'Update',text))
            db.commit()
            prepare_snapshot(db,'fixture','many-generation','test-embedding',2)
            db.execute("UPDATE cl_index_state SET state='ready'");db.commit()
        scope = self.index.scope(self.ids.get(self.alice.id),'alpha')
        seeds, generation = self.index.search(scope,'ENG-195',mode='keyword',limit=5)
        kwargs = dict(query='ENG-195 history',scope=scope,generation=generation,seeds=seeds,
                      arguments={'anchor_ids':['ENG-195']},guard=lambda:None)
        hits, report = DecisionRadarTool(self.index,budget=RadarBudget(documents=120)).execute(**kwargs)
        self.assertEqual(len(hits),67)
        self.assertNotIn('document_limit',report['coverage']['truncation_reasons'])
        hits, report = DecisionRadarTool(self.index,budget=RadarBudget(documents=50)).execute(**kwargs)
        self.assertEqual(len(hits),50)
        self.assertIn('document_limit',report['coverage']['truncation_reasons'])
