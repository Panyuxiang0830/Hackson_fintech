import json
import os
import unittest
from unittest.mock import patch
from contextledger.radar.protocol import identifiers, validate_arguments
from contextledger.radar.tool import source_guidance, partition_claims
from contextledger.answering.service import AnswerService
from contextledger.answering.models import Document, Evidence, User
from tests.answering.test_llm_workflows import completion


class RadarProtocolTests(unittest.TestCase):
    def test_whole_identifier_unicode_and_no_prefix_collision(self):
        self.assertEqual(identifiers('ENG‑123 ENG-123 ENG-1234 xENG-12 ENG-12abc PM‑CONF‑078 PR-109'),
                         ['ENG-123','ENG-1234','PM-CONF-078','PR-109'])

    def test_multi_native_ids_seed_separate_documents_without_substitution(self):
        from contextledger.retrieval.search import contains_query_entities
        self.assertTrue(contains_query_entities('ENG-123 only',['ENG-123','PR-109']))
        self.assertFalse(contains_query_entities('ENG-1234 only',['ENG-123','PR-109']))
        self.assertFalse(contains_query_entities('otherProject ENG-123',['TitanDB','ENG-123','PR-109']))

    def test_anchors_and_server_owned_parameters(self):
        for value in ({'anchor_ids':['ENG-999']},{'actor':'admin'},{'focus':['sql']},{'anchor_ids':[True]}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_arguments(value, {'ENG-123'})
        self.assertEqual(validate_arguments({'anchor_ids':['ENG-123'],'focus':['history']},{'ENG-123'})['anchor_ids'],['ENG-123'])

    def test_merged_code_and_done_ticket_do_not_prove_recovery(self):
        for source, fact in [('github','code_merge_status'),('jira','ticket_recorded_status')]:
            hit={'source':source,'metadata':{'record_type':'native_state','native_status':'merged'}}
            guidance=source_guidance(hit)
            self.assertEqual(guidance['supported_fact'],fact)
            self.assertIn('production_rollback',guidance['does_not_establish'])
            hit['metadata']['historical_revision']=True
            self.assertIsNone(source_guidance(hit)['supported_fact'])
        self.assertEqual(source_guidance({'source':'slack','metadata':{}})['assessment'],'source_reported')

    def test_partition_change_uses_new_value_and_preserves_quote(self):
        self.assertEqual(partition_claims('changed partition count from 12 to 24')[0]['value'],24)
        self.assertEqual(partition_claims('expected 8 partitions')[0]['value'],8)
        self.assertEqual(partition_claims('no count was specified'),[])
        self.assertEqual(partition_claims('timeout on partition 7; test partition 3'),[])
        self.assertEqual(partition_claims('correct partition count (8)')[0]['value'],8)


class RadarAnswerTests(unittest.TestCase):
    def setUp(self):
        self.user=User('u','U','eng','engineer','internal')
        self.evidence=[Evidence(Document('ENG-123','jira','Incident','ENG-123 incident','eng','t','t','t','internal'),1.,'acl','snapshot','unknown')]
        self.env=patch.dict(os.environ,{'LLM_API_KEY':'fixture-key','LLM_PROVIDER':'openai_compatible'})
        self.env.start();self.addCleanup(self.env.stop)
        self.answerer=AnswerService()
        self.call={'action':'call_tool','tool_name':'decision_radar','arguments':{'anchor_ids':['ENG-123'],'focus':['history']}}
        self.good={'status':'answered','answer':'工单记录 [1]。恢复验证尚待确认。','citation_ids':[1],'uncertainty':'medium'}
        self.radar_good=self.good|{'radar_presentation':{
            'status':'pending_confirmation','headline':'恢复仍待确认',
            'explanation':'工单记录可见，但恢复验证仍待确认。','citation_ids':[1],
            'needs_confirmation':[{'item':'核对运行恢复依据。','citation_ids':[1]}]}}

    def test_provider_paragraph_escape_normalization_preserves_citations(self):
        from contextledger.answering.service import _validate_model_output
        text='陈述' * 110 + ' [1]。' + '\\n\\n' + '缺口尚待确认。'
        raw=json.dumps({'status':'answered','answer':text,'citation_ids':[1],'uncertainty':'medium'})
        answer,_=_validate_model_output(raw,1)
        self.assertIn('\n\n',answer)
        malformed=raw.replace('\\\\n\\\\n','\n\n')
        answer,_=_validate_model_output(malformed,1)
        self.assertIn('\n\n',answer)

    def test_direct_answer_does_not_execute_tool(self):
        def handler(_): raise AssertionError('unneeded tool')
        with patch('urllib.request.urlopen',return_value=completion(self.good)) as transport:
            result=self.answerer.answer(self.user,'ENG-123',self.evidence,tool_handler=handler)
        self.assertEqual(result[1],'answered');self.assertEqual(transport.call_count,1)

    def test_single_tool_action_followed_by_answer_and_guard(self):
        calls=[]
        def handler(arguments): calls.append(arguments);return {'coverage':{'documents':1}}
        with patch('urllib.request.urlopen',side_effect=[completion(self.call),completion(self.radar_good)]) as transport:
            answer=self.answerer.answer(self.user,'ENG-123',self.evidence,tool_handler=handler,before_call=lambda:calls.append('guard'))
        self.assertEqual(answer[1],'answered')
        self.assertEqual(sum(isinstance(c,dict) for c in calls),1)
        final=json.loads(json.loads(transport.call_args_list[1].args[0].data)['messages'][1]['content'])
        self.assertIn('decision_radar_result',final)

    def test_tool_answer_without_presentation_stays_safe_after_format_retry(self):
        calls=[]
        with patch('urllib.request.urlopen',side_effect=[completion(self.call),
                completion(self.good),completion(self.good)]) as transport:
            result=self.answerer.answer(self.user,'ENG-123',self.evidence,
                tool_handler=lambda arguments:calls.append(arguments) or {'coverage':{'documents':1}})
        self.assertEqual(result[1: ],('insufficient','mock_fallback'))
        self.assertEqual(len(calls),1)
        self.assertEqual(transport.call_count,3)
        self.assertEqual(self.answerer.last_diagnostics['failures'],['invalid_output','invalid_output'])
        self.assertNotIn(self.good['answer'],result[0])

    def test_repeated_call_across_retry_cannot_execute_twice(self):
        calls=[]
        with patch('urllib.request.urlopen',return_value=completion(self.call)) as transport:
            answer=self.answerer.answer(self.user,'ENG-123',self.evidence,tool_handler=lambda a:calls.append(a) or {})
        self.assertEqual(len(calls),1)
        self.assertEqual(transport.call_count,3)
        self.assertEqual(answer[1],'insufficient')

    def test_network_failure_after_tool_is_safe(self):
        import urllib.error
        with patch('urllib.request.urlopen',side_effect=[completion(self.call),urllib.error.URLError('private-key')]):
            result=self.answerer.answer(self.user,'ENG-123',self.evidence,tool_handler=lambda a:{})
        self.assertEqual(result[2],'mock_fallback')
        self.assertNotIn('private-key',str(self.answerer.last_diagnostics))

    def test_large_registry_keeps_ids_but_bounds_model_payload(self):
        def handler(arguments):
            self.evidence[:] = [Evidence(Document(str(i),'jira','Topic ' + str(i),'x' * 4000,
                'eng','t','t','t','internal'),1.,'acl','snapshot','unknown') for i in range(120)]
            return {'coverage':{'documents':120}}
        with patch('urllib.request.urlopen',side_effect=[completion(self.call),completion(self.radar_good)]) as transport:
            result = self.answerer.answer(self.user,'ENG-123',self.evidence,tool_handler=handler)
        self.assertEqual(result[1],'answered')
        final=json.loads(json.loads(transport.call_args_list[1].args[0].data)['messages'][1]['content'])
        self.assertLess(len(json.dumps(final,ensure_ascii=False)),60000)
        self.assertEqual(len(final['authorised_evidence']),120)
        self.assertTrue(final['decision_radar_result']['coverage']['model_input_truncated'])
