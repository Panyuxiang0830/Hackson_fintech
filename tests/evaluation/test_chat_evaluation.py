from contextledger.paths import PROJECT_ROOT
"""Scoring rejects successful-looking answers with wrong facts or evidence."""
import json
from pathlib import Path
import unittest

from contextledger.evaluation.chat import amounts, score


class ChatEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.case = {'gold': ['quota', 'approval'], 'amounts': [60000],
                     'required_patterns': ['pending|待审批']}
        self.result = {'decision': 'answered', 'provider': 'openai_compatible/test',
                       'answer': '拟议上限 6 万元 [1]，待审批 [2]。',
                       'evidence': [{'citation_id': 1, 'doc_id': 'quota', 'content_hash': 'new'},
                                    {'citation_id': 2, 'doc_id': 'approval', 'content_hash': 'state'}]}
        self.hashes = {'quota': 'new', 'approval': 'state'}

    def test_currency_forms_are_equivalent(self):
        for text in ['6 万元', '60,000 CNY', 'RMB 60000', '人民币 6万']:
            self.assertEqual(amounts(text), amounts('60000 CNY'))

    def test_pending_answer_requires_both_cited_current_sources(self):
        self.assertTrue(score(self.case, self.result, 200, self.hashes)['passed'])
        for replacement in ['60000 CNY approved [1] [2]', '60000 CNY pending [1]',
                            '60000 CNY pending [1] [2] [99]', '70000 CNY pending [1] [2]']:
            with self.subTest(answer=replacement):
                self.assertFalse(score(self.case, self.result | {'answer': replacement}, 200, self.hashes)['passed'])

    def test_stale_evidence_fails_even_with_correct_numbers_and_citations(self):
        stale = self.result | {'evidence': [self.result['evidence'][0] | {'content_hash': 'old'},
                                           self.result['evidence'][1]]}
        self.assertFalse(score(self.case, stale, 200, self.hashes)['passed'])

    def test_mock_fallback_and_http_error_never_count_as_real_success(self):
        self.assertFalse(score(self.case, self.result | {'provider': 'mock_fallback'}, 200, self.hashes)['passed'])
        self.assertFalse(score(self.case, self.result, 503, self.hashes)['passed'])

    def test_english_question_with_chinese_answer_fails_language_check(self):
        case = self.case | {'language': 'en'}
        self.assertFalse(score(case, self.result, 200, self.hashes)['passed'])
        result = self.result | {'answer': 'The proposed amount is 60000 CNY [1], pending approval [2].'}
        self.assertTrue(score(case, result, 200, self.hashes)['passed'])

    def test_negative_requires_empty_scope_and_no_generation(self):
        case = {'decision': 'insufficient', 'gold': []}
        safe = {'decision': 'insufficient', 'answer': 'Insufficient usable evidence.',
                'evidence': [], 'llm_diagnostics': {'attempts': 0}}
        self.assertTrue(score(case, safe, 200, {})['passed'])
        self.assertFalse(score(case, safe | {'llm_diagnostics': {'attempts': 1}}, 200, {})['passed'])
        self.assertFalse(score(case, safe | {'evidence': self.result['evidence']}, 200, {})['passed'])

    def test_fixture_gold_exists_and_ids_are_unique(self):
        path = PROJECT_ROOT / 'fixtures/chat/evaluation.json'
        fixture = json.loads(path.read_text())
        docs = {d['id'] for d in fixture['documents']}
        cases = fixture['cases']
        self.assertEqual(len({c['id'] for c in cases}), len(cases))
        self.assertTrue(all(set(c['gold']).issubset(docs) for c in cases))
