#!/usr/bin/env python3
"""Preflight or publish a reviewed project catalog through the admin API."""
import argparse
import json
from pathlib import Path
import shutil
import sqlite3
import sys
import time
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import requests
from contextledger.access.project_permissions import plan_project_annotations
from contextledger.application.service import validate_security_path
from scripts.apply_demo_permissions import other_documents_digest


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out',type=Path,required=True);p.add_argument('--security-dir',type=Path,required=True)
    p.add_argument('--manifest',type=Path,required=True);p.add_argument('--url',default='http://127.0.0.1:17866')
    p.add_argument('--apply',action='store_true');args=p.parse_args()
    parsed=urlparse(args.url)
    if parsed.scheme!='http' or parsed.hostname not in {'127.0.0.1','localhost'} or parsed.path not in {'','/'} or parsed.username or parsed.password or parsed.query or parsed.fragment:
        p.error('explicit loopback URL required')
    validate_security_path(args.out,args.security_dir)
    db_path=args.out/'canonical.sqlite';manifest=json.loads(args.manifest.read_text());corpus=manifest['corpus']
    with sqlite3.connect('file:'+str(db_path)+'?mode=ro',uri=True) as db:
        db.row_factory=sqlite3.Row
        rows=[dict(r) for r in db.execute('SELECT * FROM documents WHERE corpus=?',(corpus,))]
        if db.execute("SELECT 1 FROM cl_update_jobs WHERE state IN ('queued','running','failed') LIMIT 1").fetchone():
            raise RuntimeError('finish pending document updates first')
    bodies=plan_project_annotations(manifest,rows)
    selected={e['doc_id'] for project in manifest['projects'] for e in project['documents']}
    before=other_documents_digest(db_path,corpus,selected)
    project_ids={v['id'] for v in manifest['projects']}
    roster=json.loads((args.security_dir/'demo-roster.json').read_text())
    accounts={(a.get('source') or {}).get('principal_id'):a['id'] for a in roster['accounts']}
    for member in manifest.get('initial_memberships',[]):
        if member['principal_id'] not in accounts or not set(member['projects'])<=project_ids:
            raise ValueError('unknown initial member/project')
    print(json.dumps({'dry_run':not args.apply,'projects':len(project_ids),'updates':[b['doc_id'] for b in bodies]}),flush=True)
    if not args.apply:return
    backup=args.security_dir.parent/'project-permissions'/('backup-'+str(time.time_ns()));backup.mkdir(parents=True,mode=0o700)
    (backup/'documents.json').write_text(json.dumps([r for r in rows if r['doc_id'] in selected],ensure_ascii=False,indent=2))
    for name in ('identities.sqlite','audit.sqlite'):
        with sqlite3.connect('file:'+str(args.security_dir/name)+'?mode=ro',uri=True) as src,sqlite3.connect(backup/name) as dst:src.backup(dst)
    shutil.copy2(args.manifest,backup/'manifest.json')
    s=requests.Session();s.trust_env=False;url=args.url.rstrip('/')
    status=s.get(url+'/api/session',timeout=20).json()
    if not status.get('demo_mode'):raise RuntimeError('this operator tool requires the isolated service')
    def post(path,body,status=200):
        token=s.get(url+'/api/session',timeout=20).json()['csrf']
        r=s.post(url+path,json=body,headers={'Origin':url,'X-CSRF-Token':token},timeout=60)
        if r.status_code!=status:raise RuntimeError(f'{path}: HTTP {r.status_code}: {r.text[:200]}')
        return r.json()
    admin=next(a['id'] for a in roster['accounts'] if a['subject']=='administrator')
    post('/api/demo/select',{'user_id':admin})
    for project in manifest['projects']:
        post('/api/admin/permissions',{'user_id':admin,'action':'project_catalog','corpus':corpus,'project':project['id'],'name':project['name']})
    jobs=[]
    for body in bodies:
        job=post('/api/admin/documents',body,202)['job'];deadline=time.monotonic()+180
        while time.monotonic()<deadline:
            r=s.get(url+'/api/admin/document-updates/'+job['id'],timeout=20);r.raise_for_status();job=r.json()['job']
            if job['state']=='ready':break
            if job['state']=='failed':raise RuntimeError('publication failed; recover recorded job '+job['id'])
            time.sleep(.4)
        else:raise TimeoutError('publication timed out: '+job['id'])
        jobs.append(job['id']);print(json.dumps({'ready':body['doc_id']}),flush=True)
    people=s.get(url+'/api/admin/users',timeout=20).json()
    for member in manifest.get('initial_memberships',[]):
        person=next(a for a in people if a['id']==accounts[member['principal_id']])
        for project_id in member['projects']:
            project=next(p for p in manifest['projects'] if p['id']==project_id)
            prior_denied=any(r['kind']=='project' and r['value']==project.get('previous_project') and r['corpus'] in {corpus,'*'} for r in person['restrictions'])
            if project_id not in person['projects'] and not prior_denied:
                post('/api/admin/permissions',{'user_id':person['id'],'action':'project_membership','corpus':corpus,'project':project_id,'enabled':True})
    if before!=other_documents_digest(db_path,corpus,selected):raise RuntimeError('unselected documents changed')
    result={'projects':len(project_ids),'updated_documents':[b['doc_id'] for b in bodies],'jobs':jobs,'other_documents_unchanged':True,'backup':str(backup)}
    (backup.parent/'applied.json').write_text(json.dumps(result,indent=2));print(json.dumps(result),flush=True)


if __name__=='__main__':main()
