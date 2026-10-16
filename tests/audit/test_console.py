"""Approved administrator audit scope, exact selection and mutation evidence."""
from datetime import datetime, timezone
import json
import unittest
from unittest.mock import patch

from contextledger.audit.console import question_filters
from contextledger.storage.store import connect
from tests.application import test_integration as fixtures


class AuditConsoleTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.IntegrationTests();self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.addCleanup(self.f.app.extensions['document_updates'].close)
        self.f.login(self.f.admin)

    def change(self,**fields):
        return self.f.post('/api/admin/permissions',{'user_id':self.f.alice.id,**fields})

    def query(self,**filters):
        response=self.f.client.get('/api/audit',query_string=filters)
        self.assertEqual(response.status_code,200,response.json)
        return response.json

    def test_admin_reads_historical_answers_without_business_access_or_current_version(self):
        result,_=self.f.service.ask(self.f.alice.id,'alpha','TitanDB','keyword',planning=False)
        self.f.ids.bind(self.f.alice.id,'alpha','alpha:a',False)
        with connect(self.f.db_path) as db:db.execute("UPDATE documents SET version='new' WHERE doc_id='doc-0'")
        with patch.object(self.f.index,'open',side_effect=AssertionError('audit must not require current business evidence')):
            event=self.query(request_id=result['request_id'])['events'][0]
        self.assertFalse(event['redacted']);self.assertEqual(event['answer'],result['answer'])
        self.assertEqual({e['doc_id'] for e in event['evidence']},{'doc-0','doc-1'})
        self.f.login(self.f.alice)
        for path in ('/api/audit','/api/audit/options','/api/audit/events/1'):
            self.assertEqual(self.f.client.get(path).status_code,403)
        self.assertEqual(self.f.post('/api/audit/ask',{'q':'audit all activity'}).status_code,403)

    def test_source_clearance_and_membership_have_before_after_and_single_completion(self):
        self.assertEqual(self.change(action='restriction',corpus='alpha',kind='source',value='jira',denied=True).status_code,200)
        event=self.query(category='permissions',target=self.f.alice.id)['events'][0]
        self.assertEqual(event['change']['before'],{'denied':False});self.assertEqual(event['change']['after'],{'denied':True})
        self.assertEqual(event['actor_id'],self.f.admin.id);self.assertEqual(event['target_user_id'],self.f.alice.id)
        self.assertEqual(self.query(category='permissions',source='jira')['total_count'],1)
        self.assertEqual(self.change(action='account',clearance=2,department='Engineering').status_code,200)
        event=self.query(category='permissions',keyword='clearance')['events'][0]
        self.assertEqual(event['change']['after'],{'clearance':2,'department':'Engineering'})
        self.assertEqual(event['change']['target_epoch_after'],event['change']['target_epoch_before']+1)
        self.f.ids.register_project('alpha','alpha:new-project','New project')
        self.assertEqual(self.change(action='project_membership',corpus='alpha',project='alpha:new-project',enabled=True).status_code,200)
        event=self.query(category='permissions',project='alpha:new-project')['events'][0]
        self.assertEqual(event['change']['before'],{'member':False});self.assertEqual(event['change']['after'],{'member':True})
        self.assertTrue(event['operation_id'])
        self.assertEqual(self.query(category='permissions')['total_count'],3)
        self.assertEqual(self.query(category='permissions',actor=self.f.alice.id)['total_count'],0)
        self.assertEqual(self.query(category='permissions',target=self.f.alice.id)['total_count'],3)
        self.assertEqual(self.change(action='account',clearance=99).status_code,400)
        failed=self.query(category='permissions',outcome='failed')['events'][0]
        self.assertEqual(failed['event_type'],'permission_change_failed')
        self.assertEqual(self.f.ids.get(self.f.alice.id).clearance,2)

    def test_real_keywords_exact_totals_and_stable_cursor(self):
        for index in range(31):self.f.service.record(self.f.alice,'search',question='Kafka probe '+str(index),corpus='alpha')
        first=self.query(category='access',keyword='Kafka',limit=7)
        self.assertEqual(first['total_count'],31);self.assertEqual(len(first['events']),7)
        self.assertEqual(self.query(category='access',keyword='absentword')['total_count'],0)
        self.f.service.record(self.f.alice,'search',question='Kafka appended later')
        seen=[e['sequence'] for e in first['events']];page=first
        while page['next_cursor']:
            page=self.query(category='access',keyword='Kafka',limit=7,cursor=page['next_cursor'])
            self.assertEqual(page['total_count'],31);seen.extend(e['sequence'] for e in page['events'])
        self.assertEqual(len(seen),31);self.assertEqual(len(set(seen)),31)
        self.assertEqual(self.query(category='access',keyword='Kafka')['total_count'],32)
        bad=self.f.client.get('/api/audit',query_string={'category':'permissions','cursor':first['next_cursor']})
        self.assertEqual(bad.status_code,400)

    def test_legacy_missing_fields_denied_original_and_four_categories(self):
        legacy=self.f.service.record(self.f.admin,'permission_change',change={'user_id':self.f.alice.id,'action':'account'})
        event=self.query(sequence=legacy['sequence'])['events'][0]
        self.assertNotIn('before',event['change']);self.assertIn('not recorded',event['change_recording'])
        self.f.service.open(self.f.alice.id,'alpha','does-not-exist')
        event=self.query(category='access')['events'][0]
        self.assertEqual(event['requested_document_id'],'does-not-exist')
        self.assertEqual(event['category'],'access')
        self.f.service.record(self.f.alice,'access_denied',endpoint='/api/admin/users',decision='denied')
        self.f.service.record(self.f.admin,'document_update_ready',job_id='job',doc_id='doc-0',version='next',before_version='old',corpus='alpha')
        self.assertEqual(self.query(category='violations')['total_count'],1)
        update=self.query(category='updates')['events'][0];self.assertEqual(update['before_version'],'old')
        self.assertEqual(update['outcome'],'published')
        self.assertEqual(self.query(category='permissions',keyword='Same Name')['total_count'],1)
        self.assertEqual(self.f.client.get('/api/audit/options').status_code,200)
        self.assertTrue(self.f.audit.verify().valid)

    def test_ai_receives_changes_all_categories_and_exact_statistics(self):
        self.change(action='restriction',corpus='alpha',kind='source',value='slack',denied=True)
        self.f.service.record(self.f.alice,'search',question='Kafka')
        self.f.service.record(self.f.alice,'access_denied',endpoint='/api/admin/users',decision='denied')
        self.f.service.record(self.f.admin,'document_update_ready',doc_id='doc-0',corpus='alpha',job_id='job',version='next')
        captured=[]
        def explain(query,events,selection,guard):
            captured.append((events,selection));guard()
            return {'answer':'Recorded change [E'+str(events[0]['sequence'])+']. Four events [Q1].','decision':'answered','citation_ids':['E'+str(events[0]['sequence']),'Q1']},{'attempts':1,'actual_model':'test-model'}
        with patch.object(self.f.service.audit_answerer,'answer',side_effect=explain):
            result=self.f.post('/api/audit/ask',{'q':'Summarize information access, permission changes, document updates and blocked operations'} )
        self.assertEqual(result.status_code,200,result.json)
        events,selection=captured[0]
        self.assertEqual({e['category'] for e in events},{'access','permissions','updates','violations'})
        self.assertEqual(selection['total_count'],4)
        self.assertEqual(selection['statistics']['by_category']['access']['outcome'],{'allowed':1})
        self.assertEqual(selection['statistics']['by_category']['permissions']['outcome'],{'allowed':1})
        self.assertIn('SGT (UTC+08)',events[0]['timestamp_sgt'])
        self.assertNotIn('timestamp',events[0])
        self.assertEqual(selection['response_language'],'English')
        self.assertEqual(selection['returned_count'],len(events))
        change=next(e['change'] for e in events if e['category']=='permissions')
        self.assertEqual(change['after'],{'denied':True})
        self.assertFalse(selection['not_whole_period_statistics'])
        self.assertIn('Q1',result.json['answer'])

    def test_cross_category_model_budget_preserves_change_details(self):
        self.change(action='restriction',corpus='alpha',kind='source',value='slack',denied=True)
        for _ in range(12):
            self.f.service.record(self.f.alice,'answer',question='Long answer',answer='A'*10000,
                evidence=[{'doc_id':'doc-0','title':'T'*1500,'text':'B'*8000}]*8)
        captured=[]
        def explain(query,events,selection,guard):
            captured.extend(events);guard()
            return None,{'attempts':1}
        with patch.object(self.f.service.audit_answerer,'answer',side_effect=explain):
            result=self.f.post('/api/audit/ask',{'q':'Compare information access and permission changes'})
        self.assertEqual(result.status_code,200)
        self.assertEqual({e['category'] for e in captured},{'access','permissions'})
        change=next(e['change'] for e in captured if e['category']=='permissions')
        self.assertEqual(change['after'],{'denied':True})
        self.assertLessEqual(sum(len(json.dumps(e,ensure_ascii=False)) for e in captured),40000)

    def test_ai_guard_stops_administrator_role_change(self):
        self.f.service.record(self.f.alice,'search',question='Kafka')
        def change_role(query,events,selection,guard):
            self.f.ids.update(self.f.admin.id,role='member');guard()
        with patch.object(self.f.service.audit_answerer,'answer',side_effect=change_role):
            result=self.f.post('/api/audit/ask',{'q':'Summarize access'})
        self.assertEqual(result.status_code,409)

    def test_demo_ai_uses_english_names_and_question_language_without_rewriting_history(self):
        person=self.f.ids.register('test','legacy-jax','Jax（演示员工）')
        before_epoch=person.epoch
        legacy=self.f.service.record(self.f.admin,'permission_change',
            actor_name='ContextLedger 管理员',target_user_name=person.name,
            change={'user_id':person.id,'action':'account','before':{'clearance':1},'after':{'clearance':2}})
        self.f.service.record(person,'search',question='Telemetry dashboard')
        self.f.service.identity_mode='isolated_demo'
        captured=[]
        def explain(query,events,selection,guard):
            captured.append((events,selection));guard()
            return {'answer':'Recorded activity [Q1].','decision':'answered','citation_ids':['Q1']},{'attempts':1}
        with patch.object(self.f.service.audit_answerer,'answer',side_effect=explain):
            result=self.f.post('/api/audit/ask',{'q':'今天Jax查过什么，权限变化有哪些？'})
        self.assertEqual(result.status_code,200)
        events,selection=captured[0]
        self.assertEqual(selection['response_language'],'Chinese')  # Replies follow the question's language.
        change=next(e for e in events if e['category']=='permissions')
        self.assertEqual(change['user_name'],'ContextLedger Administrator')
        self.assertEqual(change['target_user_name'],'Jax')
        self.assertEqual(next(e for e in events if e['category']=='access')['user_name'],'Jax')
        stored=self.f.audit.query(request_id=legacy['request_id'])[0]
        self.assertEqual(stored,legacy)
        self.assertEqual(self.f.ids.get(person.id).name,person.name)
        self.assertEqual(self.f.ids.get(person.id).epoch,before_epoch)

    def test_ai_sgt_today_and_target_alias(self):
        person=self.f.ids.register('test','jax','Jax（演示员工）')
        parsed=question_filters('今天谁改了Jax的权限？',self.f.ids,now=datetime(2026,10,15,18,tzinfo=timezone.utc))
        self.assertEqual(parsed['subject'],person.id)
        self.assertEqual(parsed['category'],'permissions')
        self.assertEqual(parsed['start'],'2026-10-15T16:00:00+00:00')
        self.assertEqual(parsed['end'],'2026-10-15T18:00:00+00:00')
        parsed=question_filters('谁撤销了Jax的Slack权限，之后还能访问吗？',self.f.ids)
        self.assertEqual(parsed['category'],'access,permissions')
        self.assertNotIn('source',parsed)


if __name__=='__main__':unittest.main()
