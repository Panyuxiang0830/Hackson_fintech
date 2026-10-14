"""Offline ranking fork: condition windows and multi-evidence coverage.

Reads the saved candidate pool and the tuned top-10. It does not rebuild
indexes, change gold IDs, or write the serving path. Final Recall@10 stays
separate from candidate-oracle coverage.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sqlite3
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from contextledger.evaluation import load_questions, percentile
from scripts.tune_part_a_retrieval import document_recall

# Development scores for 1-4 sibling slots and 1-3 seeds were tied, so the
# fork keeps two seeds and fills three of the ten slots with cited siblings.
SIBLING_SEEDS = 2
SIBLING_SLOTS = 3
MIN_CONSTRAINTS = 4
MAX_CONSTRAINT_HITS = 10
WINDOW_CHARS = 400

_GPU = re.compile(r"\b(a100|h100|a10|l40s?|l4|t4|v100)\b", re.I)
_SIZE = re.compile(r"\b(\d+(?:\.\d+)?)\s*b\b", re.I)
_BIT = re.compile(r"\b(\d+)\s*[- ]?bit\b", re.I)
_BATCH = re.compile(r"\bbatch(?:\s*size|\s*of|=)?\s*[=:]?\s*(\d+)\b", re.I)
_REGION = re.compile(r"\b((?:us|eu|ap|sa)-(?:east|west|central|south|north|southeast|northeast)-?\d*)\b", re.I)
_MULTI = re.compile(r"\b(end-to-end|across all|how many|complete|go/no-go)\b", re.I)
_CLASS = re.compile(r"\bacross all ([a-z0-9][a-z0-9 \-]{2,50}?)(?=,|\s+which|\s+what|\s+where|\s+who|\?|$)", re.I)
_PREDICATE = re.compile(r"\bthe most ([a-z0-9][a-z0-9 \-]{3,60})", re.I)
_STOP = set("the a an of to for in on and or with from by at as is are was were be this that what which who how when where across all most during".split())

_BIT_ALIASES = {
    "4": ("4-bit", "4 bit", "nf4", "int4", "fp4"),
    "8": ("8-bit", "8 bit", "int8", "fp8"),
    "16": ("16-bit", "16 bit", "fp16", "float16"),
}


def constraint_slots(query: str) -> list[tuple[str, tuple[str, ...]]]:
    """Typed constraints that must co-occur. Aliases stay inside one slot."""
    low = query.lower()
    slots: list[tuple[str, tuple[str, ...]]] = []

    def add(name: str, forms: tuple[str, ...] | list[str]) -> None:
        values = tuple(dict.fromkeys(form.lower() for form in forms if form))
        if values and all(name != existing for existing, _ in slots):
            slots.append((name, values))

    for match in _GPU.finditer(low):
        add("gpu:" + match.group(1).lower(), (match.group(1).lower(),))
    for match in _SIZE.finditer(low):
        size = match.group(1)
        add("size:" + size, (size + "b", size + " b"))
    for match in _BIT.finditer(low):
        bits = match.group(1)
        add("bit:" + bits, _BIT_ALIASES.get(bits, (bits + "-bit", bits + " bit")))
    if "half precision" in low or "half-precision" in low or re.search(r"\bfp16\b", low):
        add("prec:16", ("fp16", "float16", "half precision", "half-precision"))
    if re.search(r"\bbf16\b|\bbfloat16\b", low):
        add("prec:bf16", ("bf16", "bfloat16"))
    for match in _BATCH.finditer(low):
        value = match.group(1)
        forms = [f"batch={value}", f"batch {value}", f"batch size {value}", f"batch size of {value}"]
        if value == "1":
            forms.extend(("single-item", "single item"))
        add("batch:" + value, forms)
    if re.search(r"\bsingle[- ]item\b", low):
        add("batch:1", ("batch=1", "batch 1", "batch size 1", "single-item", "single item"))
    for match in _REGION.finditer(low):
        add("region:" + match.group(1).lower(), (match.group(1).lower(),))
    return slots


def evidence_windows(text: str):
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if len(line) <= WINDOW_CHARS:
            yield line
            continue
        parts = re.split(r"(?<=[.!?])\s+| - ", line)
        buf = ""
        for part in parts:
            if buf and len(buf) + 1 + len(part) > WINDOW_CHARS:
                yield buf
                buf = part
            else:
                buf = (buf + " " + part).strip()
        if buf:
            yield buf


def window_satisfies(text: str, slots: list[tuple[str, tuple[str, ...]]]) -> bool:
    if len(slots) < MIN_CONSTRAINTS:
        return False
    for window in evidence_windows(text.lower()):
        if all(any(form in window for form in forms) for _, forms in slots):
            return True
    return False


def promote_constraints(query: str, ranked: list[str], pool: list[str], docs: dict) -> tuple[list[str], int]:
    slots = constraint_slots(query)
    if len(slots) < MIN_CONSTRAINTS:
        return ranked[:10], 0
    hits = [did for did in pool if window_satisfies(_blob(docs[did]), slots)]
    if not hits or len(hits) > MAX_CONSTRAINT_HITS:
        return ranked[:10], len(hits)
    return list(dict.fromkeys(hits + ranked))[:10], len(hits)


def _blob(doc: dict) -> str:
    return doc["title"] + "\n" + doc["text"]


def sibling_ids(seeds: list[str], pool: list[str], docs: dict) -> list[str]:
    titles = [docs[did]["title"] for did in seeds if len(docs[did]["title"]) >= 16]
    blob = "\n".join(docs[did]["text"][:8000] for did in seeds).lower()
    found = []
    occupied = set(seeds)
    for did in pool:
        if did in occupied:
            continue
        title = docs[did]["title"]
        if len(title) < 16:
            continue
        text = docs[did]["text"][:5000].lower()
        if title.lower() in blob or any(seed.lower() in text for seed in titles):
            found.append(did)
    return found


def expand_siblings(query: str, ranked: list[str], pool: list[str], docs: dict,
                    seeds: int = SIBLING_SEEDS, slots: int = SIBLING_SLOTS) -> tuple[list[str], int]:
    if not _MULTI.search(query):
        return ranked[:10], 0
    links = [did for did in sibling_ids(ranked[:seeds], pool, docs) if did not in ranked[:10]]
    chosen = links[:slots]
    if not chosen:
        return ranked[:10], 0
    return list(dict.fromkeys(ranked[:10 - len(chosen)] + chosen))[:10], len(links)


def _class_head(phrase: str) -> str:
    words = [word for word in re.findall(r"[a-z0-9]+", phrase.lower()) if word not in _STOP and len(word) > 3]
    if not words:
        return ""
    head = words[-1]
    if head.endswith("ies") and len(head) > 5:
        return head[:-3] + "y"
    if head.endswith("s") and not head.endswith("ss"):
        return head[:-1]
    return head


def aggregation_query(query: str) -> tuple[str, str] | None:
    """Return (title stem, predicate phrase) for an across-all count."""
    kind = _CLASS.search(query)
    predicate = _PREDICATE.search(query)
    if not kind or not predicate:
        return None
    head = _class_head(kind.group(1))
    phrase = predicate.group(1).strip(" .?").lower()
    if not head or len(phrase) < 8:
        return None
    return head, phrase


def fill_aggregation(query: str, ranked: list[str], pool: list[str], docs: dict) -> tuple[list[str], int]:
    parsed = aggregation_query(query)
    if parsed is None:
        return ranked[:10], 0
    head, phrase = parsed
    matched = [did for did in pool
               if head in docs[did]["title"].lower() and phrase in docs[did]["text"].lower()]
    if not 3 <= len(matched) <= 30:
        return ranked[:10], len(matched)
    # Keep tuned hits that already satisfy the class, then add other class matches.
    kept = [did for did in ranked if did in set(matched)]
    return list(dict.fromkeys(kept + matched + ranked))[:10], len(matched)


def rerank(query: str, ranked: list[str], pool: list[str], docs: dict) -> dict:
    """Promote co-located conditions, then cited siblings. No gold IDs.

    Class-predicate fill is available as fill_aggregation. On the fixed 180 it
    replaced tuned documents for qst_0437 without raising that question's
    Recall@10, so the applied fork does not use it.
    """
    current, constraint_hits = promote_constraints(query, ranked, pool, docs)
    current, sibling_links = expand_siblings(query, current, pool, docs)
    return {"document_ids": current, "aggregation_hits": 0,
            "constraint_hits": constraint_hits, "sibling_links": sibling_links}


def _mean(rows, key, split=None):
    chosen = [row for row in rows if split is None or row["split"] == split]
    return sum(row[key] for row in chosen) / len(chosen)


def run(out_dir: Path, candidates: Path, *, target: float = .99) -> dict:
    started = time.perf_counter()
    out_dir = out_dir.resolve()
    tuning = json.loads((out_dir / "retrieval_tuning.json").read_text())
    cached = json.loads(candidates.read_text())
    questions, _provenance = load_questions()
    qmap = {question.question_id: question for question in questions if question.corpus == "enterpriserag"}
    connection = sqlite3.connect(f"file:{out_dir / 'canonical.sqlite'}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        docs = {row["doc_id"]: {"title": row["title"] or "", "text": row["text"] or ""}
                for row in connection.execute(
                    "SELECT doc_id,title,text FROM documents WHERE corpus='enterpriserag'")}
    finally:
        connection.close()
    rows = []
    for source in tuning["rows"]:
        question = qmap[source["question_id"]]
        pool = cached["candidates"][question.question_id]["rrf"][:800]
        tick = time.perf_counter()
        ranked = rerank(question.text, source["document_ids"], pool, docs)
        elapsed = (time.perf_counter() - tick) * 1000
        recall = document_recall(question.gold, ranked["document_ids"])
        rows.append({
            "question_id": question.question_id,
            "question_type": source["question_type"],
            "split": source["split"],
            "baseline_recall10": source["document_recall10"],
            "document_recall10": recall,
            "candidate_oracle_recall": source["candidate_oracle_recall"],
            "rerank_input_oracle_recall": source["rerank_input_oracle_recall"],
            "document_ids": ranked["document_ids"],
            "reference_document_ids": list(question.gold),
            "aggregation_hits": ranked["aggregation_hits"],
            "constraint_hits": ranked["constraint_hits"],
            "sibling_links": ranked["sibling_links"],
            "rank_ms": elapsed,
        })
    timings = [row["rank_ms"] for row in rows]
    dev = _mean(rows, "document_recall10", "development")
    validation = _mean(rows, "document_recall10", "validation")
    report = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "applied_to_serving": False,
        "target_recall10": target,
        "target_met": dev >= target and validation >= target and _mean(rows, "document_recall10") >= target,
        "metric": "Final evidence-document Recall@10. Candidate oracle is reported separately.",
        "questions": len(rows),
        "baseline_recall10": tuning["all_recall10"],
        "development_recall10": dev,
        "validation_recall10": validation,
        "all_recall10": _mean(rows, "document_recall10"),
        "candidate_oracle_recall": _mean(rows, "candidate_oracle_recall"),
        "rerank_input_oracle_recall": _mean(rows, "rerank_input_oracle_recall"),
        "store_sha256": tuning["store_sha256"],
        "configuration": {
            "base_ranking": "tuned BGE top-10 from retrieval_tuning.json",
            "candidate_pool": "saved RRF top 800",
            "min_constraints": MIN_CONSTRAINTS,
            "max_constraint_hits": MAX_CONSTRAINT_HITS,
            "window_chars": WINDOW_CHARS,
            "sibling_seeds": SIBLING_SEEDS,
            "sibling_slots": SIBLING_SLOTS,
            "sibling_router": "end-to-end, across all, how many, complete, go/no-go",
            "aggregation": "not applied; class-predicate fill did not raise Recall@10",
        },
        "rank_only_ms": {"p50": percentile(timings, .5), "p95": percentile(timings, .95),
                         "total": (time.perf_counter() - started) * 1000},
        "changed_questions": sum(row["document_recall10"] != row["baseline_recall10"] for row in rows),
        "notes": [
            "Reference IDs are used only after ranking, to score Recall@10.",
            "Sibling slot count was not selected on validation; development scores tied and the middle setting is fixed.",
            "This fork does not replace the reranker and does not change the port-7860 service.",
            "Gold document IDs are unchanged.",
            "A constraint set larger than the ten result slots is left unused; smaller sets are placed ahead of the tuned ranking.",
            "Class-predicate fill for 'across all' was measured and not applied: on qst_0437 it swapped tuned documents without raising Recall@10.",
        ],
        "rows": rows,
    }
    path = out_dir / "ranking_fork.json"
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(report, indent=2) + "\n")
    temporary.replace(path)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "runtime/part_a")
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--target", type=float, default=.99)
    args = parser.parse_args()
    report = run(args.out, args.candidates, target=args.target)
    print(json.dumps({key: report[key] for key in (
        "all_recall10", "development_recall10", "validation_recall10", "baseline_recall10",
        "changed_questions", "target_met", "applied_to_serving")}, indent=2))
    return 0 if report["target_met"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
