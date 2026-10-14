"""Real /api/ask regression on synthetic documents and a native Qdrant server."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


def amounts(text):
    found = set()
    number = r'([0-9]+(?:[,，][0-9]{3})*(?:\.[0-9]+)?)'
    patterns = [number + r'\s*(万|千|million|thousand)?\s*(?:CNY|RMB|yuan|人民币|元)',
                r'(?:人民币|CNY|RMB|￥|¥)\s*' + number + r'\s*(万|千|million|thousand)?',
                number + r'\s*(万|千)']
    multipliers = {'': 1, '万': 10000, '千': 1000, 'million': 1000000, 'thousand': 1000}
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.I):
            value = Decimal(match[1].replace(',', '').replace('，', '')) * multipliers[(match[2] or '').lower()]
            found.add(str(value.normalize()))
    return found


def score(case, result, status, expected_hashes):
    answer = result.get('answer', '')
    evidence = result.get('evidence', [])
    citation_map = {e['citation_id']: e['doc_id'] for e in evidence}
    markers = {int(n) for n in re.findall(r'\[(\d+)\]', answer)}
    cited = {citation_map[n] for n in markers if n in citation_map}
    expected = set(case.get('gold', []))
    versions = {(e['doc_id'], e['content_hash']) for e in evidence}
    checks = {'http_ok': status == 200,
              'decision': result.get('decision') == case.get('decision', 'answered')}
    if case.get('decision') == 'insufficient':
        checks.update(empty_evidence=not evidence, no_citations=not markers,
                      no_model_call=result.get('llm_diagnostics', {}).get('attempts') == 0)
    else:
        checks.update(real_model=str(result.get('provider', '')).startswith('openai_compatible/'),
                      gold_retrieved=expected.issubset({e['doc_id'] for e in evidence}),
                      gold_cited=expected.issubset(cited),
                      citation_scope=bool(markers) and markers.issubset(citation_map),
                      current_versions=all((doc, expected_hashes[doc]) in versions for doc in expected))
        if case.get('language') == 'en':
            checks['language'] = not bool(re.search(r'[\u4e00-\u9fff]', answer))
        elif case.get('language') == 'zh':
            checks['language'] = bool(re.search(r'[\u4e00-\u9fff]', answer))
        if 'amounts' in case:
            checks['amounts'] = amounts(answer) == {str(Decimal(n).normalize()) for n in case['amounts']}
        for i, pattern in enumerate(case.get('required_patterns', [])):
            checks[f'fact_{i}'] = bool(re.search(pattern, answer, re.I))
    for i, pattern in enumerate(case.get('forbidden_patterns', [])):
        checks[f'forbidden_{i}'] = not bool(re.search(pattern, answer, re.I))
    return {'passed': all(checks.values()), 'checks': checks, 'cited_docs': sorted(cited)}


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def setup(out, spec, client):
    from contextledger.audit_store import AuditStore
    from contextledger.demo_identity import initialize_demo
    from contextledger.document_updates import DocumentUpdates
    from contextledger.filtered_index import FilteredIndex, migrate
    from contextledger.identity_store import IdentityStore
    from contextledger.models import CanonicalDoc, Principal, SourceDoc
    from contextledger.processors import chunk_document
    from contextledger.store import connect, init_db, insert_documents, insert_principals
    from contextledger.unified_service import UnifiedService
    from contextledger.web import create_app
    from src.answering import AnswerService

    corpus = spec['corpus']
    db_path, security = out / 'content/canonical.sqlite', out / 'security'
    if db_path.exists() or security.exists():
        raise ValueError('Use a new output directory; existing data is never overwritten')
    with connect(db_path) as db:
        init_db(db)
        insert_principals(db, [Principal(corpus, corpus + ':' + alias, alias, 'engineer', 'eng')
                              for alias in ('alice', 'bob', 'carol', 'dave', 'erin', 'outside')], {})
        docs, chunks = [], []
        for entry in spec['documents']:
            source = SourceDoc(corpus, entry['id'], entry['source'], entry['title'], entry['text'],
                               None, None, 'eng', [], entry.get('metadata', {}))
            parts = chunk_document(source)
            docs.append(CanonicalDoc(corpus, entry['id'], entry['source'], entry['title'], entry['text'],
                        None, None, 'eng', [], [corpus + ':' + a for a in entry.get('acl', ['alice', 'bob'])],
                        'explicit synthetic chat fixture', 'initial', digest(entry['text']),
                        entry.get('metadata', {}), [p.chunk_id for p in parts]))
            chunks.extend(parts)
        insert_documents(db, docs, chunks)
        db.commit()
    migration = migrate(db_path, client, batch_size=128)
    roster = initialize_demo(db_path, security, [(corpus, corpus + ':' + a)
                             for a in ('alice', 'bob', 'carol', 'dave', 'erin', 'outside')])
    ids = IdentityStore(security / 'identities.sqlite')
    audit = AuditStore(security / 'audit.sqlite')
    index = FilteredIndex(db_path, client, ids)
    index.install_snapshot_guard()
    service = UnifiedService(index, ids, audit, answer=AnswerService())
    updates = DocumentUpdates(index, ids, audit, autostart=True)
    app = create_app(db_path, security, service=service, updates=updates,
                     config={'DEMO_MODE': True, 'BROWSER_LOGIN_ENABLED': False,
                             'PUBLIC_URL': 'http://127.0.0.1:17861'})
    actors = {a['subject']: a['id'] for a in roster['accounts']}
    return app, service, updates, actors, migration['collection']


def authenticated_client(app, actor):
    client = app.test_client()
    base = 'http://127.0.0.1:17861'
    csrf = client.get('/api/session', base_url=base).json['csrf']
    response = client.post('/api/demo/select', base_url=base, json={'user_id': actor},
                           headers={'Origin': base, 'X-CSRF-Token': csrf})
    if response.status_code != 200:
        raise RuntimeError('Could not select fixed demo identity')
    csrf = client.get('/api/session', base_url=base).json['csrf']
    return client, {'Origin': base, 'X-CSRF-Token': csrf}


def run(args, spec, app, service, updates, actors):
    from contextledger.store import connect
    corpus = spec['corpus']
    expected = {entry['id']: digest(entry['text']) for entry in spec['documents']}
    rows = []
    result_lock = threading.Lock()
    base = 'http://127.0.0.1:17861'

    def ask(case):
        actor = actors['employee-06' if case.get('actor') == 'outside' else 'employee-01']
        client, headers = authenticated_client(app, actor)
        started = time.perf_counter()
        response = client.post('/api/ask', base_url=base, headers=headers,
                               json={'corpus': corpus, 'q': case['question'],
                                     'mode': case.get('mode', 'hybrid'), 'planning': False})
        elapsed = (time.perf_counter() - started) * 1000
        result = response.get_json() or {}
        row = {'case': case, 'http_status': response.status_code, 'latency_ms': elapsed,
               'result': result, **score(case, result, response.status_code, expected)}
        with result_lock, (args.out / 'results.jsonl').open('a') as file:
            file.write(json.dumps(row, ensure_ascii=False) + '\n')
        print(json.dumps({'id': case['id'], 'passed': row['passed'], 'decision': result.get('decision'),
                          'latency_ms': round(elapsed), 'failed_checks': [k for k, v in row['checks'].items() if not v]}, ensure_ascii=False), flush=True)
        return row

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        rows.extend(pool.map(ask, spec['cases']))
    update = spec['update']
    for stage in ('before', 'after'):
        if stage == 'after':
            client, headers = authenticated_client(app, actors['administrator'])
            with connect(service.index.db_path) as db:
                version = db.execute('SELECT version FROM documents WHERE corpus=? AND doc_id=?',
                                     (corpus, update['id'])).fetchone()[0]
            entry = next(e for e in spec['documents'] if e['id'] == update['id'])
            response = client.post('/api/admin/documents', base_url=base, headers=headers,
                json={'corpus': corpus, 'doc_id': update['id'], 'source': entry['source'],
                      'title': entry['title'], 'text': update['text'],
                      'expected_version': version})
            if response.status_code != 202:
                raise RuntimeError(f'Update rejected: {response.status_code}')
            job = response.json['job']
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                state = updates.status(actors['administrator'], job['id'])
                if state['state'] == 'ready':
                    break
                if state['state'] == 'failed':
                    raise RuntimeError('Update publication failed')
                time.sleep(.02)
            else:
                raise TimeoutError('Update was not ready within 30 seconds')
            expected[update['id']] = digest(update['text'])
            write(args.out / 'update-job.json', state)
        for mode in ('keyword', 'vector', 'hybrid'):
            rows.append(ask({'id': f'update-{stage}-{mode}', 'category': 'update',
                             'question': update['question'], 'gold': [update['id']],
                             'mode': mode, 'amounts': [update[stage + '_amount']]}))
    service.identities.restrict(actors['employee-01'], corpus, 'corpus', '*', True)
    try:
        for mode in ('keyword', 'vector', 'hybrid'):
            rows.append(ask({'id': 'revoked-' + mode, 'category': 'revocation',
                             'question': update['question'], 'gold': [], 'mode': mode,
                             'decision': 'insufficient', 'forbidden_patterns': ['120000', '120,000']}))
    finally:
        service.identities.restrict(actors['employee-01'], corpus, 'corpus', '*', False)
    import numpy as np
    groups = {}
    for category in sorted({r['case']['category'] for r in rows}):
        selected = [r for r in rows if r['case']['category'] == category]
        groups[category] = {'passed': sum(r['passed'] for r in selected), 'total': len(selected)}
    generated = [r for r in rows if r['case'].get('decision') != 'insufficient']
    summary = {'passed': sum(r['passed'] for r in rows), 'total': len(rows), 'groups': groups,
               'answer_latency_ms': dict(zip(['p50', 'p95'], map(float, np.percentile([r['latency_ms'] for r in generated], [50, 95])))),
               'audit_valid': service.audit.verify().valid,
               'scope': 'Fixed synthetic regression; numeric/status/citation checks, not full semantic correctness, a held-out score or production acceptance.'}
    write(args.out / 'summary.json', summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--qdrant-url', required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--env-file', type=Path)
    parser.add_argument('--model', help='override the configured model for a paired comparison')
    parser.add_argument('--workers', type=int, default=2)
    parser.add_argument('--serve', action='store_true', help='keep the isolated preview on 127.0.0.1:17861')
    args = parser.parse_args()
    if not 1 <= args.workers <= 4:
        parser.error('workers must be 1..4')
    from dotenv import load_dotenv
    load_dotenv(args.env_file or ROOT / '.env', override=True)
    if args.model:
        os.environ['LLM_MODEL'] = args.model
    if not os.getenv('LLM_API_KEY') or os.getenv('LLM_PROVIDER') != 'openai_compatible':
        parser.error('A configured real openai_compatible model is required')
    os.environ.update(CUDA_VISIBLE_DEVICES='', LLM_PLANNER_ENABLED='false')
    import torch
    torch.set_num_threads(4)
    from qdrant_client import QdrantClient
    from src.answering import SYSTEM_PROMPT, PROMPT_VERSION
    from contextledger.radar_protocol import TOOL_PROMPT, SYNTHESIS_PROMPT, VERSION
    fixture = ROOT / 'fixtures/chat/evaluation.json'
    spec = json.loads(fixture.read_text())
    args.out.mkdir(parents=True, exist_ok=True)
    write(args.out / 'protocol.json', {'git_head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
          'model': os.environ.get('LLM_MODEL'), 'base_url': os.environ.get('LLM_BASE_URL'),
          'reasoning_effort': os.environ.get('LLM_REASONING_EFFORT'), 'workers': args.workers,
          'temperature': 0, 'answer_max_tokens': 1600,
          'radar_reasoning_effort': os.getenv('RADAR_LLM_REASONING_EFFORT', 'high'),
          'radar_max_tokens': os.getenv('RADAR_LLM_MAX_TOKENS', '6000'),
          'documents': len(spec['documents']), 'fixture_sha256': digest(fixture.read_text()),
          'prompt_version': PROMPT_VERSION, 'prompt_sha256': digest(SYSTEM_PROMPT),
          'radar_version': VERSION, 'radar_prompt_sha256': digest(TOOL_PROMPT + SYNTHESIS_PROMPT),
          'implementation_sha256': {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
              for name in ('src/answering.py', 'contextledger/unified_service.py', 'contextledger/web.py',
                           'contextledger/static/unified.js', 'contextledger/templates/unified.html',
                           'contextledger/radar_protocol.py', 'scripts/evaluate_chat.py')},
          'planning': False, 'native_qdrant': True, 'embedding': 'real MiniLM CPU',
          'scoring': 'fixed facts, amount sets, status patterns, cited document IDs and current hashes; all failures retained'})
    client = QdrantClient(url=args.qdrant_url, timeout=60)
    app, service, updates, actors, collection = setup(args.out, spec, client)
    try:
        run(args, spec, app, service, updates, actors)
        if args.serve:
            app.run(host='127.0.0.1', port=17861, threaded=True, use_reloader=False)
    finally:
        updates.close()
        client.delete_collection(collection)
        client.close()


if __name__ == '__main__':
    main()
