"""Fixed authorised Radar synthesis inputs; not end-to-end retrieval latency."""
from __future__ import annotations
import argparse,copy,hashlib,json,os,sys,time
from pathlib import Path
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
from contextledger.paths import PROJECT_ROOT
ROOT = PROJECT_ROOT


def run(args):
    from dotenv import load_dotenv
    load_dotenv(args.env_file, override=True)
    if not os.getenv('LLM_API_KEY') or os.getenv('LLM_PROVIDER') != 'openai_compatible': raise ValueError('A real compatible model is required')
    from qdrant_client import QdrantClient
    from contextledger.evaluation.radar_demo import publish
    from contextledger.radar.data import load_records,source_documents
    from contextledger.storage.models import Principal
    from contextledger.storage.store import connect,init_db,insert_principals
    from contextledger.access.identity_store import IdentityStore
    from contextledger.retrieval.filtered_index import FilteredIndex
    from contextledger.audit.store import AuditStore
    from contextledger.application.service import UnifiedService
    from contextledger.radar.tool import DecisionRadarTool
    from contextledger.radar.protocol import identifiers
    from contextledger.answering.service import AnswerService
    from contextledger.answering.models import User,Document,Evidence
    root=ROOT;out=args.out
    if out.exists():raise ValueError('New output required')
    out.mkdir(parents=True)
    (out/'evaluator.py').write_bytes(Path(__file__).read_bytes())
    db_path=out/'content/canonical.sqlite'
    with connect(db_path) as db:
     init_db(db);insert_principals(db,[Principal('orgforge','radar:engineering','Radar Engineer','engineer','engineering'),Principal('orgforge','radar:support','Radar Support','support','support')],{});db.commit()
    ids=IdentityStore(out/'security/identities.sqlite');actor=ids.register('https://latency.fixture','engineer','Radar Engineer');ids.bind(actor.id,'orgforge','radar:engineering',True)
    manifest=json.loads((root/'fixtures/radar/manifest.json').read_text());records=[]
    for item in manifest['cases'].values():records+=load_records(root/'fixtures/radar'/item['file'])
    client=QdrantClient(':memory:');publish(db_path,client,source_documents(records,final=True))
    index=FilteredIndex(db_path,client,ids,embed=lambda q:[1.,0.]);service=UnifiedService(index,ids,AuditStore(out/'security/audit.sqlite'))
    actor=ids.get(actor.id);scope=index.scope(actor,'orgforge');user=User(actor.id,actor.name,'engineering',actor.role,'internal')
    questions=[('customer_links','ZD-101、ENG-210、PR-139 的客户反馈与处理过程如何关联？请保留未确认的部分。'),('recurrence','ENG-112、ENG-263、PR-159 的方案如何演变？分区数与相关文档是否存在不一致？')]
    questions=[item for item in questions if item[0] in args.cases]
    frozen={}
    for cid,q in questions:
     seeds,generation=index.search(scope,identifiers(q)[0],mode='keyword',limit=5)
     selected,report=DecisionRadarTool(index).execute(query=q,scope=scope,generation=generation,seeds=seeds,arguments={'anchor_ids':identifiers(q),'focus':['history','relationships','conflicts','current_status']},guard=lambda:service.fence(actor,'orgforge',generation,seeds))
     budget=24000//len(selected);evidence=[]
     for hit in selected:
      document=Document(hit['doc_id'],hit['source'],hit['title'],hit['text'][:min(4000,budget)],'engineering','unknown','unknown',hit['indexed_at'],'internal',status='historical' if hit['metadata'].get('historical_revision') else 'active')
      evidence.append(Evidence(document,1.,'source ACL snapshot AND local restrictions','consistent_with_offline_snapshot','Live source freshness is unknown.'))
     report['coverage']['evidence_excerpts_truncated']=any(len(h['text'])>len(e.document.content) for h,e in zip(selected,evidence))
     model_report={**report,'event_candidates':[{k:v for k,v in e.items() if k in {'citation_id','type','event_time','historical'}} for e in report['event_candidates']], 'source_statuses':[{k:v for k,v in e.items() if k in {'citation_id','native_status','historical','supported_fact'}} for e in report['source_statuses'] if e['record_type']=='native_state']}
     frozen[cid]=(q,evidence,model_report,generation,selected)
     (out/(cid+'-input.json')).write_text(json.dumps({'question':q,'tool_report':model_report,'evidence':[{'citation_id':i,'doc_id':e.document.id,'title':e.document.title,'content':e.document.content} for i,e in enumerate(evidence,1)]},ensure_ascii=False,indent=2))
     print('Frozen',cid,len(evidence),'authorised records',flush=True)
    import urllib.request
    original_transport=urllib.request.urlopen
    def transport(request,*pos,**kw):
     if args.schema and getattr(request,'data',None) and request.full_url.endswith('/chat/completions'):
      body=json.loads(request.data)
      count=len(json.loads(body['messages'][1]['content'])['authorised_evidence'])
      body['response_format']={'type':'json_schema','json_schema':{'name':'grounded_answer','strict':True,'schema':{
       'type':'object','properties':{'status':{'type':'string','enum':['answered','insufficient']},'answer':{'type':'string'},'citation_ids':{'type':'array','items':{'type':'integer','enum':list(range(1,count+1))}},'uncertainty':{'type':'string','enum':['low','medium','high']}},
       'required':['status','answer','citation_ids','uncertainty'],'additionalProperties':False}}}
      body['provider']={'require_parameters':True}
      request.data=json.dumps(body).encode()
     return original_transport(request,*pos,**kw)
    urllib.request.urlopen=transport
    rows=[]
    def call(job):
     cid,effort,repeat=job;q,evidence,report,generation,selected=frozen[cid]
     answer=AnswerService();answer.radar_reasoning=effort;original=answer._openai_compatible;completion=answer._completion;calls=[]
     guard=lambda:service.fence(actor,'orgforge',generation,selected)
     def synth(u,question,ev,**kwargs):return original(u,question,ev,tool_handler=lambda args:None,tool_state={'called':True,'result':copy.deepcopy(report)},before_call=guard)
     def capture(system,payload):
      digest=hashlib.sha256(json.dumps({'system':system,'payload':payload},ensure_ascii=False,sort_keys=True).encode()).hexdigest();start=time.perf_counter()
      try:return completion(system,payload)
      finally:calls.append({'input_sha256':digest,'latency_ms':round((time.perf_counter()-start)*1000,2)})
     start=time.perf_counter()
     with patch.object(answer,'_openai_compatible',side_effect=synth),patch.object(answer,'_completion',side_effect=capture):text,decision,provider=answer.answer(user,q,evidence,before_call=guard,tool_handler=lambda args:None)
     row={'case':cid,'effort':effort,'repeat':repeat,'documents':len(evidence),'elapsed_seconds':round(time.perf_counter()-start,3),'answer':text,'decision':decision,'provider':provider,'diagnostics':answer.last_diagnostics,'calls':calls,'strict_passed':decision=='answered' and provider.startswith('openai_compatible/'),'semantic_review':'pending human reading; citation scope is not semantic verification'}
     print(json.dumps({k:row[k] for k in ['case','effort','repeat','elapsed_seconds','strict_passed']},ensure_ascii=False),flush=True)
     return row
    protocol={'model':os.getenv('LLM_MODEL'),'scope':'Fixed final synthesis inputs only; tool selection and retrieval excluded from timed request','synthetic_source':manifest,'max_tokens':6000,'repeats':args.repeats,'workers':args.workers,'effective_concurrency':min(args.workers,len(args.efforts)),'efforts':args.efforts,'schema':args.schema,'experimental_none': 'none' in args.efforts,'embedding_note':'Constant fixture vectors for freezing authorised evidence, not retrieval-performance evidence'}
    (out/'protocol.json').write_text(json.dumps(protocol,ensure_ascii=False,indent=2))
    try:
     for repeat in range(args.repeats):
      for cid,_ in questions:
       efforts=args.efforts if repeat%2==0 else list(reversed(args.efforts))
       with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for row in pool.map(call,[(cid,e,repeat) for e in efforts]):
         rows.append(row)
         with (out/'results.jsonl').open('a') as f:f.write(json.dumps(row,ensure_ascii=False)+'\n')
    finally:
     urllib.request.urlopen=original_transport
     client.close()
    print('Completed',len(rows),'fixed-input synthesis observations',flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--env-file',type=Path,required=True)
    parser.add_argument('--cases',nargs='+',choices=['customer_links','recurrence'],default=['customer_links','recurrence'])
    parser.add_argument('--efforts',nargs='+',choices=['high','low','none'],default=['high','low'])
    parser.add_argument('--repeats',type=int,default=2)
    parser.add_argument('--workers',type=int,default=2)
    parser.add_argument('--schema',action='store_true',help='Experimental JSON schema plus require_parameters provider routing')
    args=parser.parse_args()
    if args.repeats<2 or not 1<=args.workers<=2: parser.error('At least two repeats and one or two workers are required')
    run(args)


if __name__=='__main__':main()
