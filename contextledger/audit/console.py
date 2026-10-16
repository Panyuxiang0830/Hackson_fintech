"""Administrator audit views over verified immutable events.

The temporary SQLite index is rebuilt from one verified chain snapshot. It is
not a second durable ledger; counts and cursor pages share that same snapshot.
"""
from __future__ import annotations

import base64
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import hashlib
import json
import re
import sqlite3

from contextledger.audit.chain import AuditIntegrityError
from contextledger.audit.query import time_bounds, TIME_HINT_RE

CATEGORIES = ('access', 'permissions', 'updates', 'violations', 'system')
FILTERS = {'category','actor','target','subject','keyword','source','project','document',
           'event_type','outcome','start','end','request_id','sequence','cursor','limit'}
SGT = timezone(timedelta(hours=8))


def category(kind):
    if kind in {'search','answer','document_open','answer_discarded'}:
        return 'access'
    if kind.startswith('permission_change'):
        return 'permissions'
    if kind.startswith('document_update_'):
        return 'updates'
    if kind in {'access_denied','unauthenticated_request','csrf_rejected','tool_auth_denied','tool_access_denied'}:
        return 'violations'
    return 'system'


def outcome(event):
    kind, decision = event.get('event_type',''), event.get('decision','')
    if kind.endswith('_failed'):
        return 'failed'
    if kind == 'document_update_ready':
        return 'published'
    if kind.endswith('_intent') or kind == 'document_update_retry':
        return 'pending'
    if category(kind) == 'violations':
        return 'blocked'
    return decision or 'recorded'


def iso(value):
    try:
        dt = datetime.fromisoformat(value.replace('Z','+00:00'))
        if dt.tzinfo is None:
            raise ValueError()
        return dt.astimezone(timezone.utc).isoformat()
    except (ValueError, AttributeError, OverflowError) as error:
        raise ValueError('audit time requires an ISO timestamp with timezone') from error


def name(value):
    return re.sub(r'[（(]演示员工[）)]','',value or '').strip()


def normalize(event, people, documents):
    item = dict(event)
    change = item.get('change') or {}
    actor_id, target_id = item.get('user_id',''), change.get('user_id') or item.get('target_user_id','')
    kind = item.get('event_type','unknown')
    item.update(category=category(kind), outcome=outcome(item), actor_id=actor_id,
                user_name=item.get('actor_name') or people.get(actor_id, actor_id or 'Unknown actor'),
                target_user_id=target_id,
                target_user_name=item.get('target_user_name') or people.get(target_id,target_id),
                redacted=False, evidence_visibility='visible' if item.get('evidence') else 'not_recorded')
    resources=[]
    for evidence in item.get('evidence',[]):
        entry=dict(evidence);current=documents.get((entry.get('corpus'),entry.get('doc_id')), {})
        for field in ('title','source','project','project_name'):
            if field not in entry and current.get(field):
                entry[field]=current[field];entry['label_basis']='current directory; historical ID/version retained'
        resources.append(entry)
    if item.get('doc_id') or item.get('requested_document_id'):
        doc_id=item.get('doc_id') or item['requested_document_id'];current=documents.get((item.get('corpus'),doc_id),{})
        resources.append({'doc_id':doc_id,'corpus':item.get('corpus'),**{k:current[k] for k in ('title','source','project','project_name') if current.get(k)}})
    item['evidence'] = resources if event.get('evidence') else []
    item['resources']=resources
    item['returned_evidence_count']=len(event.get('evidence',[]))
    item['retrieved_document_ids']=event.get('retrieved_document_ids',[])
    sources={r['source'] for r in resources if isinstance(r.get('source'),str)}
    projects={r['project'] for r in resources if isinstance(r.get('project'),str) and r['project']}
    if item.get('source'):sources.add(item['source'])
    if change.get('kind')=='source' and change.get('value'):sources.add(change['value'])
    if change.get('project'):projects.add(change['project'])
    if change.get('kind')=='project' and change.get('value'):projects.add(change['value'])
    item['sources'],item['projects']=sorted(sources),sorted(projects)
    if item['category']=='updates':
        item['before_version_status']=('new_resource' if item.get('before_version') is None else 'recorded') if 'before_version' in item else 'not_recorded'
    if item['category']=='permissions':
        obj=change.get('project') or change.get('value') or change.get('principal_id') or change.get('action','permissions')
        item['summary']=f"{name(item['user_name'])} → {name(item['target_user_name'])}: {obj}"
        item['change_recording']='before/after recorded' if 'before' in change and 'after' in change else 'Historical before/after not recorded'
    elif item['category']=='updates':
        item['summary']=f"{name(item['user_name'])}: {item.get('doc_id') or item.get('job_id','Update')} · {item['outcome']}"
    elif item['category']=='violations':
        item['summary']=f"{name(item['user_name'])}: {item.get('endpoint') or item.get('tool') or kind} · blocked"
        item['severity']='unauthorised attempt'  # A recorded denial is not proof of a successful breach.
    else:
        item['summary']=item.get('query') or (resources[0].get('title') or resources[0]['doc_id'] if resources else kind.replace('_',' '))
    return item


def select(store, db_path, identities, filters):
    """Bounded pages and exact SQL aggregates; immutable snapshot cursor."""
    if set(filters)-FILTERS:
        raise ValueError('unsupported audit filter')
    f={k:v for k,v in filters.items() if v not in (None,'')}
    for k,v in f.items():
        if k not in {'limit','sequence'} and (not isinstance(v,str) or len(v)>4000):
            raise ValueError('invalid audit filter')
    try:limit=int(f.pop('limit',25));sequence=int(f.pop('sequence',0))
    except (ValueError,TypeError):raise ValueError('invalid audit page')
    if not 1<=limit<=100 or sequence<0:raise ValueError('invalid audit page')
    cursor=f.pop('cursor',None)
    for k in ('start','end'):
        if k in f:f[k]=iso(f[k])
    if f.get('start') and f.get('end') and f['start']>f['end']:raise ValueError('audit range is reversed')
    signature=hashlib.sha256(json.dumps(f,sort_keys=True).encode()).hexdigest()
    people={p['id']:p['name'] for p in identities.users()}
    with store.db() as ledger:
        ledger.execute('BEGIN');verified=store._verify(ledger)
        if not verified.valid:raise AuditIntegrityError(verified.error)
        raw=[json.loads(r[0]) for r in ledger.execute('SELECT payload FROM events ORDER BY sequence')]
    as_of=verified.event_count;before=as_of+1
    if cursor:
        try:
            page=json.loads(base64.urlsafe_b64decode(cursor.encode()))
            if page['filter']!=signature or not 0<=page['as_of']<=as_of or not 0<page['before']<=page['as_of']+1:raise ValueError()
            as_of,before=page['as_of'],page['before']
        except (ValueError,KeyError,TypeError):raise ValueError('invalid audit cursor')
    documents={}
    needed={(r.get('corpus') or e.get('corpus'),r['doc_id']) for e in raw if e['sequence']<=as_of for r in e.get('evidence',[]) if r.get('doc_id')}
    needed.update((e.get('corpus'),e.get('doc_id') or e.get('requested_document_id')) for e in raw if e['sequence']<=as_of and (e.get('doc_id') or e.get('requested_document_id')))
    keys=list(needed)
    with sqlite3.connect('file:'+str(db_path)+'?mode=ro',uri=True) as content:
        for offset in range(0,len(keys),350):
            batch=keys[offset:offset+350]
            sql='SELECT corpus,doc_id,title,source,extra_json FROM documents WHERE (corpus,doc_id) IN ('+','.join('(?,?)' for _ in batch)+')'
            for corpus,doc_id,title,source,extra in content.execute(sql,[v for pair in batch for v in pair]):
                m=json.loads(extra);documents[(corpus,doc_id)]={'title':title,'source':source,'project':m.get('project'),'project_name':m.get('project_name')}
    # Link new stages by operation ID. Legacy adjacent matching is derived only,
    # never written back into the historical ledger.
    terminal_ops={e.get('operation_id') for e in raw if e['sequence']<=as_of and e.get('event_type') in {'permission_change','permission_change_failed'}}-{None}
    terminal_jobs={e.get('job_id') for e in raw if e['sequence']<=as_of and e.get('event_type') in {'document_update_ready','document_update_failed'}}-{None}
    rows=[]
    for index,event in enumerate(raw):
        if event['sequence']>as_of:continue
        kind=event.get('event_type','')
        if kind=='permission_change_intent' and not sequence and not f.get('request_id'):
            nxt=raw[index+1] if index+1<len(raw) and raw[index+1]['sequence']<=as_of else {}
            if event.get('operation_id') in terminal_ops or (not event.get('operation_id') and nxt.get('event_type')=='permission_change' and nxt.get('user_id')==event.get('user_id') and nxt.get('change')==event.get('change')):continue
        if not sequence and not f.get('request_id') and kind in {'document_update_intent','document_update_publication_intent','document_update_retry'} and event.get('job_id') in terminal_jobs:continue
        e=normalize(event,people,documents)
        # Deliberately use full recorded question/answer and human directory labels.
        text=json.dumps(e,ensure_ascii=False).casefold()
        rows.append((e['sequence'],e['category'],e.get('event_type'),e['actor_id'],e['target_user_id'],
                     e['outcome'],iso(e['timestamp']),text,json.dumps(e,ensure_ascii=False)))
    with sqlite3.connect(':memory:') as db:
        db.execute('CREATE TABLE selection(seq INTEGER PRIMARY KEY, category TEXT, kind TEXT, actor TEXT, target TEXT, outcome TEXT, ts TEXT, text TEXT, payload TEXT)')
        db.executemany('INSERT INTO selection VALUES (?,?,?,?,?,?,?,?,?)',rows)
        clauses=['1'];params=[]
        if sequence:clauses.append('seq=?');params.append(sequence)
        for key,column in (('actor','actor'),('target','target'),('request_id',"json_extract(payload,'$.request_id')")):
            if f.get(key):clauses.append(f'{column}=?');params.append(f[key])
        if f.get('subject'):
            clauses.append('(actor=? OR target=?)');params.extend([f['subject']]*2)
        for key,column in (('category','category'),('event_type','kind'),('outcome','outcome')):
            if f.get(key) and f[key]!='all':
                values=f[key].split(',')
                if len(values)>30:raise ValueError('too many audit filter values')
                if key=='category' and not set(values)<=set(CATEGORIES):raise ValueError('unknown audit category')
                clauses.append(f"{column} IN ({','.join('?'*len(values))})");params.extend(values)
        for key,sign in (('start','>='),('end','<=')):
            if f.get(key):clauses.append(f'ts{sign}?');params.append(f[key])
        for word in f.get('keyword','').casefold().split():
            clauses.append('instr(text,?)>0');params.append(word)
        for key,path in (('source','sources'),('project','projects')):
            if f.get(key):
                clauses.append(f"EXISTS (SELECT 1 FROM json_each(payload,'$.{path}') WHERE value=?)");params.append(f[key])
        if f.get('document'):
            clauses.append("EXISTS (SELECT 1 FROM json_each(payload,'$.resources') WHERE instr(lower(json_extract(value,'$.doc_id')),lower(?))>0)");params.append(f['document'])
        where=' AND '.join(clauses)
        total=db.execute('SELECT COUNT(*) FROM selection WHERE '+where,params).fetchone()[0]
        stats={}
        for field in ('category','kind','outcome','actor','target'):
            stats[field]={k:n for k,n in db.execute('SELECT '+field+',COUNT(*) FROM selection WHERE '+where+' GROUP BY '+field,params)}
        stats['by_category']={}
        for cat,n in stats['category'].items():
            grouped={'total_count':n}
            for field in ('kind','outcome','actor','target'):
                grouped[field]={key:count for key,count in db.execute('SELECT '+field+',COUNT(*) FROM selection WHERE '+where+' AND category=? GROUP BY '+field,[*params,cat])}
            stats['by_category'][cat]=grouped
        page=[json.loads(r[0]) for r in db.execute('SELECT payload FROM selection WHERE '+where+' AND seq<? ORDER BY seq DESC LIMIT ?',[*params,before,limit+1])]
        has_more=len(page)>limit;page=page[:limit]
        samples=[]
        for cat in stats['category']:
            samples.append([json.loads(r[0]) for r in db.execute('SELECT payload FROM selection WHERE '+where+' AND category=? ORDER BY seq DESC LIMIT ?', [*params,cat,max(1,20//len(stats['category']))])])
        # Spend the model detail budget across categories before taking more
        # records from one category; long answers must not hide all changes.
        sample=[rows[i] for i in range(max(map(len,samples),default=0)) for rows in samples if i<len(rows)]
    next_cursor=None
    if has_more:
        next_cursor=base64.urlsafe_b64encode(json.dumps({'filter':signature,'as_of':as_of,'before':page[-1]['sequence']}).encode()).decode()
    return {'events':page,'total_count':total,'statistics':stats,'next_cursor':next_cursor,'_model_events':sample,
            'selection':{'filters':f,'returned_count':len(page),'total_count':total,'limit':limit,
                         'snapshot_sequence':as_of,'truncated':has_more,'not_whole_period_statistics':False,
                         'statistics_scope':'all matching events in the verified snapshot','timezone':'Asia/Singapore'},
            'integrity':asdict(verified)}


def question_filters(question, identities, projects=(), *, now=None, parse_time=True):
    """Explicit bounded audit intents; no model-generated SQL or identities."""
    if not isinstance(question,str) or not 1<=len(question.strip())<=4000:raise ValueError('audit question required')
    text=question.casefold();result={}
    access=bool(re.search(r'访问|读取|搜索|提问|回答|打开|获取|查过|查询|access|search|ask|answer|read|open',text))
    permissions=bool(re.search(r'权限|撤[销权]|成员|密级|部门|permission|revok|membership|clearance',text))
    updates=bool(re.search(r'更新|发布|同步|update|publish|sync',text))
    violations=bool(re.search(r'越权|违规|未授权|没有权限的管理|异常|unauthori[sz]ed|violation|denied|breach|blocked',text))
    categories=[]
    if violations and not (updates or re.search(r'权限变更|权限变化|permission changes|compare|对照',text)):
        categories=['violations']
    else:
        if access:categories.append('access')
        if permissions:categories.append('permissions')
        if updates:categories.append('updates')
        if violations:categories.append('violations')
    result['category']=','.join(categories) or 'access,permissions,updates,violations'
    for p in identities.users():
        label=name(p['name']).casefold()
        if p['id'].casefold() in text or (label and re.search(r'(?<![a-z])'+re.escape(label)+r'(?![a-z])',text)):
            result['subject']=p['id'];break
    # Source narrows a single-domain question; cross-domain comparison must also
    # retain access events without evidence/source, such as a zero-evidence answer.
    if len(categories)==1:
        for source in ('slack','jira','confluence','google_drive'):
            if source.replace('_',' ') in text or source in text:result['source']=source;break
    if not (access and permissions):
        for project in projects:
            label=project['name'].casefold();first=label.split()[0]
            if project['id'].casefold() in text or label in text or (len(first)>4 and first in text):result['project']=project['id'];break
    if updates and re.search(r'失败|failed|failure',text):result['outcome']='failed'
    now=now or datetime.now(timezone.utc)
    if not parse_time:return result
    if re.search(r'今天|昨天|\btoday\b|\byesterday\b',text):
        local=now.astimezone(SGT);start=local.replace(hour=0,minute=0,second=0,microsecond=0)
        if re.search(r'昨天|\byesterday\b',text):start-=timedelta(days=1);end=start+timedelta(days=1)-timedelta(microseconds=1)
        else:end=local
        result.update(start=iso(start.isoformat()),end=iso(end.isoformat()))
    elif TIME_HINT_RE.search(text):
        start,end=time_bounds(question,now)
        if start:result.update(start=start,end=end)
    return result
