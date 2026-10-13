"""Latency comparisons retain failures and keep workloads separate."""
import unittest
from scripts.evaluate_chat_latency import summarize


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


if __name__ == '__main__':
    unittest.main()
