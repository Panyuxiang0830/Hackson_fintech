#!/usr/bin/env python3
"""Isolated four-case replay with real SQLite/Qdrant and fixture embeddings.

No LLM is used here: this measures retrieval/tool/publication behavior, not model
routing or reasoning quality. Run the web service on --output for real-model QA.
"""
from __future__ import annotations
import argparse
import json
import sys
import time
import uuid
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from qdrant_client import QdrantClient, models as qm
from contextledger.radar_data import load_records, source_documents, canonical_documents
from contextledger.radar_store import SourceRevisionStore
from contextledger.radar_tool import DecisionRadarTool
from contextledger.radar_protocol import identifiers
from contextledger.models import Principal
from contextledger.store import connect, init_db, insert_documents, insert_principals
from contextledger.filtered_index import FilteredIndex, prepare_snapshot, payload_for, point_id
from contextledger.identity_store import IdentityStore
from contextledger.audit_store import AuditStore
from contextledger.unified_service import UnifiedService, validate_security_path


def publish(db_path, client, documents):
    """Whole-snapshot gate: readers fail closed during mutation/vector publication."""
    docs, chunks = canonical_documents(documents)
    generation = str(uuid.uuid4())
    collection = "radar_" + generation.replace("-", "")
    with connect(db_path) as db:
        state = db.execute("SELECT name FROM sqlite_master WHERE name='cl_index_state'").fetchone()
        if state:
            db.execute("UPDATE cl_index_state SET state='building'")
            db.commit()
        with db:
            for table in ('documents', 'chunks', 'docs_fts'):
                db.execute("DELETE FROM " + table)
            insert_documents(db, docs, chunks)
            prepare_snapshot(db, collection, generation, "radar-fixture-constant-vector", 2)
        client.create_collection(collection, vectors_config=qm.VectorParams(size=2, distance=qm.Distance.COSINE))
        points = []
        for chunk in db.execute("SELECT * FROM chunks"):
            meta = db.execute("SELECT * FROM cl_metadata WHERE corpus=? AND doc_id=?", (chunk['corpus'],chunk['doc_id'])).fetchone()
            points.append(qm.PointStruct(id=point_id(chunk['corpus'],chunk['doc_id'],meta['version'],chunk['chunk_id']),
                                        vector=[1.,0.],payload=payload_for(chunk,meta)))
        if points:
            client.upsert(collection, points, wait=True)
        db.execute("UPDATE cl_index_state SET state='ready'")
        db.commit()
    return generation


def replay(output, fixture_dir, *, live_llm=False):
    output = Path(output)
    if output.exists():
        raise ValueError("Replay output must be a new directory; existing data is never replaced")
    validate_security_path(output/'content', output/'security')
    output.mkdir(parents=True)
    db_path = output/'content'/'canonical.sqlite'
    with connect(db_path) as db:
        init_db(db)
        insert_principals(db, [Principal('orgforge','radar:engineering','Radar Engineer','engineer','engineering'),
                               Principal('orgforge','radar:support','Radar Support','support','support')], {})
        db.commit()
    ids = IdentityStore(output/'security'/'identities.sqlite')
    actor = ids.register('https://radar.fixture','engineer','Radar Engineer')
    ids.bind(actor.id,'orgforge','radar:engineering',True)
    client = QdrantClient(path=str(output/'content'/'qdrant'))
    try:
        index = FilteredIndex(db_path,client,ids,embed=lambda q:[1.,0.])
        service = UnifiedService(index,ids,AuditStore(output/'security'/'audit.sqlite'))
        archive = SourceRevisionStore()
        all_records = []
        manifest = json.loads((Path(fixture_dir)/'manifest.json').read_text())
        for case in manifest['cases'].values():
            all_records += load_records(Path(fixture_dir)/case['file'])
        snapshots = [('early','2026-01-20T23:59:59Z',False),('middle','2026-02-15T23:59:59Z',False),('final',None,True)]
        reports=[]
        for phase, cutoff, final in snapshots:
            docs=source_documents(all_records,cutoff=cutoff,final=final)
            for doc in docs:
                archive.observe(doc,observed_at=cutoff or 'final offline snapshot')
            documents=docs+archive.documents(docs)
            started=time.monotonic()
            generation=publish(db_path,client,documents)
            elapsed=round((time.monotonic()-started)*1000,1)
            for name, case in manifest['cases'].items():
                actor=ids.get(actor.id)
                scope=index.scope(actor,'orgforge')
                query=case['anchor_ids'][0]
                seeds, gen=index.search(scope,query,mode='keyword',limit=5)
                if not seeds:
                    radar={'coverage':{'documents':0,'scope':'current replay phase'},'entity_candidates':[query]}
                else:
                    _,radar=DecisionRadarTool(index).execute(query=query,scope=scope,generation=gen,
                        seeds=seeds,arguments={'anchor_ids':[query],'focus':['history','conflicts']},
                        guard=lambda:service.fence(actor,'orgforge',gen,seeds))
                reports.append({'phase':phase,'case':name,'generation':generation,'publish_ms':elapsed,'radar':radar})
        live_results=[]
        if live_llm:
            from src.answering import AnswerService
            if AnswerService().provider != 'openai_compatible':
                raise ValueError('Real model validation requires existing LLM configuration')
            questions=[
                ('01-dashboard-review','ENG-195 与 PR-135 的评审和批准过程如何发展？哪些信息能够确认，哪些仍有缺口？'),
                ('02-kafka-incident','ENG-123 与 PR-109 的处理过程是什么？现有证据能否确认生产回滚和服务恢复？'),
                ('03-customer-incident','ZD-101、ENG-210、PR-139 的客户反馈与处理过程如何关联？请保留未确认的部分。'),
                ('04-recurrence-revision','ENG-112、ENG-263、PR-159 的方案如何演变？分区数与相关文档是否存在不一致？'),
                ('direct-control','ENG-195 的标题是什么？只回答标题。')]
            for case, question in questions:
                started=time.monotonic()
                result,_=service.ask(actor.id,'orgforge',question,mode='keyword',planning=True)
                result['elapsed_seconds']=round(time.monotonic()-started,2)
                live_results.append({'case':case,'question':question,'result':result})
                print('Real model:',case,result['provider'],result['decision'],
                      'radar',bool(result.get('radar')),'seconds',result['elapsed_seconds'],flush=True)
        report={'dataset':manifest,'transport':'tool-only; no LLM; constant fixture embeddings',
                'phases':reports,'live_model_samples':live_results,'quality_claim':'Real model samples require human semantic assessment; no unseen-case quality validation.' if live_results else 'No real-model or unseen-case quality validation.'}
        (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
        return report
    finally:
        client.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--fixtures',type=Path,default=Path(__file__).resolve().parents[1]/'fixtures/radar')
    parser.add_argument('--live-llm',action='store_true',help='Use configured real LLM for four questions plus a direct control; API usage applies')
    args=parser.parse_args()
    if args.live_llm:
        from dotenv import load_dotenv
        load_dotenv()
    result=replay(args.output,args.fixtures,live_llm=args.live_llm)
    for item in result['phases']:
        print(item['phase'],item['case'],item['radar']['coverage'])
    print('Report:',args.output/'report.json')
