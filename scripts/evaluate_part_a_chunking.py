"""Read-only chunking ablation: identical documents, model and search protocol."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from contextledger.evaluation import document_scores, load_questions, resources
from contextledger.models import SourceDoc
from contextledger.processors import CHUNKING_VERSION, MODEL_NAME, MODEL_REVISION, chunk_document
from contextledger.search import _fts_doc_ids, _partition, _rrf
from contextledger.store import chunk_digest, load_principal


def dedupe_neighbors(ids, distances, rows):
    best = {}
    for row_id, distance in zip(ids, distances):
        if row_id < 0:
            continue
        did = rows[int(row_id)]
        best[did] = max(best.get(did, float("-inf")), float(distance))
    return sorted(best, key=lambda did: (-best[did], did))


def validate_prepared_store(root, snapshot, code_digest, corpus="enterpriserag"):
    meta = json.loads((root / "manifest.json").read_text())["chunking"]
    expected = {"version": CHUNKING_VERSION, "max_tokens": 256, "overlap_tokens": 32,
                "contextual": True, "processor_sha256": code_digest}
    if any(meta.get(k) != v for k, v in expected.items()):
        raise ValueError("prepared chunks do not match the current processor")
    with sqlite3.connect((root / "canonical.sqlite").as_uri() + "?mode=ro", uri=True) as prepared:
        prepared.row_factory = sqlite3.Row
        if (resources(root, prepared)["store_sha256"] != snapshot or
                chunk_digest(prepared, corpus) != meta["corpora"][corpus]["chunks_sha256"]):
            raise ValueError("prepared source snapshot or chunk fingerprint differs")


def build_variant(source, directory, variant, model, signature, batch_size, prepared_store=None):
    import numpy as np

    directory.mkdir(parents=True, exist_ok=True)
    status_path = directory / "status.json"
    if status_path.exists():
        status = json.loads(status_path.read_text())
        if status.get("signature") == signature and status.get("complete"):
            return status
    data_path = directory / "chunks.sqlite"
    data_path.unlink(missing_ok=True)
    target = sqlite3.connect(data_path)
    target.execute("CREATE TABLE chunks(row_id INTEGER PRIMARY KEY,doc_id TEXT,text TEXT)")
    n = 0
    generation_started = time.perf_counter()
    if prepared_store is not None and variant == "contextual":
        with sqlite3.connect((prepared_store / "canonical.sqlite").as_uri() + "?mode=ro", uri=True) as prepared:
            for row in prepared.execute("SELECT doc_id,text FROM chunks WHERE corpus='enterpriserag' ORDER BY rowid"):
                target.execute("INSERT INTO chunks VALUES (?,?,?)", (n, row[0], row[1]))
                n += 1
        print(f"{variant}: reused {n} verified prepared chunks", flush=True)
    else:
        for i, row in enumerate(source.execute("SELECT * FROM documents WHERE corpus='enterpriserag' ORDER BY doc_id"), 1):
            doc = SourceDoc(row["corpus"], row["doc_id"], row["source"], row["title"], row["text"],
                            row["day"], row["ts"], row["dept"], [])
            pieces = chunk_document(doc, tokenizer=model.tokenizer, contextual=variant == "contextual")
            target.executemany("INSERT INTO chunks VALUES (?,?,?)", [(n + j, doc.doc_id, p.text) for j, p in enumerate(pieces)])
            n += len(pieces)
            if i % 5000 == 0:
                print(f"{variant}: segmented {i} docs, {n} chunks", flush=True)
    target.commit()
    segmentation_seconds = time.perf_counter() - generation_started
    matrix = np.memmap(directory / "embeddings.f32", mode="w+", dtype=np.float32, shape=(n, 384))
    started = time.perf_counter()
    seen, maximum, over_limit = 0, 0, 0
    cursor = target.execute("SELECT text FROM chunks ORDER BY row_id")
    while True:
        batch = cursor.fetchmany(batch_size)
        if not batch:
            break
        texts = [r[0] for r in batch]
        lengths = [len(ids) for ids in model.tokenizer(texts, truncation=False)["input_ids"]]
        maximum = max(maximum, max(lengths))
        over_limit += sum(length > model.max_seq_length for length in lengths)
        if over_limit:
            raise ValueError("new chunks exceed the actual embedding context")
        encoded = model.encode(texts, batch_size=batch_size, normalize_embeddings=True,
                               convert_to_numpy=True, show_progress_bar=False)
        matrix[seen:seen + len(batch)] = encoded
        seen += len(batch)
        if seen % (batch_size * 100) == 0 or seen == n:
            matrix.flush()
            print(f"{variant}: embedded {seen}/{n}", flush=True)
    matrix.flush()
    del matrix
    target.close()
    status = {"signature": signature, "complete": True, "rows": n,
              "max_input_tokens": maximum, "over_limit_chunks": over_limit,
              "segmentation_seconds": segmentation_seconds,
              "embedding_seconds": time.perf_counter() - started}
    status_path.write_text(json.dumps(status, indent=2) + "\n")
    return status


def measure(source, questions, model, query_vectors, directory, variant, status):
    import faiss
    import numpy as np

    n = status["rows"]
    matrix = np.memmap(directory / "embeddings.f32", mode="r", dtype=np.float32, shape=(n, 384))
    index = faiss.IndexFlatIP(384)
    index.add(matrix)
    if variant == "legacy":
        with sqlite3.connect(directory / "rows.sqlite") as mapping:
            rows = [r[0] for r in mapping.execute("SELECT doc_id FROM vec_rows ORDER BY row_id")]
    else:
        with sqlite3.connect(directory / "chunks.sqlite") as mapping:
            rows = [r[0] for r in mapping.execute("SELECT doc_id FROM chunks ORDER BY row_id")]
    if len(rows) != n:
        raise ValueError("vector row mapping does not match embeddings")
    started = time.perf_counter()
    distances, ids = index.search(query_vectors, min(1600, n))
    search_seconds = time.perf_counter() - started
    results = []
    for q, neighbors, scores in zip(questions, ids, distances):
        principal = load_principal(source, q.principal_id)
        keyword = _fts_doc_ids(source, q.corpus, q.text, 200)
        vector = dedupe_neighbors(neighbors[:80], scores[:80], rows)
        broad_vector = dedupe_neighbors(neighbors, scores, rows)
        allowed, _ = _partition(source, principal, list(dict.fromkeys(keyword + broad_vector)), q.as_of_day)
        visible = set(allowed)
        keyword = [did for did in keyword if did in visible]
        vector = [did for did in vector if did in visible]
        broad_vector = [did for did in broad_vector if did in visible]
        fused = _rrf([keyword, vector])
        document_vector = broad_vector[:80]
        document_fused = _rrf([keyword, document_vector])
        results.append({"question_id": q.question_id, "question_type": q.kind,
            "vector_recall10": document_scores(q.gold, vector, 10)["recall"],
            "hybrid_recall10": document_scores(q.gold, fused, 10)["recall"],
            "candidate_oracle": document_scores(q.gold, keyword + broad_vector, len(keyword) + len(broad_vector))["recall"],
            "document_budget_vector_recall10": document_scores(q.gold, document_vector, 10)["recall"],
            "document_budget_hybrid_recall10": document_scores(q.gold, document_fused, 10)["recall"],
            "visible_documents_at_chunk_budget": len(vector),
            "document_budget_hybrid_ids": document_fused[:10],
            "vector_document_ids": vector[:10], "hybrid_document_ids": fused[:10],
            "reference_document_ids": list(q.gold)})
    summary = {key: sum(r[key] for r in results) / len(results) for key in
               ("vector_recall10", "hybrid_recall10", "candidate_oracle",
                "document_budget_vector_recall10", "document_budget_hybrid_recall10", "visible_documents_at_chunk_budget")}
    return {"summary": summary, "index": status, "exact_search_seconds": search_seconds, "rows": results}


def run(args):
    import faiss
    import numpy as np
    import torch
    from sentence_transformers import SentenceTransformer

    torch.set_num_threads(8)
    faiss.omp_set_num_threads(8)
    out = args.out.resolve()
    cache = args.cache.resolve() if args.cache else Path(tempfile.mkdtemp(prefix="contextledger-chunking-"))
    cache.mkdir(parents=True, exist_ok=True)
    baseline = json.loads((out / "evaluation.json").read_text())
    all_questions, provenance = load_questions()
    qmap = {q.question_id: q for q in all_questions if q.corpus == "enterpriserag"}
    qids = [r["question_id"] for r in baseline["retrieval"]["queries"] if r["corpus"] == "enterpriserag"
            and r["mode"] == "hybrid" and r["coverage"] == "fully_covered"]
    if args.limit:
        qids = qids[:args.limit]
    questions = [qmap[qid] for qid in qids]
    source = sqlite3.connect((out / "canonical.sqlite").as_uri() + "?mode=ro", uri=True)
    source.row_factory = sqlite3.Row
    snapshot = resources(out, source)["store_sha256"]
    if snapshot != baseline["resources"]["store_sha256"] or baseline["datasets"]["enterpriserag"]["custom_questions"]:
        raise ValueError("the fixed official baseline no longer matches this store")
    device = ("cuda" if torch.cuda.is_available() else "cpu") if args.device == "auto" else args.device
    model = SentenceTransformer(MODEL_NAME, revision=MODEL_REVISION, device=device)
    if model.max_seq_length != 256:
        raise ValueError("unexpected embedding context window")
    query_vectors = np.ascontiguousarray(model.encode([q.text for q in questions], batch_size=64,
        normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False), dtype=np.float32)
    code_digest = hashlib.sha256((ROOT / "contextledger/processors.py").read_bytes()).hexdigest()
    prepared_store = args.prepared_store.resolve() if args.prepared_store else None
    if prepared_store is not None:
        validate_prepared_store(prepared_store, snapshot, code_digest)
    report = {"created_at": datetime.now(timezone.utc).isoformat(), "questions": len(questions),
        "store_sha256": snapshot, "datasets": provenance, "applied_to_serving": False,
        "configuration": {"model": MODEL_NAME, "revision": MODEL_REVISION, "dim": 384,
            "max_tokens": 256, "overlap_tokens": 32, "backend": "exact FlatIP for all variants",
            "device": device, "dtype": "float32", "keyword_candidates": 200,
            "vector_chunk_candidates": 80, "oracle_vector_chunk_candidates": 1600,
            "document_budget_comparison": {"documents": 80, "chunk_cap": 1600},
            "processor_sha256": code_digest}, "variants": {},
        "notes": ["Same source IDs, ACL, queries, model, keyword retrieval and RRF; no label-selected settings.",
                  "Candidate oracle is an upper bound, not final Recall@10.",
                  "Fully covered EnterpriseRAG regression subset only; no answer generation or reranker."]}
    report_path = args.report or out / "chunking_evaluation.json"
    if report_path.exists():
        previous = json.loads(report_path.read_text())
        if (previous.get("store_sha256") == snapshot and previous.get("configuration") == report["configuration"]
                and previous.get("datasets") == provenance
                and previous.get("questions") == len(questions)
                and all([r["question_id"] for r in value["rows"]] == qids
                        for value in previous.get("variants", {}).values())):
            report["variants"] = previous.get("variants", {})
    for variant in args.variants:
        if variant in report["variants"]:
            print(f"{variant}: existing result matches the protocol", flush=True)
            continue
        if variant == "legacy":
            directory = out / "vectors/enterpriserag"
            status = json.loads((directory / "status.json").read_text())
        else:
            directory = cache / variant
            signature = hashlib.sha256(json.dumps([snapshot, code_digest, MODEL_REVISION, variant]).encode()).hexdigest()
            status = build_variant(source, directory, variant, model, signature, args.batch_size, prepared_store)
        report["variants"][variant] = measure(source, questions, model, query_vectors, directory, variant, status)
        if resources(out, source)["store_sha256"] != snapshot:
            raise ValueError("store changed during chunking evaluation")
        temporary = report_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(report, indent=2) + "\n")
        temporary.replace(report_path)
        print(variant, json.dumps(report["variants"][variant]["summary"]), flush=True)
    source.close()
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "runtime/part_a")
    parser.add_argument("--cache", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--prepared-store", type=Path, help="reuse a matching rechunked store for the contextual variant")
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    parser.add_argument("--variants", nargs="+", choices=("legacy", "tokens", "contextual"), default=["legacy", "tokens", "contextual"])
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--batch-size", type=int, default=256)
    run(parser.parse_args())


if __name__ == "__main__":
    main()
