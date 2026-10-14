"""Combine contextual vector candidates with bounded evidence reranking."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import inspect
import json
import math
from pathlib import Path
import sqlite3
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from contextledger.evaluation import classify_questions, load_questions, percentile, resources
from contextledger.store import chunk_digest
from scripts.compare_part_a_rerankers import (
    INSTRUCTION, MODELS, Reranker, atomic_json, candidate_cache_signature,
)
from scripts.experiment_part_a_qwen_shortlist import _signature as old_score_signature
from scripts.experiment_part_a_ranking import rerank
from scripts.tune_part_a_retrieval import document_recall, passage, query_terms, visible_rankings

MAX_TOKENS = 1536
VECTOR_ADDITIONS = 0
# Fewer replacements and smaller margins win development ties.
SETTINGS = [(slots, margin) for slots in (0, 1, 2, 3) for margin in (0.0, 1.0, 2.0)
            if slots or margin == 0]


def shortlist(base: list[str], rrf: list[str], vector: list[str], additions: int) -> list[str]:
    if additions < 0:
        raise ValueError("negative vector additions")
    ids = list(dict.fromkeys(base[:10] + rrf[:80]))
    if not additions:
        return ids
    seen = set(ids)
    extra = []
    for did in vector:
        if did not in seen:
            seen.add(did)
            extra.append(did)
        if len(extra) >= additions:
            break
    return ids + extra


def replace_tail(base: list[str], ids: list[str], scores: dict[str, float],
                 slots: int, margin: float) -> list[str]:
    """Replace at most slots documents; reference IDs never enter ranking."""
    if not 0 <= slots <= 10 or margin < 0:
        raise ValueError("invalid replacement budget")
    if len(set(ids)) != len(ids) or any(did not in scores for did in ids):
        raise ValueError("one score required per unique candidate")
    if any(not math.isfinite(float(scores[did])) for did in ids):
        raise ValueError("non-finite scores")
    current = list(dict.fromkeys(base))[:10]
    if not set(current) <= set(ids):
        raise ValueError("base missing from shortlist")
    inside = sorted(current, key=lambda did: (scores[did], did))
    outside = sorted((did for did in ids if did not in current), key=lambda did: (-scores[did], did))
    for best, worst in list(zip(outside, inside))[:slots]:
        if scores[best] - scores[worst] < margin:
            break
        current[current.index(worst)] = best
    # A revoked permission can leave fewer than ten base documents.
    for did in sorted(ids, key=lambda did: (-scores[did], did)):
        if len(current) == 10:
            break
        if did not in current:
            current.append(did)
    return current


def select_setting(development: list[tuple[tuple[int, float], float]]) -> tuple[int, float]:
    if not development:
        raise ValueError("no development settings")
    # Input order provides the deterministic, conservative tie break.
    return max(development, key=lambda item: round(item[1], 12))[0]


def meets_target(rows: list[dict], expected: int, target: float) -> bool:
    if not 0 < target <= 1:
        raise ValueError("target must be in (0, 1]")
    if len(rows) != expected or len({row['question_id'] for row in rows}) != expected:
        return False
    if any(row["split"] not in {"development", "validation"} for row in rows):
        return False
    splits = [[row for row in rows if row["split"] == name] for name in ("development", "validation")]
    return all(group and sum(row["document_recall10"] for row in group) / len(group) >= target
               for group in [rows, *splits])


def _digest(data) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def run(args) -> dict:
    import faiss
    import torch
    from contextledger import vectors

    torch.set_num_threads(8)
    faiss.omp_set_num_threads(8)
    device = ("cuda" if torch.cuda.is_available() else "cpu") if args.device == "auto" else args.device
    tuning = json.loads((args.baseline / "retrieval_tuning.json").read_text())
    cached = json.loads(args.candidates.read_text())
    questions, provenance = load_questions()
    qmap = {q.question_id: q for q in questions if q.corpus == "enterpriserag"}
    full = [qmap[row["question_id"]] for row in tuning["rows"]]
    if provenance != tuning["datasets"]:
        raise ValueError("question provenance changed")
    expected = candidate_cache_signature(tuning["store_sha256"], [q.question_id for q in full],
                                         tuning["configuration"])
    if cached["signature"] != expected:
        raise ValueError("candidate cache belongs to a different experiment")
    selected = full[:args.limit] if args.limit else full
    sources = {row["question_id"]: row for row in tuning["rows"]}
    for q in full:
        if set(q.gold) != set(sources[q.question_id]["reference_document_ids"]):
            raise ValueError("reference evidence changed")
    connection = sqlite3.connect(f"file:{args.out / 'canonical.sqlite'}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        snapshot = resources(args.out, connection)["store_sha256"]
        if snapshot != tuning["store_sha256"]:
            raise ValueError("source documents or permissions changed")
        _, coverage_labels = classify_questions(connection, [q for q in questions if q.corpus == "enterpriserag"])
        covered = {qid for (corpus, qid), (status, _) in coverage_labels.items() if status == "fully_covered"}
        if len(full) != len(covered) or {q.question_id for q in full} != covered:
            raise ValueError("tuning rows do not cover every fully imported benchmark question")
        docs = {row["doc_id"]: dict(row) for row in connection.execute(
            "SELECT doc_id,title,text,source FROM documents WHERE corpus='enterpriserag'")}
        chunks_snapshot = chunk_digest(connection, "enterpriserag")
        signature = _digest({
            "store": snapshot, "chunks": chunks_snapshot,
            "candidates": hashlib.sha256(args.candidates.read_bytes()).hexdigest(),
            "baseline": hashlib.sha256((args.baseline / "retrieval_tuning.json").read_bytes()).hexdigest(),
            "model": MODELS["qwen"], "max_tokens": MAX_TOKENS, "instruction": INSTRUCTION,
            "passage_code": hashlib.sha256((inspect.getsource(passage) + inspect.getsource(query_terms)).encode()).hexdigest(),
            "device": device, "seed_scores": hashlib.sha256(args.seed_scores.read_bytes()).hexdigest(),
            "vector_additions": args.vector_additions, "nprobe": 768 if args.vector_additions else None,
            "chunk_candidates": 1600 if args.vector_additions else 0,
            "vector_meta": hashlib.sha256((args.out / "vectors/meta.json").read_bytes()).hexdigest(),
        })
        checkpoint_path = args.cache / "refinement_scores.json"
        args.cache.mkdir(parents=True, exist_ok=True)
        checkpoint = json.loads(checkpoint_path.read_text()) if checkpoint_path.exists() else {
            "signature": signature, "rows": {}}
        if checkpoint["signature"] != signature:
            raise ValueError("refinement checkpoint belongs to different inputs")
        seed = json.loads(args.seed_scores.read_text())
        if seed["signature"] != old_score_signature([q.question_id for q in full], snapshot):
            raise ValueError("seed scores belong to a different experiment")
        store = vectors.get_store(args.out, "enterpriserag") if args.vector_additions else None
        if store is not None:
            store.nprobe = min(768, store.index.num_clusters)
        prepared = []
        for i, q in enumerate(selected):
            pool = cached["candidates"][q.question_id]["rrf"][:800]
            base = rerank(q.text, sources[q.question_id]["document_ids"], pool, docs)["document_ids"]
            tick = time.perf_counter()
            vector = ([hit["doc_id"] for hit in vectors.search_chunks(args.out, q.corpus, q.text, k=1600)]
                      if args.vector_additions else [])
            allowed = visible_rankings(connection, q, {"base": base, "rrf": pool, "vector": vector})
            ids = shortlist(allowed["base"], allowed["rrf"], allowed["vector"], args.vector_additions)
            prepared.append((q, allowed["base"], ids, (time.perf_counter() - tick) * 1000))
            if (i + 1) % 20 == 0:
                print(f"contextual candidates {i + 1}/{len(selected)}", flush=True)
    finally:
        connection.close()
    model = None
    try:
        for q, base, ids, retrieval_ms in prepared:
            identity = _digest({"query": q.text, "ids": ids,
                                "texts": [passage(docs[did], q.text) for did in ids]})
            saved = checkpoint["rows"].get(q.question_id)
            if saved is not None and saved["identity"] != identity:
                raise ValueError("checkpoint shortlist or passages changed")
            if saved is None:
                old = seed["rows"][q.question_id]
                existing = dict(zip(old["ids"], old["scores"]))
                missing = [did for did in ids if did not in existing]
                if model is None and missing:
                    model = Reranker("qwen", device, MAX_TOKENS, args.batch_size)
                tick = time.perf_counter()
                if missing:
                    predicted = model.predict(q.text, [passage(docs[did], q.text) for did in missing])
                    if len(predicted) != len(missing):
                        raise ValueError("incorrect number of model scores")
                    existing.update(zip(missing, predicted))
                saved = {"identity": identity, "ids": ids, "scores": [float(existing[did]) for did in ids],
                         "new_documents": len(missing), "additional_score_ms": (time.perf_counter()-tick)*1000,
                         "seed_score_ms": old["score_ms"], "retrieval_ms": retrieval_ms}
                replace_tail(base, ids, dict(zip(ids, saved["scores"])), 0, 0)
                checkpoint["rows"][q.question_id] = saved
                atomic_json(checkpoint_path, checkpoint)
            print(f"refine {q.question_id} {len(checkpoint['rows'])}/{len(selected)} "
                  f"new={saved['new_documents']} {saved['additional_score_ms']/1000:.1f}s", flush=True)
    finally:
        if model is not None:
            model.close()
    connection = sqlite3.connect(f"file:{args.out / 'canonical.sqlite'}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        if resources(args.out, connection)["store_sha256"] != snapshot or chunk_digest(connection, "enterpriserag") != chunks_snapshot:
            raise ValueError("store changed during inference; refresh the experiment")
    finally:
        connection.close()
    predictions = []
    control_predictions = []
    for q, base, ids, _ in prepared:
        saved = checkpoint["rows"][q.question_id]
        scores = dict(zip(ids, saved["scores"]))
        by_setting = {f"slots{s}-margin{m:g}": replace_tail(base, ids, scores, s, m) for s, m in SETTINGS}
        predictions.append({"question_id": q.question_id, "question_type": q.kind,
            "split": sources[q.question_id]["split"], "reference_document_ids": list(q.gold),
            "by_setting": by_setting, "scored_candidates": len(ids),
            "candidate_oracle": document_recall(q.gold, ids, len(ids)),
            "additional_score_ms": saved["additional_score_ms"], "seed_score_ms": saved["seed_score_ms"],
            "retrieval_ms": saved["retrieval_ms"], "new_documents": saved["new_documents"]})
        old_ids = shortlist(base, cached["candidates"][q.question_id]["rrf"], [], 0)
        old_scores = dict(zip(seed["rows"][q.question_id]["ids"], seed["rows"][q.question_id]["scores"]))
        control_predictions.append({"question_id": q.question_id, "split": sources[q.question_id]["split"],
            "reference_document_ids": list(q.gold),
            "by_setting": {f"slots{s}-margin{m:g}": replace_tail(base, old_ids, old_scores, s, m)
                           for s, m in SETTINGS}})
    development = [row for row in predictions if row["split"] == "development"]
    if not development:
        raise ValueError("no development questions")
    options = [(setting, sum(document_recall(row["reference_document_ids"],
                    row["by_setting"][f"slots{setting[0]}-margin{setting[1]:g}"]) for row in development)
                    / len(development)) for setting in SETTINGS]
    chosen = select_setting(options)
    name = f"slots{chosen[0]}-margin{chosen[1]:g}"
    for row in predictions:
        row["document_ids"] = row["by_setting"][name]
        row["document_recall10"] = document_recall(row["reference_document_ids"], row["document_ids"])
        del row["by_setting"]
    def mean(group, key):
        return sum(row[key] for row in group) / len(group) if group else None
    validation = [row for row in predictions if row["split"] == "validation"]
    controls_dev = [row for row in control_predictions if row["split"] == "development"]
    control_setting = select_setting([(setting,
        sum(document_recall(row["reference_document_ids"], row["by_setting"][f"slots{setting[0]}-margin{setting[1]:g}"])
            for row in controls_dev) / len(controls_dev)) for setting in SETTINGS])
    control_name = f"slots{control_setting[0]}-margin{control_setting[1]:g}"
    for row in control_predictions:
        row["document_recall10"] = document_recall(row["reference_document_ids"], row["by_setting"][control_name])
    control_validation = [row for row in control_predictions if row["split"] == "validation"]
    report = {"created_at": datetime.now(timezone.utc).isoformat(), "applied_to_serving": False,
        "complete": len(predictions) == len(full), "target_recall10": args.target,
        "target_met": meets_target(predictions, len(full), args.target),
        "metric": "Final fixed-reference evidence-document Recall@10",
        "questions": len(predictions), "development_questions": len(development),
        "validation_questions": len(validation), "development_recall10": mean(development, "document_recall10"),
        "validation_recall10": mean(validation, "document_recall10"),
        "all_recall10": mean(predictions, "document_recall10"), "selected_setting": name,
        "development_by_setting": {f"slots{s}-margin{m:g}": score for (s, m), score in options},
        "candidate_oracle": mean(predictions, "candidate_oracle"), "store_sha256": snapshot,
        "control_without_contextual_candidates": {"selected_setting": control_name,
            "development_recall10": mean(controls_dev, "document_recall10"),
            "validation_recall10": mean(control_validation, "document_recall10"),
            "all_recall10": mean(control_predictions, "document_recall10"),
            "target_met": meets_target(control_predictions, len(full), args.target)},
        "by_question_type": {kind: {"questions": len(group), "document_recall10": mean(group, "document_recall10")}
            for kind in sorted({row["question_type"] for row in predictions})
            for group in [[row for row in predictions if row["question_type"] == kind]]},
        "datasets": provenance, "coverage": tuning["coverage"], "input_signature": signature,
        "configuration": {"model": MODELS["qwen"], "max_tokens": MAX_TOKENS,
            "base": "calibrated BGE plus condition and sibling rules; replayed from unchanged sources",
            "old_shortlist": 80, "contextual_vector_additions": args.vector_additions,
            "vector_chunks": 1600 if store is not None else 0,
            "nprobe": store.nprobe if store is not None else None, "passage": "title plus two lexical windows",
            "selection": "highest development Recall@10; ties prefer fewer replacements then lower margin"},
        "timing": {"additional_score_p95_ms": percentile([row["additional_score_ms"] for row in predictions], .95),
            "seed_plus_additional_p95_ms": percentile([row["seed_score_ms"] + row["additional_score_ms"]
                                                     for row in predictions], .95)},
        "notes": ["Gold document IDs are only used to score final predictions and choose development settings.",
            "The 180-question benchmark and its 160-question validation split have been used in prior experiments; this is a regression measurement, not an unseen holdout.",
            "Scores cover 180 fully imported questions out of the official 500, with the original references unchanged.",
            "Old pointwise Qwen scores are reused for unchanged source documents and identical passages.",
            "Base BGE ranking is replayed; timing excludes its inference, HTTP and answer generation.",
            "All new model inputs are filtered against the current principal and as-of permissions.",
            "This experiment does not change port 7860 or 7861."], "rows": predictions}
    atomic_json(args.out / ("retrieval_refinement.json" if report["complete"] else "retrieval_refinement_pilot.json"), report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True, help="token-budgeted store")
    parser.add_argument("--baseline", type=Path, required=True, help="store with retrieval_tuning.json")
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--seed-scores", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--target", type=float, default=.90)
    parser.add_argument("--vector-additions", type=int, default=VECTOR_ADDITIONS)
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    parser.add_argument("--batch-size", type=int, default=2)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    if not 0 < args.target <= 1 or args.limit < 0 or args.batch_size < 1 or args.vector_additions < 0:
        parser.error("invalid target or candidate limits")
    for key in ("out", "baseline", "candidates", "seed_scores", "cache"):
        setattr(args, key, getattr(args, key).resolve())
    report = run(args)
    print(json.dumps({key: report[key] for key in ("complete", "all_recall10", "validation_recall10", "selected_setting", "target_met")}, indent=2))
    return 0 if report["target_met"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
