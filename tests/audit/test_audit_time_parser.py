"""Time boundaries and real audit selection; no external model is used."""
from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import Mock, patch
from tests.application import test_integration as fixture
from contextledger.audit.query import AuditQueryParser


NOW = datetime(2026, 3, 31, 12, 30, tzinfo=timezone.utc)


class AuditTimeParserTests(unittest.TestCase):
    def parse(self, query, now=NOW):
        return AuditQueryParser().parse(query, {}, [], now=now)

    def test_week_aliases_have_identical_rolling_window(self):
        expected = (NOW - timedelta(days=7)).isoformat()
        for text in ['过去一周', '最近一个星期', '近7天', 'last 7 days', 'past a week']:
            with self.subTest(text=text):
                bounds = self.parse(text)
                self.assertEqual(bounds['start'], expected)
                self.assertEqual(bounds['end'], NOW.isoformat())

    def test_chinese_quantities_and_week_multiplier(self):
        for text, days in [('过去两周',14), ('最近十四天',14), ('过去三十天',30), ('最近一百天',100)]:
            with self.subTest(text=text):
                self.assertEqual(self.parse(text)['start'],(NOW-timedelta(days=days)).isoformat())

    def test_calendar_month_clamps_month_end_and_handles_leap_year(self):
        self.assertEqual(self.parse('过去一个月')['start'], '2026-02-28T12:30:00+00:00')
        leap=NOW.replace(year=2024)
        self.assertEqual(self.parse('past 1 month',leap)['start'], '2024-02-29T12:30:00+00:00')
        self.assertEqual(self.parse('最近三个月')['start'], '2025-12-31T12:30:00+00:00')

    def test_calendar_days_use_utc_boundaries(self):
        today=self.parse('今天谁查询过？')
        yesterday=self.parse('昨天谁查询过？')
        self.assertEqual(today['start'],'2026-03-31T00:00:00+00:00')
        self.assertEqual(today['end'],NOW.isoformat())
        self.assertEqual(yesterday['start'],'2026-03-30T00:00:00+00:00')
        self.assertEqual(yesterday['end'],'2026-03-30T23:59:59.999999+00:00')
        local=NOW.astimezone(timezone(timedelta(hours=8)))
        self.assertEqual(self.parse('昨天',local),yesterday)

    def test_unsupported_conflicting_or_invalid_time_is_not_unbounded(self):
        for text in ['上周','过去一季度','last week','过去零天','过去99999天',
                     '过去十三个月以及最近两天','昨天过去7天','2026-03-01到2026-03-10']:
            with self.subTest(text=text),self.assertRaises(ValueError):self.parse(text)

    def test_no_time_constraint_preserves_unfiltered_query(self):
        parsed=self.parse('谁访问过资料？')
        self.assertIsNone(parsed['start']);self.assertIsNone(parsed['end'])

    def test_explicit_range_can_bypass_natural_time_without_changing_identity_filters(self):
        self.assertIsNone(AuditQueryParser().parse('上周',{},[],parse_time=False)['start'])

    def test_reference_time_must_be_timezone_aware(self):
        with self.assertRaises(ValueError):self.parse('过去一周',NOW.replace(tzinfo=None))


class AuditTimeSelectionTests(unittest.TestCase):
    setUp = fixture.IntegrationTests.setUp
    login = fixture.IntegrationTests.login

    def test_old_and_future_events_are_excluded_before_audit_model_input(self):
        current=datetime.now(timezone.utc)
        for days in [-20,-3,1]:
            self.service.record(self.alice,'search',question='controlled date boundary',
                                timestamp=(current+timedelta(days=days)).isoformat())
        self.service.audit_answerer=Mock()
        self.service.audit_answerer.answer.return_value=(None,{'status':'test_no_model','attempts':0})
        results=self.service.audit_query(self.admin.id,query='过去一周谁查询过？',
                                         user_id=self.alice.id,generate=True)
        self.assertEqual(len(results['events']),1)
        selected=self.service.audit_answerer.answer.call_args.args[1]
        self.assertEqual(len(selected),1)
        self.assertEqual(results['events'][0]['timestamp'],(current-timedelta(days=3)).isoformat())
        self.assertEqual(selected[0]['timestamp_sgt'],(current-timedelta(days=3)).astimezone(
            timezone(timedelta(hours=8))).strftime('%d %b %Y %H:%M:%S SGT (UTC+08)'))
        self.assertTrue(results['integrity']['valid'])
        self.assertFalse(results['events'][0]['redacted'])
        with self.assertRaises(PermissionError):
            self.service.audit_query(self.alice.id,query='过去一周')

    def test_unsupported_window_returns_http_400_without_audit_generation(self):
        self.login(self.admin)
        self.service.audit_answerer=Mock()
        response=self.client.get('/api/audit',query_string={'q':'上周谁查询过？'})
        self.assertEqual(response.status_code,400)
        self.service.audit_answerer.answer.assert_not_called()

    def test_structured_start_end_override_unsupported_natural_phrase(self):
        self.service.record(self.alice,'search',timestamp='2026-03-25T12:00:00+00:00')
        result=self.service.audit_query(self.admin.id,query='上周谁查询过？',
            user_id=self.alice.id,start='2026-03-23T00:00:00+00:00',end='2026-03-29T23:59:59+00:00')
        self.assertEqual(len(result['events']),1)
        self.assertEqual(result['selection']['filters']['start'],'2026-03-23T00:00:00+00:00')
