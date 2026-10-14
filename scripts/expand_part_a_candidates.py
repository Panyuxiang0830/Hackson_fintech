"""Measure candidate coverage from local query rewriting and additional searches."""

from __future__ import annotations

import argparse
import gc
import hashlib
import itertools
import json
from pathlib import Path
import re
import sqlite3
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from contextledger.evaluation import load_questions, resources
from contextledger.search import _rrf
from scripts.compare_part_a_rerankers import atomic_json, candidate_cache_signature
from scripts.tune_part_a_retrieval import document_recall, fts_match, KINDS, query_terms, visible_rankings

REWRITE_MODEL = "Qwen/Qwen3-4B-Instruct-2507"
REWRITE_REVISION = "cdbee75f17c01a7cc42f958dc650907174af0554"
PROMPT = (
    "Rewrite an enterprise document search question into two complementary search queries. "
    "Use standard technical terminology and synonyms for concepts described indirectly. "
    "Preserve all explicit entities, dates, numbers, environments and technical constraints. "
    "Do not answer the question or invent the cause, customer name, incident, date or document ID. "
    "When the question asks for unknown thresholds or configuration keys, keep asking for them; "
    "NEVER guess their values or identifiers. Phrase both rewrites as questions. "
    "For aggregation, search for its constituent evidence. Each query must be at most 40 words. "
    'Return ONLY a JSON array of two strings, without explanations.'
)


def parse_rewrites(text):
    result = []
    decoder = json.JSONDecoder()
    cursor = 0
    while len(result) < 2:
        start = text.find("[", cursor)
        if start == -1:
            break
        values, end = decoder.raw_decode(text[start:])
        if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
            raise ValueError("rewrite output must contain string arrays")
        result.extend(values)
        cursor = start + end
    if len(result) < 2 or not all(value.strip() and len(value) <= 2000 for value in result):
        raise ValueError("rewrites require two nonempty bounded strings")
    result = result[:2]
    if any(re.search(r"dsid_[0-9a-f]+", value) for value in result):
        raise ValueError("document IDs are not permitted in generated queries")
    return [value.strip() for value in result]


def faithful_rewrites(original, rewrites):
    allowed = set(re.findall(r"\d+(?:\.\d+)?", original))
    for word, number in [("one", "1"), ("two", "2"), ("three", "3"), ("single", "1")]:
        if re.search(r"\b" + word + r"\b", original, re.I):
            allowed.add(number)
    if re.search(r"half.?precision", original, re.I):
        allowed.add("16")
    if re.search(r"first hour", original, re.I):
        allowed.add("60")
    if re.search(r"tail latency", original, re.I):
        allowed.update(["95", "99"])
    return [value for value in rewrites if set(re.findall(r"\d+(?:\.\d+)?", value)) <= allowed]


def rewrite(questions, cache, device):
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    signature = hashlib.sha256(json.dumps({"model": REWRITE_MODEL, "revision": REWRITE_REVISION,
        "prompt": PROMPT, "device": device,
        "queries": [[q.question_id, q.text] for q in questions]}).encode()).hexdigest()
    path = cache / "rewrites.json"
    result = json.loads(path.read_text()) if path.exists() else {"signature": signature, "queries": {}, "errors": {}}
    if result["signature"] != signature:
        raise ValueError("rewrite cache belongs to another experiment")
    remaining = [q for q in questions if q.question_id not in result["queries"]]
    if not remaining:
        return result
    tokenizer = AutoTokenizer.from_pretrained(REWRITE_MODEL, revision=REWRITE_REVISION, padding_side="left")
    model = AutoModelForCausalLM.from_pretrained(REWRITE_MODEL, revision=REWRITE_REVISION,
        dtype=torch.bfloat16, attn_implementation="sdpa").to(device).eval()
    started = time.perf_counter()
    try:
        with torch.inference_mode():
            for start in range(0, len(remaining), 8):
                batch = remaining[start:start + 8]
                prompts = [tokenizer.apply_chat_template(
                    [{"role": "system", "content": PROMPT}, {"role": "user", "content": q.text}],
                    tokenize=False, add_generation_prompt=True) for q in batch]
                inputs = tokenizer(prompts, padding=True, return_tensors="pt").to(device)
                outputs = model.generate(**inputs, max_new_tokens=256, do_sample=False,
                                         pad_token_id=tokenizer.pad_token_id)
                texts = tokenizer.batch_decode(outputs[:, inputs["input_ids"].shape[1]:], skip_special_tokens=True)
                for q, text in zip(batch, texts):
                    try:
                        values = faithful_rewrites(q.text, parse_rewrites(text))
                        if not values:
                            raise ValueError("rewrites introduced unsupported numeric values")
                        result["queries"][q.question_id] = values
                    except (ValueError, TypeError) as error:
                        result["queries"][q.question_id] = []
                        result["errors"][q.question_id] = str(error)
                result["generation_seconds"] = time.perf_counter() - started
                atomic_json(path, result)
                print(f"rewrite: {len(result['queries'])}/{len(questions)}", flush=True)
    finally:
        del model
        gc.collect()
        if device == "cuda":
            torch.cuda.empty_cache()
    return result


def expand(connection, questions, original, rewrites, out, device):
    from contextledger import vectors
    from sentence_transformers import SentenceTransformer

    vectors.get_store(out, "enterpriserag").nprobe = 768
    vectors._MODEL = SentenceTransformer(vectors.MODEL_NAME, device=device)
    max_frequency = .4 * connection.execute(
        "SELECT count(*) FROM documents WHERE corpus='enterpriserag'").fetchone()[0]
    frequency = {}
    result, rows = {}, []
    for q in questions:
        routes = [original[q.question_id]["rrf"][800:]]
        for query in [q.text] + rewrites[q.question_id]:
            match = fts_match(query)
            if not match:
                continue
            routes.append([r[0] for r in connection.execute(
                "SELECT doc_id FROM docs_fts WHERE docs_fts MATCH ? AND corpus=? ORDER BY bm25(docs_fts,0,0,0,5,1) LIMIT 800",
                (match, q.corpus))])
            if query != q.text:
                routes.append([hit["doc_id"] for hit in vectors.search_chunks(out, q.corpus, query, k=1600)])
            viable = []
            for term in query_terms(query):
                token = fts_match(term)
                if not token:
                    continue
                if token not in frequency:
                    frequency[token] = connection.execute(
                        "SELECT count(*) FROM docs_fts WHERE docs_fts MATCH ? AND corpus=?", (token, q.corpus)).fetchone()[0]
                count = frequency[token]
                if 0 < count < max_frequency:
                    viable.append((count, token))
            for a, b in itertools.combinations(sorted(viable)[:8], 2):
                routes.append([r[0] for r in connection.execute(
                    "SELECT doc_id FROM docs_fts WHERE docs_fts MATCH ? AND corpus=? ORDER BY bm25(docs_fts,0,0,0,5,1) LIMIT 80",
                    (f"({a[1]}) AND ({b[1]})", q.corpus))])
        for kind in KINDS:
            if re.search(r"\b" + kind + r"(?:s|ies)?\b", q.text.lower()):
                routes.append([r[0] for r in connection.execute(
                    "SELECT doc_id FROM docs_fts WHERE docs_fts MATCH ? AND corpus=? ORDER BY bm25(docs_fts) LIMIT 5000",
                    ('title: "' + kind + '"*', q.corpus))])
        supplement = visible_rankings(connection, q, {"supplement": _rrf(routes)})["supplement"]
        base = original[q.question_id]["rrf"][:800]
        base_set = set(base)
        extra = [did for did in supplement if did not in base_set]
        pool = base + extra[:400]
        union = list(dict.fromkeys(original[q.question_id]["rrf"] + supplement))
        result[q.question_id] = {"rrf": pool, "union": union}
        rows.append({"question_id": q.question_id, "question_type": q.kind,
            "rewrites": rewrites[q.question_id], "document_budget": len(pool),
            "original_pool_oracle": document_recall(q.gold, base, len(base)),
            "expanded_pool_oracle": document_recall(q.gold, pool, len(pool)),
            "expanded_union_oracle": document_recall(q.gold, union, len(union))})
        if len(rows) % 20 == 0:
            print(f"expand: {len(rows)}/{len(questions)}", flush=True)
    return result, rows


def main():
    import faiss
    import torch

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "runtime/part_a")
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--device", choices=["auto", "cpu", "cuda"], default="auto")
    args = parser.parse_args()
    torch.set_num_threads(8)
    faiss.omp_set_num_threads(8)
    device = ("cuda" if torch.cuda.is_available() else "cpu") if args.device == "auto" else args.device
    out = args.out.resolve()
    previous = json.loads((out / "retrieval_tuning.json").read_text())
    base = json.loads((args.cache / "candidates.json").read_text())
    qmap = {q.question_id: q for q in load_questions()[0] if q.corpus == "enterpriserag"}
    questions = [qmap[row["question_id"]] for row in previous["rows"]]
    expected = candidate_cache_signature(previous["store_sha256"], [q.question_id for q in questions],
                                        previous["configuration"])
    if base["signature"] != expected:
        raise ValueError("base candidate cache belongs to a different store or experiment")
    connection = sqlite3.connect(f"file:{out / 'canonical.sqlite'}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        if resources(out, connection)["store_sha256"] != previous["store_sha256"]:
            raise ValueError("store changed")
        rewrites = rewrite(questions, args.cache, device)
        started = time.perf_counter()
        candidates, rows = expand(connection, questions, base["candidates"], rewrites["queries"], out, device)
        atomic_json(args.cache / "expanded_candidates.json", {
            "signature": base["signature"], "candidates": candidates,
            "expansion_configuration": {"model": REWRITE_MODEL, "revision": REWRITE_REVISION,
                                        "device": device,
                                        "prompt": PROMPT, "preserved_base_documents": 800,
                                        "additional_documents": 400}})
        report = {"questions": len(rows), "applied_to_serving": False, "target_met": False,
            "metric": "Candidate oracle coverage; not final document Recall@10",
            "store_sha256": previous["store_sha256"], "rewrite_model": REWRITE_MODEL,
            "device": device, "inference_dtype": "bfloat16",
            "rewrite_revision": REWRITE_REVISION, "rewrite_errors": rewrites["errors"],
            "generation_seconds": rewrites.get("generation_seconds"), "expansion_seconds": time.perf_counter()-started,
            "original_pool_oracle": sum(r["original_pool_oracle"] for r in rows)/len(rows),
            "expanded_pool_oracle": sum(r["expanded_pool_oracle"] for r in rows)/len(rows),
            "expanded_union_oracle": sum(r["expanded_union_oracle"] for r in rows)/len(rows), "rows": rows}
        atomic_json(out / "candidate_expansion.json", report)
        print(json.dumps({k:v for k,v in report.items() if k != "rows"}, indent=2))
    finally:
        connection.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
