"""Read-only document-recall tuning with a separate validation split."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import itertools
import json
from pathlib import Path
import random
import re
import sqlite3
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from contextledger.evaluation import load_questions, percentile, resources
from contextledger.search import _partition, _rrf
from contextledger.store import load_principal

DENSE_MODEL = "BAAI/bge-base-en-v1.5"
DENSE_REVISION = "a5beb1e3e68b9ab74eb54cfd186867f64f240e1a"
RERANK_MODEL = "BAAI/bge-reranker-v2-m3"
RERANK_REVISION = "953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e"
LABELS = ("keyword", "titles", "vector", "profile", "kinds")
WORD = re.compile(r"[\w]+(?:[-_][\w]+)*")
KINDS = ("postmortem", "runbook", "playbook", "policy", "proposal", "checklist")


def query_terms(text: str) -> list[str]:
    from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS

    stop = set(ENGLISH_STOP_WORDS) | set("does did doing explain describe document documents tell provide know information according using use list based".split())
    return list(dict.fromkeys(w.lower() for w in WORD.findall(text)
                             if len(w) >= 2 and w.lower() not in stop))[:48]


def fts_match(text: str) -> str:
    def prefix(term):
        if len(term) > 5 and term.endswith("ies"):
            return '"' + term[:-3] + 'y"*'
        if len(term) > 4 and term.endswith("s"):
            return '"' + term[:-1] + '"*'
        if len(term) > 5 and term.endswith("ed"):
            return '"' + term[:-2] + '"*'
        return '"' + term + '"'

    return " OR ".join(prefix(term) for term in query_terms(text))


def passage(doc: dict, query: str) -> str:
    terms = query_terms(query)
    text = doc["text"]
    windows = [text[start:start + 2100] for start in range(0, len(text), 1800)] or [""]
    ranked = [(sum((2 if any(c.isdigit() for c in term) else 1) * min(window.lower().count(term), 3)
                   for term in terms), i, window) for i, window in enumerate(windows)]
    selected = sorted(ranked, key=lambda row: (-row[0], row[1]))[:2]
    return doc["title"] + "\n" + "\n".join(row[2] for row in selected)


def visible_rankings(connection, question, rankings: dict) -> dict:
    principal = load_principal(connection, question.principal_id)
    if principal is None or principal.corpus != question.corpus:
        return {name: [] for name in rankings}
    combined = list(dict.fromkeys(did for ids in rankings.values() for did in ids))
    visible, _ = _partition(connection, principal, combined, question.as_of_day)
    allowed = set(visible)
    return {name: [did for did in ids if did in allowed] for name, ids in rankings.items()}


def document_recall(gold, ranked, k=10):
    expected = set(gold)
    found = list(dict.fromkeys(ranked))[:k]
    return len(expected & set(found)) / len(expected)


def calibrate_reranking(questions, predictions, docs, development_queries):
    """Fit score adjustments on development labels only."""
    import numpy as np

    if len(questions) != len(predictions) or not 1 <= development_queries <= len(questions):
        raise ValueError("calibration requires matching predictions and a valid development split")
    configurations = list(itertools.product((0, 1, 2, 4), (0, 1, 2, 4), (0, 1, 2)))
    weights = np.asarray(configurations, dtype=np.float64)
    ranked_by_question = []
    development = np.zeros(len(configurations))
    for i, (question, prediction) in enumerate(zip(questions, predictions)):
        query = question.text.lower()
        sources = {source for source in ("jira", "confluence", "slack", "google_drive")
                   if ("google drive" if source == "google_drive" else source) in query}
        kinds = [kind for kind in KINDS if re.search(r"\b" + kind + r"(?:s|ies)?\b", query)]
        ids = list(prediction)
        features = []
        for did in ids:
            doc = docs[did]
            fields = re.findall(r"(?im)^([\w ]{3,30}):\s*([^\n]{3,80})$", doc["text"])
            features.append([
                -int(bool(sources) and doc["source"] not in sources),
                sum(value.lower() in query for _, value in fields),
                int(any(doc["title"].lower().startswith((kind + ":", "p0 incident " + kind + ":"))
                        for kind in kinds)),
            ])
        logits = np.asarray([prediction[did] for did in ids], dtype=np.float64)
        scores = logits[:, None] + np.asarray(features, dtype=np.float64).reshape(-1, 3) @ weights.T
        # Stable ties follow the candidate ranking used by the raw reranker.
        rankings = np.argsort(-scores, axis=0, kind="stable")[:10]
        ranked_by_question.append((ids, rankings))
        if i < development_queries:
            gold = set(question.gold)
            matches = np.asarray([did in gold for did in ids])
            development += matches[rankings].sum(axis=0) / len(gold)
    development /= development_queries
    selected = max(range(len(configurations)), key=lambda j: (development[j], -j))
    rankings = [[ids[int(j)] for j in order[:, selected]] for ids, order in ranked_by_question]
    source, field, kind = configurations[selected]
    return {
        "configurations": len(configurations),
        "selected": {"source_penalty": source, "field_bonus": field, "kind_bonus": kind},
        "development_recall10": float(development[selected]),
    }, rankings


def tune_fusion(questions, candidates, development_queries=20):
    import numpy as np

    configs = [{"rrf_constant": constant, "weights": [1, title, vector, profile, kind]}
               for constant, title, vector, profile, kind in itertools.product(
                   (30, 60, 120), (0, .5, 1), (.5, 1, 2), (0, .5, 1, 2), (0, .5, 1))]
    weights = np.asarray([cfg["weights"] for cfg in configs], dtype=np.float64)
    values = np.zeros((len(questions), len(configs)))
    for i, question in enumerate(questions):
        entry = candidates[question.question_id]
        ids = sorted(set(did for label in LABELS for did in entry[label]))
        if not ids:
            continue
        positions = {did: j for j, did in enumerate(ids)}
        gold = set(question.gold)
        matches = np.asarray([did in gold for did in ids])
        for constant in (30, 60, 120):
            indexes = [j for j, cfg in enumerate(configs) if cfg["rrf_constant"] == constant]
            features = np.zeros((len(ids), len(LABELS)))
            for li, label in enumerate(LABELS):
                for rank, did in enumerate(entry[label], 1):
                    features[positions[did], li] = 1 / (constant + rank)
            scores = features @ weights[indexes].T
            chosen = np.argsort(-scores, axis=0, kind="stable")[:10]
            values[i, indexes] = matches[chosen].sum(axis=0) / len(gold)
    development = values[:development_queries].mean(axis=0)
    selected = max(range(len(configs)), key=lambda j: (development[j], -j))
    return {
        "configurations": len(configs), "selected": configs[selected],
        "development_recall10": float(development[selected]),
        "validation_recall10": float(values[development_queries:, selected].mean()),
        "all_recall10": float(values[:, selected].mean()),
    }


def collect_candidates(out_dir, connection, questions, docs, selected_device):
    import faiss
    import numpy as np
    import torch
    from sentence_transformers import SentenceTransformer
    from contextledger import vectors

    dense = SentenceTransformer(DENSE_MODEL, revision=DENSE_REVISION, device=selected_device)
    if selected_device == "cuda":
        dense.half()
    doc_ids = list(docs)
    embeddings = np.empty((len(doc_ids), 768), dtype=np.float32)
    for start in range(0, len(doc_ids), 1024):
        batch = doc_ids[start:start + 1024]
        embeddings[start:start + len(batch)] = dense.encode(
            [docs[did]["title"] + "\n" + docs[did]["text"][:2000] for did in batch],
            batch_size=48, normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False)
        print(f"tune profiles: {min(start + 1024, len(doc_ids))}/{len(doc_ids)}", flush=True)
    embeddings /= np.linalg.norm(embeddings, axis=1, keepdims=True)
    query_vectors = np.asarray(dense.encode(
        ["Represent this sentence for searching relevant passages: " + q.text for q in questions],
        batch_size=32, normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False), dtype=np.float32)
    query_vectors /= np.linalg.norm(query_vectors, axis=1, keepdims=True)
    flat = faiss.IndexFlatIP(768)
    flat.add(embeddings)
    _, profile_ids = flat.search(query_vectors, min(500, len(doc_ids)))
    del dense, flat, embeddings, query_vectors
    if selected_device == "cuda":
        torch.cuda.empty_cache()

    store = vectors.get_store(out_dir, "enterpriserag")
    store.nprobe = min(768, store.index.num_clusters)
    vectors._MODEL = SentenceTransformer(vectors.MODEL_NAME, device=selected_device)
    candidates = {}
    for i, question in enumerate(questions):
        match = fts_match(question.text)
        keyword = [row[0] for row in connection.execute(
            "SELECT doc_id FROM docs_fts WHERE docs_fts MATCH ? AND corpus=? ORDER BY bm25(docs_fts,0,0,0,5,1) LIMIT 800",
            (match, question.corpus))] if match else []
        titles = [row[0] for row in connection.execute(
            "SELECT doc_id FROM docs_fts WHERE docs_fts MATCH ? AND corpus=? ORDER BY bm25(docs_fts) LIMIT 100",
            ("title: (" + match + ")", question.corpus))] if match else []
        kinds = []
        for kind in KINDS:
            if re.search(r"\b" + kind + r"(?:s|ies)?\b", question.text.lower()):
                kinds.extend(row[0] for row in connection.execute(
                    "SELECT doc_id FROM docs_fts WHERE docs_fts MATCH ? AND corpus=? ORDER BY bm25(docs_fts) LIMIT 600",
                    ('title: "' + kind + '"*', question.corpus)))
        ranking = visible_rankings(connection, question, {
            "keyword": keyword, "titles": titles,
            "vector": [hit["doc_id"] for hit in vectors.search_chunks(out_dir, question.corpus, question.text, k=1600)],
            "profile": [doc_ids[int(j)] for j in profile_ids[i]], "kinds": list(dict.fromkeys(kinds)),
        })
        ranking["rrf"] = _rrf([ranking[label] for label in LABELS])
        candidates[question.question_id] = ranking
        if (i + 1) % 20 == 0:
            print(f"tune candidates: {i + 1}/{len(questions)}", flush=True)
    return candidates, store.nprobe


def run(out_dir: Path, *, target=.90, development_queries=20, seed=42, rerank_limit=800, device="auto"):
    import faiss
    import numpy as np
    import torch
    from sentence_transformers import CrossEncoder, SentenceTransformer
    from contextledger import vectors

    if not 0 < target <= 1 or rerank_limit < 10 or development_queries < 1:
        raise ValueError("invalid target, development size or rerank budget")
    torch.set_num_threads(8)
    faiss.omp_set_num_threads(8)
    selected_device = ("cuda" if torch.cuda.is_available() else "cpu") if device == "auto" else device
    out_dir = out_dir.resolve()
    baseline = json.loads((out_dir / "evaluation.json").read_text())
    if baseline["datasets"]["enterpriserag"]["custom_questions"]:
        raise ValueError("tuning requires the pinned official question set")
    all_questions, provenance = load_questions()
    connection = sqlite3.connect(f"file:{out_dir / 'canonical.sqlite'}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        docs = {row["doc_id"]: dict(row) for row in connection.execute(
            "SELECT doc_id,title,text,source FROM documents WHERE corpus='enterpriserag' ORDER BY doc_id")}
        current_snapshot = resources(out_dir, connection)["store_sha256"]
        if current_snapshot != baseline["resources"]["store_sha256"]:
            raise ValueError("store changed since evaluation; rerun eval before tuning")
        qmap = {q.question_id: q for q in all_questions if q.corpus == "enterpriserag"}
        questions = [qmap[row["question_id"]] for row in baseline["retrieval"]["queries"]
                     if row["corpus"] == "enterpriserag" and row["mode"] == "hybrid"
                     and row["coverage"] == "fully_covered"]
        random.Random(seed).shuffle(questions)
        if development_queries >= len(questions):
            raise ValueError("development split must leave validation questions")
        print(f"tune: {len(questions)} fully covered questions; {development_queries} development", flush=True)
        candidates, nprobe = collect_candidates(out_dir, connection, questions, docs, selected_device)
        fusion = tune_fusion(questions, candidates, development_queries)
        reranker = CrossEncoder(RERANK_MODEL, revision=RERANK_REVISION, device=selected_device, max_length=768)
        if selected_device == "cuda":
            reranker.model.half()
        rows, predictions = [], []
        for i, question in enumerate(questions):
            entry = candidates[question.question_id]
            short = entry["rrf"][:rerank_limit]
            started = time.perf_counter()
            logits = np.asarray(reranker.predict(
                [(question.text, passage(docs[did], question.text)) for did in short],
                batch_size=16 if selected_device == "cuda" else 8,
                activation_fct=torch.nn.Identity(), show_progress_bar=False)) if short else np.empty(0)
            ranked = [short[int(j)] for j in np.argsort(-logits, kind="stable")]
            predictions.append({did: float(logit) for did, logit in zip(short, logits)})
            rows.append({"question_id": question.question_id, "question_type": question.kind,
                         "split": "development" if i < development_queries else "validation",
                         "document_recall10": document_recall(question.gold, ranked),
                         "raw_reranker_recall10": document_recall(question.gold, ranked),
                         "candidate_oracle_recall": document_recall(question.gold, entry["rrf"], len(entry["rrf"])),
                         "rerank_input_oracle_recall": document_recall(question.gold, short, len(short)),
                         "document_ids": ranked[:10], "reference_document_ids": list(question.gold),
                         "rerank_ms": (time.perf_counter() - started) * 1000})
            print(f"tune rerank: {i + 1}/{len(questions)} recall={rows[-1]['document_recall10']:.3f}", flush=True)
        calibration, rankings = calibrate_reranking(questions, predictions, docs, development_queries)
        for question, row, ranked in zip(questions, rows, rankings):
            row["document_ids"] = ranked
            row["document_recall10"] = document_recall(question.gold, ranked)
        report = summarize(rows, baseline, provenance, target, fusion, seed, selected_device, nprobe, rerank_limit)
        report["reranker_calibration"] = calibration
        path = out_dir / "retrieval_tuning.json"
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(report, indent=2) + "\n")
        temporary.replace(path)
        return report
    finally:
        connection.close()


def summarize(rows, baseline, provenance, target, fusion, seed, device, nprobe, rerank_limit):
    def mean(items, key):
        return sum(row[key] for row in items) / len(items)

    dev = [row for row in rows if row["split"] == "development"]
    validation = [row for row in rows if row["split"] == "validation"]
    validation_score = mean(validation, "document_recall10")
    all_score = mean(rows, "document_recall10")
    timings = [row["rerank_ms"] for row in rows if row.get("rerank_ms") is not None]
    return {
        "created_at": datetime.now(timezone.utc).isoformat(), "target_recall10": target,
        "target_met": validation_score >= target and all_score >= target,
        "applied_to_serving": False, "questions": len(rows), "seed": seed,
        "development_queries": len(dev), "validation_queries": len(validation),
        "development_recall10": mean(dev, "document_recall10"),
        "validation_recall10": validation_score, "all_recall10": all_score,
        "raw_reranker_recall10": mean(rows, "raw_reranker_recall10") if all("raw_reranker_recall10" in row for row in rows) else None,
        "candidate_oracle_recall": mean(rows, "candidate_oracle_recall"),
        "rerank_input_oracle_recall": mean(rows, "rerank_input_oracle_recall"),
        "baseline_recall10": baseline["retrieval"]["summary"]["enterpriserag"]["hybrid"]["top_k"]["10"]["document_recall"],
        "coverage": baseline["retrieval"]["coverage_all_questions"]["enterpriserag"],
        "store_sha256": baseline["resources"]["store_sha256"],
        "datasets": provenance, "fusion_grid": fusion,
        "configuration": {"corpus": "enterpriserag", "device": device,
                          "inference_dtype": "float16" if device == "cuda" else "float32", "dense_model": DENSE_MODEL,
                          "dense_revision": DENSE_REVISION, "dense_profile": "title plus first 2000 characters; max 512 model tokens",
                          "dense_candidate_backend": "exact FlatIP, experimental supplement to existing RaBitQ",
                          "reranker": RERANK_MODEL, "reranker_revision": RERANK_REVISION,
                          "reranker_max_tokens": 768, "reranker_activation": "raw logits", "rerank_document_budget": rerank_limit,
                          "candidate_fusion": {"rrf_constant": 60, "weights": [1, 1, 1, 1, 1]},
                          "rabitq_nprobe": nprobe, "vector_chunk_candidates": 1600,
                          "keyword_candidates": 800, "title_candidates": 100, "document_kind_candidates": 600},
        "rerank_only_ms": {"measured_queries": len(timings), "p50": percentile(timings, .5),
                           "p95": percentile(timings, .95)} if timings else None,
        "notes": ["Reference IDs are used only for scoring; no reference lists enter retrieval or model inputs.",
                  "Scores cover the fully imported EnterpriseRAG subset, not the complete benchmark.",
                  "Fusion settings are selected on development queries; validation labels do not select the settings.",
                  "The fusion grid is a separate comparison; reranker candidates use the fixed fusion configuration.",
                  "Reranker score adjustments are selected on development queries only.",
                  "Rerank timing excludes profiles, candidate retrieval, HTTP and answer generation.",
                  "This experiment does not change serving indexes or promise per-question 99 percent recall."],
        "rows": rows,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "runtime/part_a")
    parser.add_argument("--target", type=float, default=.90)
    parser.add_argument("--development-queries", type=int, default=20)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--rerank-limit", type=int, default=800)
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    args = parser.parse_args()
    report = run(args.out, target=args.target, development_queries=args.development_queries,
                 seed=args.seed, rerank_limit=args.rerank_limit, device=args.device)
    print(json.dumps({key: report[key] for key in ("all_recall10", "validation_recall10", "target_met", "applied_to_serving")}, indent=2))
    return 0 if report["target_met"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
