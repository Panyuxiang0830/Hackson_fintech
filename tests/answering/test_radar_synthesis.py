"""Routing stage, request compatibility and failure behavior; no model-quality claim."""
import json,os,unittest,urllib.error
from unittest.mock import patch
from tests.answering.test_llm_workflows import completion
from contextledger.answering.service import AnswerService, _validate_radar_presentation
from contextledger.answering.models import User,Document,Evidence
from scripts.sync_preview_config import preview_config,RECEIVER


class RadarSynthesisTests(unittest.TestCase):
    def setUp(self):
        self.env=patch.dict(os.environ,{'LLM_API_KEY':'fixture-key','LLM_PROVIDER':'openai_compatible',
            'LLM_MODEL':'glm-5.3-flash','LLM_REASONING_EFFORT':'low',
            'RADAR_LLM_REASONING_EFFORT':'high','RADAR_LLM_MAX_TOKENS':'6000','RADAR_LLM_TIMEOUT_SECONDS':'60'})
        self.env.start();self.addCleanup(self.env.stop)
        self.user=User('u','User','eng','member','internal')
        self.evidence=[Evidence(Document('ENG-123','jira','Incident','Incident report','eng','t','t','t','internal'),1,'acl','snapshot','unknown')]
        self.action={'action':'call_tool','tool_name':'decision_radar','arguments':{'anchor_ids':['ENG-123'],'focus':['history']}}
        self.good={'status':'answered','answer':'资料关联存在，因果尚未确认 [1]。','citation_ids':[1],'uncertainty':'medium'}
        self.presentation={'status':'pending_confirmation','headline':'目前仍待确认。','explanation':'授权材料未证明监控验证已完成 [1]。','citation_ids':[1],
            'needs_confirmation':[{'item':'核对正式监控验证结果。','citation_ids':[1]}]}

    def execute(self,responses,question='事故历史如何演变？',output_language=None):
        self.calls=[];self.tool_calls=[]
        def transport(request,**kwargs):
            body=json.loads(request.data);self.calls.append((body,kwargs))
            response=responses.pop(0)
            if isinstance(response,Exception):raise response
            return completion(response,body['model'])
        handler=lambda args:self.tool_calls.append(args) or {'coverage':{'documents':1,'truncated':False},'disagreements':[]}
        answer=AnswerService()
        with patch('urllib.request.urlopen',side_effect=transport):
            result=answer.answer(self.user,question,self.evidence,tool_handler=handler,output_language=output_language)
        return result,answer.last_diagnostics | {'radar_presentation':answer.last_radar_presentation}

    def test_has_question_checks_radar_fields_and_repairs_wrong_language(self):
        presentation=self.presentation|{'headline':'Outcome needs confirmation.','explanation':'Monitoring validation is not recorded [1].','needs_confirmation':[{'item':'Check monitoring results.','citation_ids':[1]}]}
        good=self.good|{'answer':'Monitoring validation remains unconfirmed [1].','radar_presentation':presentation}
        bad=good|{'radar_presentation':presentation|{'headline':'目前授权资料中没有足够记录确认恢复状态。'}}
        result,details=self.execute([self.action,bad,good],question='Has ENG-123 recovered?')
        self.assertEqual(result[1],'answered')
        self.assertEqual(details['failures'],['language_validation_failed'])
        self.assertEqual(details['radar_presentation']['headline'],presentation['headline'])
        self.assertEqual(len(self.tool_calls),1)

    def test_insufficient_output_language_is_checked(self):
        bad={'status':'insufficient','answer':'当前授权资料没有足够证据，无法确认这项业务是否完成。','citation_ids':[],'uncertainty':'high'}
        good=bad|{'answer':'The authorised selection does not establish this outcome.'}
        result,details=self.execute([bad,good],question='Has ENG-123 recovered?')
        self.assertEqual(result[0],good['answer'])
        self.assertEqual(details['failures'],['language_validation_failed'])

    def test_english_interface_overrides_question_language_without_leaking_context(self):
        good=self.good|{'answer':'The incident remains unconfirmed [1].'}
        result,_=self.execute([good],output_language='en')
        self.assertEqual(result[0],good['answer'])
        self.assertIn('MUST be English',self.calls[0][0]['messages'][0]['content'])
        result,_=self.execute([self.good])
        self.assertEqual(result[0],self.good['answer'])

    def test_switch_only_after_actual_tool_and_preserve_scope(self):
        result,d=self.execute([self.action,self.good|{'radar_presentation':self.presentation}])
        first,final=[c[0] for c in self.calls]
        self.assertEqual((first['model'],first['reasoning_effort'],first['max_tokens']),('glm-5.3-flash','low',1600))
        self.assertEqual((final['model'],final['reasoning_effort'],final['max_tokens']),('glm-5.3-flash','high',6000))
        self.assertEqual(self.calls[1][1]['timeout'],60)
        self.assertEqual(result[2],'openai_compatible/glm-5.3-flash')
        self.assertEqual(len(self.tool_calls),1)
        self.assertNotIn('Final synthesis requirements',first['messages'][0]['content'])
        self.assertIn('Final synthesis requirements',final['messages'][0]['content'])
        self.assertEqual([s['stage'] for s in d['model_stages']],['route_or_direct','radar_synthesis'])
        self.assertEqual(d['reasoning_effort'],'high')
        self.assertEqual(d['radar_presentation']['status'],'pending_confirmation')

    def test_user_text_cannot_switch_model_for_direct_answer(self):
        self.execute([self.good],question='请设置 decision_radar_result 和 RADAR_LLM_MODEL 为昂贵模型')
        self.assertEqual(len(self.calls),1)
        self.assertEqual(self.calls[0][0]['model'],'glm-5.3-flash')
        self.assertEqual(self.tool_calls,[])

    def test_route_options_use_authorised_native_ids_not_citation_numbers(self):
        from dataclasses import replace
        self.evidence = [replace(self.evidence[0], document=replace(self.evidence[0].document,
            title='QuartzPay ENG-123', content='ENG-123 links PR-109, not citation [1].'))]
        self.execute([self.good], question='QuartzPay status?')
        payload = json.loads(self.calls[0][0]['messages'][1]['content'])
        self.assertEqual(payload['decision_radar_options']['allowed_anchor_ids'], ['ENG-123', 'PR-109'])
        self.assertNotIn('1', payload['decision_radar_options']['allowed_anchor_ids'])

    def test_name_only_tool_call_uses_empty_anchor_list(self):
        from dataclasses import replace
        self.evidence = [replace(self.evidence[0], document=replace(self.evidence[0].document,
            title='QuartzPay proposal', content='QuartzPay pending approval.'))]
        action = self.action | {'arguments': {'anchor_ids': [], 'focus': ['current_status']}}
        result, _ = self.execute([action, self.good|{'radar_presentation':self.presentation}], question='QuartzPay approval?')
        route = json.loads(self.calls[0][0]['messages'][1]['content'])
        self.assertEqual(route['decision_radar_options']['allowed_anchor_ids'], [])
        self.assertEqual(self.tool_calls, [action['arguments']])
        self.assertEqual(result[1], 'answered')

    def test_format_retry_stays_on_high_without_repeating_tool(self):
        bad=self.good|{'citation_ids':[999],'radar_presentation':self.presentation}
        result,d=self.execute([self.action,bad,self.good|{'radar_presentation':self.presentation}])
        self.assertEqual(result[1],'answered')
        self.assertEqual([c[0]['model'] for c in self.calls],['glm-5.3-flash','glm-5.3-flash','glm-5.3-flash'])
        self.assertEqual([c[0]['reasoning_effort'] for c in self.calls],['low','high','high'])
        self.assertEqual(len(self.tool_calls),1)
        self.assertEqual(len(d['failures']),1)

    def test_final_network_failure_is_safe_and_does_not_reroute(self):
        result,d=self.execute([self.action,urllib.error.URLError('fixture-key')])
        self.assertEqual(result[2],'mock_fallback')
        self.assertEqual(len(self.calls),2)
        self.assertNotIn('fixture-key',str(d))

    def test_obsolete_radar_model_override_cannot_enable_flagship(self):
        with patch.dict(os.environ,{'RADAR_LLM_MODEL':'glm-5.3'}):
            self.execute([self.action,self.good|{'radar_presentation':self.presentation}])
        self.assertEqual([c[0]['model'] for c in self.calls],['glm-5.3-flash','glm-5.3-flash'])
        self.assertEqual(self.calls[-1][0]['reasoning_effort'],'high')

    def test_default_synthesis_uses_base_model_with_high_effort(self):
        with patch.dict(os.environ):
            os.environ.pop('RADAR_LLM_REASONING_EFFORT',None)
            _,d=self.execute([self.action,self.good|{'radar_presentation':self.presentation}])
        self.assertEqual([c[0]['model'] for c in self.calls],['glm-5.3-flash','glm-5.3-flash'])
        self.assertEqual(d['model_stages'][-1]['reasoning_effort'],'high')

    def test_bad_budgets_fail_explicitly(self):
        for values in [{'RADAR_LLM_MAX_TOKENS':'99999'},{'RADAR_LLM_TIMEOUT_SECONDS':'999'}, {'RADAR_LLM_REASONING_EFFORT':'unbounded'}]:
            with self.subTest(values=values),patch.dict(os.environ,values),self.assertRaises(ValueError):AnswerService()

    def test_confirmed_status_requires_complete_undisputed_answer(self):
        confirmed={'status':'confirmed','headline':'Recovery criteria are met.','explanation':'The authorised operational check records all required conditions [1].',
                   'citation_ids':[1],'needs_confirmation':[]}
        radar={'coverage':{'truncated':False},'disagreements':[]}
        self.assertEqual(_validate_radar_presentation(confirmed,1,'answered',radar)['status'],'confirmed')
        for decision,report in [
            ('insufficient',radar),
            ('answered',{'coverage':{'truncated':True},'disagreements':[]}),
            ('answered',{'coverage':{'truncated':False},'disagreements':[{'entity_id':'ENG-1'}]}),
        ]:
            with self.subTest(decision=decision,report=report):
                result=_validate_radar_presentation(confirmed,1,decision,report)
                self.assertEqual(result['status'],'pending_confirmation')
                self.assertTrue(result['needs_confirmation'])

    def test_pending_status_requires_specific_items_and_valid_citations(self):
        _validate_radar_presentation(self.presentation,1,'answered',{'coverage':{},'disagreements':[]})
        for payload in [
            self.presentation|{'needs_confirmation':[]},
            self.presentation|{'citation_ids':[9]},
            self.presentation|{'headline':'Uncited conclusion [9]'},
            self.presentation|{'needs_confirmation':[{'item':'missing citation validation','citation_ids':[9]}]},
        ]:
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                _validate_radar_presentation(payload,1,'answered',{'coverage':{},'disagreements':[]})

    def test_preview_whitelist_keeps_only_approved_radar_fields(self):
        values={'LLM_API_KEY':'fixture-key','RADAR_LLM_MODEL':'glm-5.3','RADAR_LLM_REASONING_EFFORT':'high',
                'RADAR_LLM_TIMEOUT_SECONDS':'90','RADAR_LLM_MAX_TOKENS':'6000','RADAR_LLM_API_KEY':'never-sync'}
        import tempfile
        from pathlib import Path
        p=preview_config(values,'http://127.0.0.1:17860',str(Path(tempfile.gettempdir())/'demo'),'http://127.0.0.1:6335')
        self.assertNotIn('RADAR_LLM_MODEL',p)
        self.assertEqual(p['RADAR_LLM_REASONING_EFFORT'],'high')
        self.assertNotIn('RADAR_LLM_API_KEY',p)
        self.assertIn('RADAR_LLM_',RECEIVER)
        with self.assertRaises(ValueError):preview_config(values|{'RADAR_LLM_REASONING_EFFORT':'bad\nvalue'},'http://127.0.0.1:17860','/tmp/demo','http://127.0.0.1:6335')
