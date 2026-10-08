"""Compare local rerankers on the same authorized evidence candidates."""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import gc
import hashlib
from importlib.metadata import PackageNotFoundError, version
import json
import math
from pathlib import Path
import sqlite3
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from contextledger.evaluation import document_scores, load_questions, percentile, resources
from scripts.tune_part_a_retrieval import (
    collect_candidates, document_recall, passage, RERANK_MODEL, RERANK_REVISION,
)

MODELS = {
    "bge": (RERANK_MODEL, RERANK_REVISION),
    "qwen": ("Qwen/Qwen3-Reranker-4B", "22e683669bc0f0bd69640a1354a6d0aebcfeede5"),
    "jina": ("jinaai/jina-reranker-v3.5", "e8a93f33f0b22108f8c2364f8484ce3422552fbc"),
}
INSTRUCTION = (
    "Retrieve original enterprise documents that provide evidence needed to answer the query. "
    "Respect explicit entity, environment, date, model size, precision and batch size constraints. "
    "Prefer direct evidence over related topics. For comparisons and aggregation, a document "
    "covering one required part is relevant; it need not answer every part."
)


def atomic_json(path, data):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2) + "\n")
    temporary.replace(path)


def candidate_cache_signature(snapshot, question_ids, configuration):
    return hashlib.sha256(json.dumps({"snapshot": snapshot, "questions": question_ids,
        "candidate_config": configuration, "version": 1}, sort_keys=True).encode()).hexdigest()


def rank_scores(ids, scores):
    if len(ids) != len(scores) or len(set(ids)) != len(ids):
        raise ValueError("scores require one value per unique candidate")
    if not all(math.isfinite(float(score)) for score in scores):
        raise ValueError("non-finite reranker scores")
    return [ids[i] for i in sorted(range(len(ids)), key=lambda i: -float(scores[i]))]


def summarize_rows(rows):
    groups = defaultdict(list)
    for row in rows:
        groups["all"].append(row)
        groups[row["split"]].append(row)
        groups["type:" + row["question_type"]].append(row)
    return {key: {
        "questions": len(items),
        "document_recall10": sum(r["document_recall10"] for r in items) / len(items),
        "all_evidence_hit10": sum(r["all_evidence_hit10"] for r in items) / len(items),
        "candidate_oracle_recall": sum(r["candidate_oracle_recall"] for r in items) / len(items),
        "retrieval_pool_oracle_recall": sum(r.get("retrieval_pool_oracle_recall", r["candidate_oracle_recall"])
                                            for r in items) / len(items),
        "rerank_only_ms": {"p50": percentile([r["rerank_ms"] for r in items], .5),
                           "p95": percentile([r["rerank_ms"] for r in items], .95)},
        "local_reranking_pipeline_ms": {
            "p50": percentile([r["rerank_ms"] + r.get("preselection_ms", 0) for r in items], .5),
            "p95": percentile([r["rerank_ms"] + r.get("preselection_ms", 0) for r in items], .95)},
    } for key, items in groups.items()}


class Reranker:
    def __init__(self, name, device, max_tokens, batch_size):
        import torch
        from transformers import AutoModel, AutoModelForCausalLM, AutoTokenizer

        torch.set_num_threads(8)
        self.name, self.device = name, device
        self.max_tokens, self.batch_size = max_tokens, batch_size
        repo, revision = MODELS[name]
        dtype = torch.bfloat16 if device == "cuda" else torch.float32
        if name == "bge":
            from sentence_transformers import CrossEncoder
            self.model = CrossEncoder(repo, revision=revision, device=device, max_length=max_tokens)
            if device == "cuda":
                self.model.model.half()
        elif name == "qwen":
            self.tokenizer = AutoTokenizer.from_pretrained(repo, revision=revision, padding_side="left")
            self.model = AutoModelForCausalLM.from_pretrained(
                repo, revision=revision, dtype=dtype, attn_implementation="sdpa").to(device).eval()
            prefix = "<|im_start|>system\nJudge whether the Document meets the requirements based on the Query and the Instruct provided. Note that the answer can only be \"yes\" or \"no\".<|im_end|>\n<|im_start|>user\n"
            suffix = "<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n"
            self.prefix = self.tokenizer.encode(prefix, add_special_tokens=False)
            self.suffix = self.tokenizer.encode(suffix, add_special_tokens=False)
            self.yes = self.tokenizer.convert_tokens_to_ids("yes")
            self.no = self.tokenizer.convert_tokens_to_ids("no")
        else:
            self.model = AutoModel.from_pretrained(
                repo, revision=revision, trust_remote_code=True, dtype=dtype,
                attn_implementation="sdpa").to(device).eval()
            # Keep the tokenizer on the inspected, pinned model revision.
            self.model._tokenizer = AutoTokenizer.from_pretrained(repo, revision=revision, padding_side="left")
            # The official implementation reserves 8192 tokens between blocks.
            self.model._tokenizer.model_max_length = 16384

    def predict(self, query, texts):
        import numpy as np
        import torch

        if not texts:
            return []
        if self.name == "bge":
            return self.model.predict([(query, text) for text in texts], batch_size=self.batch_size,
                                      activation_fct=torch.nn.Identity(), show_progress_bar=False).tolist()
        if self.name == "jina":
            tokenizer = self.model._tokenizer
            docs = [tokenizer.decode(tokenizer.encode(text, add_special_tokens=False)[:self.max_tokens])
                    for text in texts]
            results = self.model.rerank(query, docs)
            scores = [None] * len(texts)
            for row in results:
                scores[int(row["index"])] = float(row["relevance_score"])
            return scores
        prompts = [f"<Instruct>: {INSTRUCTION}\n<Query>: {query}\n<Document>: {text}" for text in texts]
        encoded = self.tokenizer(prompts, padding=False, add_special_tokens=False, truncation=True,
                                 max_length=self.max_tokens - len(self.prefix) - len(self.suffix))["input_ids"]
        tokens = [self.prefix + ids + self.suffix for ids in encoded]
        order = sorted(range(len(tokens)), key=lambda i: len(tokens[i]))
        scores = np.empty(len(texts), dtype=np.float32)
        with torch.inference_mode():
            for start in range(0, len(order), self.batch_size):
                indexes = order[start:start + self.batch_size]
                inputs = self.tokenizer.pad({"input_ids": [tokens[i] for i in indexes]},
                                            padding=True, return_tensors="pt").to(self.device)
                logits = self.model(**inputs, use_cache=False, logits_to_keep=1).logits[:, -1, :]
                values = (logits[:, self.yes].float() - logits[:, self.no].float()).cpu().numpy()
                scores[indexes] = values
        return scores.tolist()

    def close(self):
        import torch
        del self.model
        gc.collect()
        if self.device == "cuda":
            torch.cuda.empty_cache()


def _package_version(name: str):
    try:
        return version(name)
    except PackageNotFoundError:
        return None


def _hardware_name(device: str) -> str:
    if device != "cuda":
        return "CPU"
    import torch

    return torch.cuda.get_device_name()


def run(args):
    if args.device == "cpu":
        device = "cpu"
    else:
        import torch

        torch.set_num_threads(8)
        device = ("cuda" if torch.cuda.is_available() else "cpu") if args.device == "auto" else args.device
    out = args.out.resolve()
    baseline = json.loads((out / "evaluation.json").read_text())
    previous = json.loads((out / "retrieval_tuning.json").read_text())
    all_questions, provenance = load_questions()
    qmap = {q.question_id: q for q in all_questions if q.corpus == "enterpriserag"}
    full_questions = [qmap[row["question_id"]] for row in previous["rows"]]
    questions = full_questions
    if args.limit:
        questions = questions[:args.limit]
    previous_rows = {row["question_id"]: row for row in previous["rows"]}
    connection = sqlite3.connect(f"file:{out / 'canonical.sqlite'}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        snapshot = resources(out, connection)["store_sha256"]
        if snapshot != previous["store_sha256"] or snapshot != baseline["resources"]["store_sha256"]:
            raise ValueError("store changed; refresh baseline and tuning reports")
        if provenance != previous["datasets"]:
            raise ValueError("question provenance changed")
        docs = {row["doc_id"]: dict(row) for row in connection.execute(
            "SELECT doc_id,title,text,source FROM documents WHERE corpus='enterpriserag' ORDER BY doc_id")}
        args.cache.mkdir(parents=True, exist_ok=True)
        signature = candidate_cache_signature(snapshot, [q.question_id for q in full_questions],
                                              previous["configuration"])
        cache_path = args.candidates or args.cache / "candidates.json"
        if cache_path.exists():
            cached = json.loads(cache_path.read_text())
            if cached["signature"] != signature:
                raise ValueError("cache belongs to a different experiment")
            candidates = cached["candidates"]
        else:
            candidates, _ = collect_candidates(out, connection, full_questions, docs, device)
            atomic_json(cache_path, {"signature": signature, "candidates": candidates})
    finally:
        connection.close()
    report_path = args.report or out / "reranker_comparison.json"
    experiment = json.loads(json.dumps({
        "candidate_signature": signature, "document_budget": args.rerank_limit,
        "bge_preselection_limit": args.preselect_limit,
        "candidate_pool_sha256": hashlib.sha256(json.dumps(
            {q.question_id: candidates[q.question_id]["rrf"][:args.rerank_limit] for q in full_questions},
            sort_keys=True).encode()).hexdigest(),
        "model_max_tokens": args.max_tokens, "instruction": INSTRUCTION, "device": device,
        "batch_size": args.batch_size, "models": {name: MODELS[name] for name in args.models},
    }))
    report = json.loads(report_path.read_text()) if report_path.exists() else {
        "created_at": datetime.now(timezone.utc).isoformat(), "store_sha256": snapshot, "datasets": provenance,
        "configuration": experiment, "questions": len(questions), "full_regression_questions": len(previous["rows"]),
        "applied_to_serving": False, "complete": False, "target_recall10": .99, "target_met": False,
        "previous_tuned_subset_recall10": sum(previous_rows[q.question_id]["document_recall10"] for q in questions) / len(questions),
        "software": {name: _package_version(name) for name in ("torch", "transformers", "sentence-transformers")},
        "hardware": _hardware_name(device),
        "notes": ["The 180-question set has been inspected previously; this is a regression comparison, not fresh validation.",
                  "Original fixed reference IDs and Top10 are unchanged; reference IDs never enter model inputs.",
                  ("Models receive the same visible document IDs and passage text; tokenizer truncation differs."
                   if not args.preselect_limit else
                   "BGE sees the retrieval pool; Qwen/Jina see its BGE shortlist. Both coverage stages are reported."),
                  "Timing covers local reranking only, excluding model loading, candidate building, HTTP and answer generation.",
                  "Jina uses 16384-token blocks and documents truncated to model_max_tokens; all candidates are scored."],
        "results": {},
    }
    if report["configuration"] != experiment or report["questions"] != len(questions):
        raise ValueError("existing report belongs to a different experiment")
    for name in args.models:
        result = report["results"].setdefault(name, {"rows": [], "complete": False})
        done = {row["question_id"] for row in result["rows"]}
        if len(done) == len(questions):
            continue
        print(f"compare: loading {name}; {len(done)}/{len(questions)} completed", flush=True)
        model = Reranker(name, device, args.max_tokens, args.batch_size)
        selector = Reranker("bge", device, 768, args.batch_size) if args.preselect_limit and name != "bge" else None
        try:
            for q in questions:
                if q.question_id in done:
                    continue
                entry = candidates[q.question_id]
                ids = entry["rrf"][:args.rerank_limit]
                texts = [passage(docs[did], q.text) for did in ids]
                retrieval_oracle = document_recall(q.gold, ids, len(ids))
                preselection_ms = 0
                if selector is not None:
                    if device == "cuda":
                        torch.cuda.synchronize()
                    prestarted = time.perf_counter()
                    selection_scores = selector.predict(q.text, texts)
                    if device == "cuda":
                        torch.cuda.synchronize()
                    preselection_ms = (time.perf_counter() - prestarted) * 1000
                    selection = rank_scores(ids, selection_scores)[:args.preselect_limit]
                    text_map = dict(zip(ids, texts))
                    ids, texts = selection, [text_map[did] for did in selection]
                if device == "cuda":
                    torch.cuda.synchronize()
                started = time.perf_counter()
                scores = model.predict(q.text, texts)
                if device == "cuda":
                    torch.cuda.synchronize()
                elapsed = (time.perf_counter() - started) * 1000
                ranked = rank_scores(ids, scores)
                metrics = document_scores(q.gold, ranked, 10)
                row = {"question_id": q.question_id, "question_type": q.kind,
                    "split": previous_rows[q.question_id]["split"], "document_ids": ranked[:10],
                    "reference_document_ids": list(q.gold), "document_recall10": metrics["recall"],
                    "all_evidence_hit10": metrics["all_evidence"], "rerank_ms": elapsed,
                    "preselection_ms": preselection_ms, "retrieval_pool_oracle_recall": retrieval_oracle,
                    "candidate_oracle_recall": document_recall(q.gold, ids, len(ids)),
                    "union_oracle_recall": document_recall(q.gold, entry.get("union", entry["rrf"]),
                        len(entry.get("union", entry["rrf"]))),
                    "scored_candidates": len(ids)}
                if name == "bge":
                    row["preselection_oracle_at_k"] = {
                        str(k): document_recall(q.gold, ranked, k) for k in (50, 100, 200, 400, 800)}
                result["rows"].append(row)
                result["summary"] = summarize_rows(result["rows"])
                atomic_json(report_path, report)
                print(f"compare {name}: {len(result['rows'])}/{len(questions)} {q.question_id} "
                      f"recall={metrics['recall']:.3f} time={elapsed/1000:.2f}s", flush=True)
        finally:
            model.close()
            if selector is not None:
                selector.close()
        result["complete"] = True
        atomic_json(report_path, report)
    report["complete"] = all(report["results"][name]["complete"] for name in args.models)
    report["target_met"] = len(questions) == len(previous["rows"]) and any(
        result["summary"]["all"]["document_recall10"] >= .99 for result in report["results"].values())
    atomic_json(report_path, report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "runtime/part_a")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--cache", type=Path)
    parser.add_argument("--candidates", type=Path, help="Use a checked candidate-cache variant")
    parser.add_argument("--models", nargs="+", choices=MODELS, default=["bge", "qwen", "jina"])
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--rerank-limit", type=int, default=800)
    parser.add_argument("--preselect-limit", type=int, default=0, help="Optional BGE shortlist before Qwen/Jina")
    parser.add_argument("--max-tokens", type=int, default=768)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--device", choices=["auto", "cpu", "cuda"], default="auto")
    args = parser.parse_args()
    if args.limit < 0 or args.rerank_limit < 10 or args.max_tokens < 256 or args.batch_size < 1 or (
        args.preselect_limit != 0 and not 10 <= args.preselect_limit <= args.rerank_limit):
        parser.error("invalid question, candidate, token or batch budget")
    if args.cache is None:
        with tempfile.TemporaryDirectory(prefix="contextledger-rerank-") as directory:
            args.cache = Path(directory)
            report = run(args)
    else:
        report = run(args)
    print(json.dumps({name: result["summary"]["all"] for name, result in report["results"].items()}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
