#!/usr/bin/env python3
"""Operator tool: apply a bounded demo manifest through the actual admin queue."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import sys
import time
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import requests
from contextledger.access.demo_identity import load_roster
from contextledger.access.identity_store import IdentityStore
from contextledger.access.demo_permissions import plan_annotations
from contextledger.application.service import validate_security_path


def other_documents_digest(db_path, corpus, selected):
    digest = hashlib.sha256()
    with sqlite3.connect('file:' + str(db_path) + '?mode=ro', uri=True) as db:
        db.row_factory = sqlite3.Row
        for row in db.execute('SELECT * FROM documents ORDER BY corpus,doc_id'):
            if row['corpus'] == corpus and row['doc_id'] in selected:
                continue
            digest.update(json.dumps(dict(row), ensure_ascii=False, sort_keys=True).encode())
            digest.update(b'\n')
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--security-dir', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--url', default='http://127.0.0.1:17866')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    parsed = urlparse(args.url)
    if parsed.scheme != 'http' or parsed.hostname not in {'127.0.0.1', 'localhost'} or parsed.path not in {'', '/'} or parsed.username or parsed.password or parsed.query or parsed.fragment:
        parser.error('only an explicit loopback demo URL is supported')
    validate_security_path(args.out, args.security_dir)
    db_path = args.out / 'canonical.sqlite'
    identities = IdentityStore(args.security_dir / 'identities.sqlite')
    roster = load_roster(db_path, args.security_dir, identities)
    manifest = json.loads(args.manifest.read_text())
    with sqlite3.connect('file:' + str(db_path) + '?mode=ro', uri=True) as db:
        db.row_factory = sqlite3.Row
        rows = [dict(row) for row in db.execute('SELECT * FROM documents WHERE corpus=?', (manifest['corpus'],))]
        if db.execute("SELECT 1 FROM cl_update_jobs WHERE state IN ('queued','running','failed') LIMIT 1").fetchone():
            raise RuntimeError('finish existing document updates before applying the demo fixture')
    bodies = plan_annotations(manifest, rows)
    employee = next(item for item in roster['accounts'] if (item.get('source') or {}).get('principal_id') == manifest['employee_source_principal'])
    selected = {entry['doc_id'] for entry in manifest['documents']}
    before = other_documents_digest(db_path, manifest['corpus'], selected)
    print(json.dumps({'dry_run': not args.apply, 'documents': [b['doc_id'] for b in bodies], 'project': manifest['project']}), flush=True)
    if not args.apply:
        return
    backup = args.security_dir.parent / 'demo-permission-annotations' / ('backup-' + str(time.time_ns()))
    backup.mkdir(parents=True, mode=0o700)
    (backup/'documents.json').write_text(json.dumps([r for r in rows if r['doc_id'] in selected], ensure_ascii=False, indent=2))
    for name in ('identities.sqlite', 'audit.sqlite'):
        with sqlite3.connect('file:' + str(args.security_dir/name) + '?mode=ro', uri=True) as src, sqlite3.connect(backup/name) as dest:
            src.backup(dest)
    shutil.copy2(args.manifest, backup/'manifest.json')
    client = requests.Session()
    base = args.url.rstrip('/')
    status = client.get(base+'/api/session', timeout=30).json()
    if not status.get('demo_mode'):
        raise RuntimeError('this tool requires the isolated demo service')
    def post(path, body, expected=200):
        token = client.get(base+'/api/session', timeout=30).json()['csrf']
        r = client.post(base+path, json=body, headers={'Origin': base, 'X-CSRF-Token': token}, timeout=60)
        if r.status_code != expected:
            raise RuntimeError(f'{path}: HTTP {r.status_code}')
        return r.json()
    post('/api/demo/select', {'user_id': roster['accounts'][0]['id']})
    jobs = []
    for body in bodies:
        job = post('/api/admin/documents', body, 202)['job']
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            r = client.get(base+'/api/admin/document-updates/'+job['id'], timeout=30)
            r.raise_for_status(); job = r.json()['job']
            if job['state'] == 'ready':
                break
            if job['state'] == 'failed':
                raise RuntimeError('document publication failed; use the recorded job and backup to recover: '+job['id'])
            time.sleep(.4)
        else:
            raise TimeoutError('document update timed out: '+job['id'])
        jobs.append(job['id'])
    # Restore only this employee's original own mapping, never another person's identity.
    user = next(u for u in identities.users() if u['id'] == employee['id'])
    binding = next(b for b in user['bindings'] if b['corpus'] == manifest['corpus'] and b['principal_id'] == manifest['employee_source_principal'])
    if not binding['enabled']:
        post('/api/admin/permissions', {'action':'binding','user_id':employee['id'],'corpus':manifest['corpus'], 'principal_id':manifest['employee_source_principal'],'enabled':True})
    if user['clearance'] != manifest['employee_clearance']:
        post('/api/admin/permissions', {'action':'account','user_id':employee['id'],'clearance':manifest['employee_clearance']})
    if other_documents_digest(db_path, manifest['corpus'], selected) != before:
        raise RuntimeError('a document outside the explicit allowlist changed')
    result = {'scenario_id':manifest['scenario_id'],'updated_documents':[b['doc_id'] for b in bodies], 'jobs':jobs,'other_documents_unchanged':True,'backup':str(backup)}
    (backup.parent/'applied.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    main()
