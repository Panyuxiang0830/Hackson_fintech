"""Offline Qwen3-Reranker shortlist for final evidence Recall@10.

Scores the ranking fork plus the first 80 RRF candidates. One setting is
chosen from the 20 development questions. Gold IDs are not model inputs.
This does not change the port-7860 service.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from contextledger.evaluation import load_questions, percentile
from scripts.experiment_part_a_ranking import rerank
from scripts.tune_part_a_retrieval import document_recall, passage

# Pointwise scores make every smaller cutoff a subset of this pool.
SCORE_K = 80
MAX_TOKENS = 1536
DEV_FLOOR = 0.90
# Earlier settings win a development tie. Fork is first so a tie keeps it.
SETTINGS = (
    {"name": "fork", "kind": "fork"},
    {"name": "reorder-40", "kind": "reorder", "k": 40},
    {"name": "reorder-80", "kind": "reorder", "k": 80},
    {"name": "tail1-40-m0", "kind": "tail", "k": 40, "margin": 0.0, "slots": 1},
    {"name": "tail1-80-m0", "kind": "tail", "k": 80, "margin": 0.0, "slots": 1},
    {"name": "tail1-40-m1", "kind": "tail", "k": 40, "margin": 1.0, "slots": 1},
    {"name": "tail1-80-m1", "kind": "tail", "k": 80, "margin": 1.0, "slots": 1},
)


def build_shortlist(ranked: list[str], rrf: list[str], k: int) -> list[str]:
    """Fork top-10, then RRF documents that are not already there, through rank k."""
    if k < 10:
        raise ValueError("shortlist k must be at least 10")
    return list(dict.fromkeys(list(ranked[:10]) + list(rrf[:k])))


def order_by_score(ids: list[str], scores: list[float]) -> list[str]:
    if len(ids) != len(scores) or len(set(ids)) != len(ids):
        raise ValueError("one score per unique id")
    return [ids[i] for i in sorted(range(len(ids)), key=lambda i: (-float(scores[i]), i))]


def apply_setting(spec: dict, fork_ids: list[str], rrf: list[str], score_by_id: dict) -> list[str]:
    """Rank from fork ids, RRF order, and reranker scores. No gold IDs."""
    if spec["kind"] == "fork":
        return list(fork_ids[:10])
    ids = build_shortlist(fork_ids, rrf, spec["k"])
    missing = [did for did in ids if did not in score_by_id]
    if missing:
        raise ValueError("shortlist id has no score")
    if spec["kind"] == "reorder":
        return order_by_score(ids, [score_by_id[did] for did in ids])[:10]
    if spec["kind"] != "tail":
        raise ValueError("unknown setting")
    base = list(fork_ids[:10])
    outside = [did for did in ids if did not in set(base)]
    outside.sort(key=lambda did: (-float(score_by_id[did]), did))
    insiders = sorted(base, key=lambda did: (float(score_by_id[did]), did))
    out = list(base)
    for slot in range(spec["slots"]):
        if slot >= len(outside) or slot >= len(insiders):
            break
        best, worst = outside[slot], insiders[slot]
        if float(score_by_id[best]) - float(score_by_id[worst]) < spec["margin"]:
            break
        out[out.index(worst)] = best
    return out


def choose_setting(options: list[tuple[str, float]], floor: float = DEV_FLOOR) -> str:
    """Pick the best development Recall@10. Ties keep the earlier name.

    ``options`` is ``(name, development_recall)`` in priority order.
    A value under ``floor`` is eligible only when every option is under it.
    """
    if not options:
        raise ValueError("no settings")
    eligible = [item for item in options if item[1] >= floor - 1e-9]
    pool = eligible or list(options)
    best_name, best_score = pool[0]
    for name, score in pool[1:]:
        if score > best_score:
            best_name, best_score = name, score
    return best_name


def _mean(rows: list[dict], key: str, split: str | None = None) -> float:
    chosen = [row for row in rows if split is None or row["split"] == split]
    return sum(row[key] for row in chosen) / len(chosen)


def _signature(question_ids: list[str], store_sha256: str) -> str:
    payload = {
        "questions": question_ids,
        "store_sha256": store_sha256,
        "score_k": SCORE_K,
        "max_tokens": MAX_TOKENS,
        "passage": "tune_part_a_retrieval.passage",
        "model": "Qwen/Qwen3-Reranker-4B@22e683669bc0f0bd69640a1354a6d0aebcfeede5",
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def _atomic(path: Path, data: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2) + "\n")
    temporary.replace(path)


def score_questions(questions, forks, docs, cache_path: Path, signature: str,
                     device: str, batch_size: int) -> dict:
    """Score each fork-plus-RRF shortlist. Gold is not passed in."""
    import torch
    from scripts.compare_part_a_rerankers import Reranker

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    if cache_path.exists():
        cached = json.loads(cache_path.read_text())
        if cached.get("signature") != signature:
            raise ValueError("score cache belongs to a different shortlist")
    else:
        cached = {"signature": signature, "rows": {}}
    pending = [q for q in questions if q.question_id not in cached["rows"]]
    if not pending:
        return cached
    if device == "cuda":
        torch.cuda.set_per_process_memory_fraction(0.62)
    batch = batch_size
    while pending and batch >= 1:
        model = None
        try:
            model = Reranker("qwen", device, MAX_TOKENS, batch)
            for question in list(pending):
                ids = build_shortlist(forks[question.question_id], question.rrf, SCORE_K)
                texts = [passage(docs[did], question.text) for did in ids]
                if device == "cuda":
                    torch.cuda.synchronize()
                started = time.perf_counter()
                scores = model.predict(question.text, texts)
                if device == "cuda":
                    torch.cuda.synchronize()
                elapsed = (time.perf_counter() - started) * 1000
                if len(scores) != len(ids):
                    raise ValueError("reranker returned the wrong number of scores")
                cached["rows"][question.question_id] = {
                    "ids": ids, "scores": [float(score) for score in scores], "score_ms": elapsed,
                }
                pending = [item for item in pending if item.question_id != question.question_id]
                _atomic(cache_path, cached)
                print(f"qwen-shortlist {len(cached['rows'])}/{len(questions)} {question.question_id} "
                      f"n={len(ids)} {elapsed / 1000:.1f}s", flush=True)
            model.close()
            break
        except torch.cuda.OutOfMemoryError:
            if model is not None:
                model.close()
            elif device == "cuda":
                torch.cuda.empty_cache()
            batch //= 2
            print(f"qwen-shortlist: out of memory, retry batch {batch}", flush=True)
            if batch < 1:
                raise
    return cached


class _Question:
    def __init__(self, question, rrf):
        self.question_id = question.question_id
        self.text = question.text
        self.gold = list(question.gold)
        self.kind = question.kind
        self.rrf = rrf


def run(out_dir: Path, candidates: Path, scores_path: Path, *, target: float, device: str,
        batch_size: int, limit: int) -> dict:
    out_dir = out_dir.resolve()
    tuning = json.loads((out_dir / "retrieval_tuning.json").read_text())
    cached_candidates = json.loads(candidates.read_text())
    questions, _provenance = load_questions()
    qmap = {question.question_id: question for question in questions if question.corpus == "enterpriserag"}
    import sqlite3
    connection = sqlite3.connect(f"file:{out_dir / 'canonical.sqlite'}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        docs = {row["doc_id"]: {"title": row["title"] or "", "text": row["text"] or ""}
                for row in connection.execute(
                    "SELECT doc_id,title,text FROM documents WHERE corpus='enterpriserag'")}
    finally:
        connection.close()
    sources = tuning["rows"] if limit <= 0 else tuning["rows"][:limit]
    prepared = []
    forks = {}
    for source in sources:
        question = qmap[source["question_id"]]
        pool = cached_candidates["candidates"][question.question_id]["rrf"][:800]
        forked = rerank(question.text, source["document_ids"], pool, docs)
        forks[question.question_id] = forked["document_ids"]
        item = _Question(question, pool)
        item.split = source["split"]
        item.fork_ids = forked["document_ids"]
        prepared.append(item)
    signature = _signature([item.question_id for item in prepared], tuning["store_sha256"])
    import torch
    resolved = device
    if resolved == "auto":
        resolved = "cuda" if torch.cuda.is_available() else "cpu"
    scored = score_questions(prepared, forks, docs, scores_path, signature, resolved, batch_size)
    rows = []
    for item in prepared:
        saved = scored["rows"][item.question_id]
        score_by_id = dict(zip(saved["ids"], saved["scores"]))
        expected = build_shortlist(item.fork_ids, item.rrf, SCORE_K)
        if saved["ids"] != expected:
            raise ValueError(f"cached shortlist mismatch for {item.question_id}")
        by_setting = {
            spec["name"]: apply_setting(spec, item.fork_ids, item.rrf, score_by_id) for spec in SETTINGS
        }
        rows.append({
            "question_id": item.question_id,
            "question_type": item.kind,
            "split": item.split,
            "fork_ids": item.fork_ids,
            "by_setting": by_setting,
            "gold": item.gold,
            "score_ms": saved["score_ms"],
            "scored_candidates": len(saved["ids"]),
        })
    dev_options = []
    development_recall = {}
    validation_recall = {}
    all_recall = {}
    for spec in SETTINGS:
        name = spec["name"]
        recalls = [document_recall(row["gold"], row["by_setting"][name]) for row in rows]
        for row, recall in zip(rows, recalls):
            row.setdefault("recall_by_setting", {})[name] = recall
        dev_values = [recall for row, recall in zip(rows, recalls) if row["split"] == "development"]
        val_values = [recall for row, recall in zip(rows, recalls) if row["split"] == "validation"]
        development_recall[name] = sum(dev_values) / len(dev_values)
        validation_recall[name] = (sum(val_values) / len(val_values)) if val_values else None
        all_recall[name] = sum(recalls) / len(recalls)
        dev_options.append((name, development_recall[name]))
    selected = choose_setting(dev_options)
    for row in rows:
        row["document_ids"] = row["by_setting"][selected]
        row["document_recall10"] = row["recall_by_setting"][selected]
        row["fork_recall10"] = document_recall(row["gold"], row["fork_ids"])
    dev = _mean(rows, "document_recall10", "development")
    validation_rows = [row for row in rows if row["split"] == "validation"]
    validation = _mean(validation_rows, "document_recall10") if validation_rows else None
    overall = _mean(rows, "document_recall10")
    report = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "applied_to_serving": False,
        "complete": len(rows) == len(tuning["rows"]),
        "target_recall10": target,
        "target_met": (len(rows) == len(tuning["rows"]) and dev >= target and overall >= target),
        "metric": "Final evidence-document Recall@10 after a development-chosen shortlist rerank.",
        "questions": len(rows),
        "selected_setting": selected,
        "development_recall10": dev,
        "validation_recall10": validation,
        "all_recall10": overall,
        "fork_recall10": _mean(rows, "fork_recall10"),
        "development_recall_by_setting": development_recall,
        "validation_recall_by_setting": validation_recall,
        "all_recall_by_setting": all_recall,
        "store_sha256": tuning["store_sha256"],
        "configuration": {
            "model": "Qwen/Qwen3-Reranker-4B",
            "revision": "22e683669bc0f0bd69640a1354a6d0aebcfeede5",
            "max_tokens": MAX_TOKENS,
            "score_k": SCORE_K,
            "passage": "title plus two lexical windows",
            "development_floor": DEV_FLOOR,
            "selection": "highest development Recall@10 at or above the floor; earlier setting wins a tie",
            "settings": [spec["name"] for spec in SETTINGS],
        },
        "score_ms": {"p50": percentile([row["score_ms"] for row in rows], .5),
                     "p95": percentile([row["score_ms"] for row in rows], .95)},
        "notes": [
            "Reference IDs are used only after ranking, to score Recall@10.",
            "The setting is chosen from development Recall@10. Validation numbers are recorded and do not choose it.",
            "A development tie keeps the earlier setting. The unchanged fork is first.",
            "This run does not change the port-7860 service.",
            "Gold document IDs are unchanged.",
            "Candidate-oracle coverage is not this metric.",
        ],
        "rows": [{
            "question_id": row["question_id"],
            "question_type": row["question_type"],
            "split": row["split"],
            "fork_recall10": row["fork_recall10"],
            "document_recall10": row["document_recall10"],
            "recall_by_setting": row["recall_by_setting"],
            "document_ids": row["document_ids"],
            "reference_document_ids": row["gold"],
            "scored_candidates": row["scored_candidates"],
            "score_ms": row["score_ms"],
        } for row in rows],
    }
    if report["complete"]:
        _atomic(out_dir / "qwen_shortlist.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "runtime/part_a")
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--scores", type=Path,
                        default=Path("/tmp/contextledger-rerank-20261007/qwen_shortlist_scores.json"))
    parser.add_argument("--target", type=float, default=DEV_FLOOR)
    parser.add_argument("--device", choices=["auto", "cpu", "cuda"], default="auto")
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    if args.batch_size < 1 or args.limit < 0:
        parser.error("invalid batch or limit")
    report = run(args.out, args.candidates, args.scores, target=args.target, device=args.device,
                 batch_size=args.batch_size, limit=args.limit)
    print(json.dumps({key: report[key] for key in (
        "selected_setting", "all_recall10", "development_recall10", "validation_recall10",
        "fork_recall10", "development_recall_by_setting", "target_met", "applied_to_serving",
        "complete")}, indent=2))
    return 0 if report["target_met"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
