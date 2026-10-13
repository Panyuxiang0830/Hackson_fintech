"""Interleaved native-index chat latency experiments; no live-service changes."""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import sqlite3
import statistics
import subprocess
import sys
import threading
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SCALAR_HINT = ''' For a plain request for an owner, deadline, date or single amount,
first inspect the initial authorised evidence. If the requested fact is explicit,
answer it directly and name its subject, with citations. A short follow-up phrase
such as "then what is the deadline" does not itself require history reconstruction.
No previous conversation is supplied; never invent its subject. Do not invoke
Radar merely to collect more records when the requested scalar fact is already
present. This rule does not relax Radar requirements for explicit history,
revision comparisons, conflicting reports, cross-entity relations or multi-source
business-process reconstruction. Before claiming a missing formal state or
missing review/recovery record, the existing bounded Radar requirements still apply.
'''
PROFILES = [('baseline_high', 'high', False), ('scalar_hint_high', 'high', True),
            ('scalar_hint_low', 'low', True)]


def digest(value):
    return hashlib.sha256(value if isinstance(value, bytes) else value.encode()).hexdigest()


def summarize(rows):
    groups = defaultdict(list)
    for row in rows:
        groups[(row['case']['id'], row['profile'])].append(row)
    return [{'case': case, 'profile': profile, 'observations': len(items),
             'passed': sum(item['passed'] for item in items),
             'median_ms': round(statistics.median(item['latency_ms'] for item in items), 1),
             'range_ms': [round(min(item['latency_ms'] for item in items), 1),
                          round(max(item['latency_ms'] for item in items), 1)],
             'model_calls': [item['result'].get('llm_diagnostics', {}).get('model_calls', 0) for item in items],
             'documents': [len(item['result'].get('evidence', [])) for item in items],
             'failures': [item['result'].get('llm_diagnostics', {}).get('failures', []) for item in items]}
            for (case, profile), items in groups.items()]


def backup(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(f'file:{source.resolve()}?mode=ro', uri=True) as src, sqlite3.connect(target) as dst:
        src.backup(dst)


def cases():
    return [
        {'id': 'named_deadline', 'question': 'OakRunbook 退款复核负责人、截止日期分别是什么？',
         'gold': ['OakRunbook'], 'language': 'zh', 'required_patterns': ['Lin', r'2026\s*[年/-]?\s*11\s*[月/-]?\s*0?2']},
        {'id': 'unnamed_deadline', 'question': '那截止日期是哪天？', 'gold': ['OakRunbook'], 'language': 'zh',
         'required_patterns': ['OakRunbook', r'2026\s*[年/-]?\s*11\s*[月/-]?\s*0?2']},
        {'id': 'budget_conflict', 'question': 'MossBudget 的试点预算到底是 40000 还是 55000？请说出各来源意见。',
         'gold': ['MossBudgetFormal', 'MossBudgetReport'], 'language': 'zh', 'amounts': [40000, 55000],
         'required_patterns': ['冲突|不一致|不同|矛盾']},
        {'id': 'pending_approval', 'question': 'QuartzPay 的 60000 元额度已经可以用了么？',
         'gold': ['QuartzPayQuota', 'QuartzPayApproval'], 'language': 'zh', 'amounts': [60000],
         'required_patterns': ['待|尚未|未.{0,4}批准|未生效|pending']},
        {'id': 'unknown', 'question': 'MissingOrbit721 的当前上限是多少？', 'gold': [], 'decision': 'insufficient'},
        {'id': 'unauthorised', 'question': 'TracePay 当前每日转账上限是多少？', 'gold': [],
         'decision': 'insufficient', 'actor': 'outside'},
    ]


def run(args):
    from dotenv import load_dotenv
    load_dotenv(args.env_file, override=True)
    if not os.getenv('LLM_API_KEY') or os.getenv('LLM_PROVIDER') != 'openai_compatible':
        raise ValueError('Configure a real compatible model in the private env file')
    os.environ['QDRANT_URL'] = args.qdrant_url
    os.environ['LLM_PLANNER_ENABLED'] = 'false'
    os.environ['HF_HUB_OFFLINE'] = '1'
    import torch
    torch.set_num_threads(4)
    from contextledger import radar_protocol
    from contextledger.audit_store import AuditStore
    from contextledger.demo_identity import MARKER
    from contextledger.radar_tool import DecisionRadarTool
    from contextledger.web import create_app
    from scripts.evaluate_chat import score
    from src.answering import AnswerService
    from werkzeug.serving import make_server, WSGIRequestHandler
    import requests

    if args.out.exists():
        raise ValueError('Output must be new; previous evidence is never overwritten')
    args.out.mkdir(parents=True)
    db_path, security = args.out / 'content/canonical.sqlite', args.out / 'security'
    backup(args.source / 'content/canonical.sqlite', db_path)
    backup(args.source / 'security/identities.sqlite', security / 'identities.sqlite')
    AuditStore(security / 'audit.sqlite')
    roster = json.loads((args.source / 'security' / MARKER).read_text())
    roster['canonical_path'] = str(db_path.resolve())
    (security / MARKER).write_text(json.dumps(roster, ensure_ascii=False, indent=2))
    with sqlite3.connect(db_path) as db:
        expected = dict(db.execute('SELECT doc_id, content_hash FROM documents'))
        corpora = [r[0] for r in db.execute('SELECT DISTINCT corpus FROM documents')]
    if len(corpora) != 1 or set(expected) != {d['id'] for d in json.loads((ROOT / 'fixtures/chat/evaluation.json').read_text())['documents']}:
        raise ValueError('Only the fixed synthetic chat fixture is permitted')
    original_prompt = radar_protocol.TOOL_PROMPT
    state = {'trace': [], 'retrieval': [], 'radar': []}
    original_completion, original_tool = AnswerService._completion, DecisionRadarTool.execute

    def completion(self, system, payload):
        started = time.perf_counter()
        row = {'stage': 'radar_synthesis' if 'decision_radar_result' in payload else 'route_or_direct',
               'input_sha256': digest(json.dumps({'system': system, 'payload': payload}, ensure_ascii=False, sort_keys=True)),
               'input_characters': len(system) + len(json.dumps(payload, ensure_ascii=False))}
        try:
            value = original_completion(self, system, payload)
            diagnostics = self.last_diagnostics
            row.update(actual_model=diagnostics.get('actual_model'), finish_reason=diagnostics.get('finish_reason'),
                       usage=diagnostics.get('usage_by_attempt', [{}])[-1],
                       requested_effort=diagnostics['model_stages'][-1]['reasoning_effort'])
            return value
        except Exception as error:
            row['error_type'] = type(error).__name__
            raise
        finally:
            row['latency_ms'] = round((time.perf_counter() - started) * 1000, 2)
            state['trace'].append(row)

    def tool(self, **kwargs):
        started = time.perf_counter()
        try:
            return original_tool(self, **kwargs)
        finally:
            state['radar'].append(round((time.perf_counter() - started) * 1000, 2))

    base = f'http://127.0.0.1:{args.port}'
    app = create_app(db_path, security, config={'DEMO_MODE': True, 'BROWSER_LOGIN_ENABLED': False,
        'PUBLIC_URL': base, 'SECRET_KEY': secrets.token_hex(32)})
    service = app.extensions['unified_service']
    original_retrieve = service.retrieve
    def retrieve(*pos, **kw):
        started = time.perf_counter()
        try:
            return original_retrieve(*pos, **kw)
        finally:
            state['retrieval'].append(round((time.perf_counter() - started) * 1000, 2))
    service.retrieve = retrieve
    actors = {a['subject']: a['id'] for a in roster['accounts']}
    sessions = {}
    class Quiet(WSGIRequestHandler):
        def log_request(self, *args, **kwargs):
            pass
    server = make_server('127.0.0.1', args.port, app, request_handler=Quiet)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    rows = []
    protocol = {'source_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD']).decode().strip(),
        'evaluator_sha256': digest(Path(__file__).read_bytes()),
        'model': os.getenv('LLM_MODEL'), 'route_effort': service.answer.reasoning_effort,
        'profiles': PROFILES, 'repeats': args.repeats, 'corpus': corpora[0],
        'content_hashes': expected, 'cases': cases(), 'tool_prompt_sha256': digest(original_prompt),
        'scalar_hint': SCALAR_HINT, 'scope': 'synthetic development cases, native Qdrant and MiniLM; production unchanged',
        'timer_scope': 'HTTP wall time; completion includes network/provider and JSON decoding; tool and retrieval separately timed'}
    (args.out / 'protocol.json').write_text(json.dumps(protocol, ensure_ascii=False, indent=2))
    try:
        with patch.object(AnswerService, '_completion', completion), patch.object(DecisionRadarTool, 'execute', tool):
            for repeat in range(args.repeats):
                for case in cases():
                    sequence = PROFILES if repeat % 2 == 0 else list(reversed(PROFILES))
                    for profile, effort, hint in sequence:
                        radar_protocol.TOOL_PROMPT = original_prompt + (SCALAR_HINT if hint else '')
                        service.answer.radar_reasoning = effort
                        actor = actors['employee-06' if case.get('actor') == 'outside' else 'employee-01']
                        if actor not in sessions:
                            session = requests.Session()
                            csrf = session.get(base+'/api/session', timeout=10).json()['csrf']
                            selected = session.post(base+'/api/demo/select', json={'user_id': actor},
                                headers={'Origin': base, 'X-CSRF-Token': csrf}, timeout=10)
                            selected.raise_for_status()
                            csrf = session.get(base+'/api/session', timeout=10).json()['csrf']
                            sessions[actor] = (session, {'Origin': base, 'X-CSRF-Token': csrf})
                        session, headers = sessions[actor]
                        state.update(trace=[], retrieval=[], radar=[])
                        started = time.perf_counter()
                        response = session.post(base+'/api/ask', json={'corpus': corpora[0], 'q': case['question'],
                            'mode': 'hybrid', 'planning': False}, headers=headers, timeout=240)
                        elapsed = (time.perf_counter() - started) * 1000
                        result = response.json()
                        graded = score(case, result, response.status_code, expected)
                        if case.get('require_radar'):
                            graded['checks']['radar_retained'] = bool(result.get('radar'))
                            graded['passed'] = all(graded['checks'].values())
                        row = {'case': case, 'profile': profile, 'repeat': repeat, 'http_status': response.status_code,
                               'latency_ms': round(elapsed, 2), 'model_calls': state['trace'],
                               'retrieval_ms': state['retrieval'], 'radar_ms': state['radar'], 'result': result, **graded}
                        rows.append(row)
                        with (args.out / 'results.jsonl').open('a') as file:
                            file.write(json.dumps(row, ensure_ascii=False)+'\n')
                        (args.out / 'summary.json').write_text(json.dumps(summarize(rows), ensure_ascii=False, indent=2))
                        print(json.dumps({'id': case['id'], 'profile': profile, 'repeat': repeat, 'passed': row['passed'],
                            'seconds': round(elapsed/1000, 2), 'models': len(state['trace']),
                            'documents': len(result.get('evidence', [])), 'failed': [k for k,v in graded['checks'].items() if not v]}, ensure_ascii=False), flush=True)
    finally:
        radar_protocol.TOOL_PROMPT = original_prompt
        server.shutdown()
        thread.join(timeout=5)
        app.extensions['document_updates'].close()
        for session, _ in sessions.values():
            session.close()
    print(json.dumps({'observations': len(rows), 'passed': sum(r['passed'] for r in rows), 'audit_valid': service.audit.verify().valid}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT/'runtime/deploy/tailnet')
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--env-file', type=Path, required=True)
    parser.add_argument('--qdrant-url', default='http://127.0.0.1:16339')
    parser.add_argument('--port', type=int, default=17864)
    parser.add_argument('--repeats', type=int, default=2)
    args = parser.parse_args()
    if args.repeats < 2:
        parser.error('Use at least two interleaved repeats')
    run(args)

if __name__ == '__main__':
    main()
