"""Reproducible Part A retrieval evaluation; no model judge or API calls."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from importlib.metadata import PackageNotFoundError, version
import json
import math
import os
from pathlib import Path
import platform
import random
import resource
import sqlite3
import time

from contextledger.search import MODES, search

ERAG_REVISION = "69916e31c68aa5963c00248fd7f0bc12d04fd235"
ORG_REVISION = "f2a1ab2ac94043f20ad4d15fc2bbc60c09332656"


@dataclass(frozen=True)
class Question:
    question_id: str
    corpus: str
    text: str
    gold: tuple[str, ...]
    kind: str
    principal_id: str
    as_of_day: int | None = None


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def document_scores(gold: tuple[str, ...], ranked: list[str], k: int) -> dict | None:
    expected = set(gold)
    if not expected:
        return None
    found = list(dict.fromkeys(ranked))[:k]
    matches = expected.intersection(found)
    first = next((i for i, doc_id in enumerate(found, 1) if doc_id in expected), None)
    return {
        "recall": len(matches) / len(expected),
        "hit": float(bool(matches)),
        "all_evidence": float(matches == expected),
        "reciprocal_rank": 1 / first if first else 0.0,
    }


def _read_rows(path: Path) -> list[dict]:
    if path.suffix == ".parquet":
        import pyarrow.parquet as pq

        return pq.read_table(path).to_pylist()
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".json":
        rows = json.loads(text)
        if not isinstance(rows, list):
            raise ValueError("questions JSON must contain an array")
        return rows
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def load_questions(erag_path: Path | None = None) -> tuple[list[Question], dict]:
    from huggingface_hub import hf_hub_download

    specs = [
        ("enterpriserag", "onyx-dot-app/EnterpriseRAG-Bench", ERAG_REVISION,
         "data/questions/test.parquet", erag_path),
        ("orgforge", "aeriesec/orgforge", ORG_REVISION,
         "questions/eval_questions.jsonl", None),
    ]
    questions = []
    provenance = {}
    seen = set()
    for corpus, repo, revision, filename, override in specs:
        path = override or Path(hf_hub_download(repo, filename, repo_type="dataset", revision=revision))
        rows = _read_rows(path)
        provenance[corpus] = {
            "repository": repo, "revision": revision if override is None else None,
            "questions_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "questions": len(rows), "custom_questions": override is not None,
        }
        for row in rows:
            qid = row["question_id"]
            if (corpus, qid) in seen:
                raise ValueError(f"duplicate question: {corpus}/{qid}")
            seen.add((corpus, qid))
            if corpus == "enterpriserag":
                text, gold = row["question"], row["expected_doc_ids"]
                principal, day = "enterpriserag:engineer", None
            else:
                text = row["question_text"]
                truth = row["ground_truth"]
                if row["question_type"] == "PERSPECTIVE":
                    gold = truth.get("evidence_artifacts", [])
                    principal = f"orgforge:{row['actor']}"
                    day = int(row["as_of_day"])
                elif row["question_type"] == "COUNTERFACTUAL":
                    gold = [item for group in truth.get("evidence_chain_artifacts", {}).values() for item in group]
                    gold += truth.get("alternative_cause_artifacts", [])
                    principal, day = "orgforge:Jax", 60
                else:
                    gold = truth.get("expected_search_space", [])
                    principal, day = "orgforge:Jax", 60
            if not isinstance(text, str) or not text.strip() or not isinstance(gold, list):
                raise ValueError(f"invalid question: {corpus}/{qid}")
            questions.append(Question(qid, corpus, text, tuple(dict.fromkeys(gold)),
                                      row["question_type"], principal, day))
    return questions, provenance


def classify_questions(connection: sqlite3.Connection, questions: list[Question]) -> tuple[dict, dict]:
    documents = defaultdict(set)
    for row in connection.execute("SELECT corpus, doc_id FROM documents"):
        documents[row["corpus"]].add(row["doc_id"])
    coverage = defaultdict(Counter)
    labels = {}
    for q in questions:
        missing = sorted(set(q.gold) - documents[q.corpus])
        status = "no_reference_evidence" if not q.gold else "missing_evidence" if missing else "fully_covered"
        labels[(q.corpus, q.question_id)] = (status, missing)
        coverage[q.corpus][status] += 1
        coverage[q.corpus]["reference_documents"] += len(set(q.gold))
        coverage[q.corpus]["imported_reference_documents"] += len(set(q.gold) & documents[q.corpus])
    return {key: dict(value) for key, value in coverage.items()}, labels


def _summarize(rows: list[dict], cutoffs: tuple[int, ...]) -> dict:
    latencies = [latency for row in rows for latency in row["latency_ms"]]
    covered = [row for row in rows if row["coverage"] == "fully_covered"]
    with_reference = [row for row in rows if row["scores"] is not None]

    def average(items, key, k):
        return sum(row["scores"][str(k)][key] for row in items) / len(items) if items else None

    return {
        "queries": len(rows), "measurements": len(latencies),
        "scored_fully_covered_queries": len(covered),
        "latency_ms": {"p50": percentile(latencies, .5), "p95": percentile(latencies, .95),
                       "p99": percentile(latencies, .99), "mean": sum(latencies) / len(latencies) if latencies else None},
        "serial_queries_per_second": len(latencies) * 1000 / sum(latencies) if sum(latencies) else None,
        "top_k": {str(k): {
            "document_recall": average(covered, "recall", k),
            "hit_rate": average(covered, "hit", k),
            "all_evidence_rate": average(covered, "all_evidence", k),
            "mrr": average(covered, "reciprocal_rank", k),
            "all_reference_questions_recall": average(with_reference, "recall", k),
        } for k in cutoffs},
    }


def evaluate_retrieval(connection: sqlite3.Connection, questions: list[Question], *,
                       modes: tuple[str, ...], cutoffs: tuple[int, ...], repeats: int,
                       seed: int, limit: int | None = None) -> dict:
    coverage, labels = classify_questions(connection, questions)
    selected = list(questions)
    random.Random(seed).shuffle(selected)
    if limit is not None:
        selected = selected[:limit]
    max_k = max(cutoffs)
    rows = []
    for mode in modes:
        for i, q in enumerate(selected):
            latencies = []
            ranked = []
            for _ in range(repeats):
                started = time.perf_counter()
                result = search(connection, corpus=q.corpus, query=q.text,
                                principal_id=q.principal_id, as_of_day=q.as_of_day, limit=max_k, mode=mode)
                latencies.append((time.perf_counter() - started) * 1000)
                if result.get("error"):
                    raise RuntimeError(result["error"])
                current = list(dict.fromkeys(hit["doc_id"] for hit in result["hits"]))
                if latencies[:-1] and current != ranked:
                    raise RuntimeError(f"unstable results: {q.question_id}/{mode}")
                ranked = current
            status, missing = labels[(q.corpus, q.question_id)]
            rows.append({"question_id": q.question_id, "corpus": q.corpus, "question_type": q.kind,
                         "principal_id": q.principal_id, "as_of_day": q.as_of_day, "mode": mode,
                         "coverage": status, "missing_evidence": missing,
                         "document_ids": ranked, "reference_document_ids": list(q.gold),
                         "latency_ms": latencies,
                         "scores": {str(k): document_scores(q.gold, ranked, k) for k in cutoffs} if q.gold else None})
            if (i + 1) % 100 == 0:
                print(f"eval {mode}: {i + 1}/{len(selected)} queries", flush=True)
    groups = defaultdict(list)
    for row in rows:
        groups[(row["corpus"], row["mode"])].append(row)
    summary = {}
    for (corpus, mode), items in groups.items():
        by_type = defaultdict(list)
        for row in items:
            by_type[row["question_type"]].append(row)
        summary.setdefault(corpus, {})[mode] = {
            **_summarize(items, cutoffs),
            "by_question_type": {kind: _summarize(group, cutoffs) for kind, group in sorted(by_type.items())},
        }
    return {
        "coverage_all_questions": coverage, "summary": summary, "queries": rows,
        "notes": [
            "Primary scores include only questions with every reference document imported; their original reference sets are unchanged.",
            "All-reference scores include missing-evidence questions, exposing corpus coverage losses.",
            "EnterpriseRAG scores measure reference-document retrieval, not ANN agreement or answer correctness.",
            "OrgForge scores are artifact-retrieval proxies: SILENCE uses the expected search space; causal/perspective reasoning is not scored.",
            "Questions without reference evidence are queried for latency only; retrieval cannot establish correct abstention.",
            "Precision is not computed: non-reference documents are not necessarily irrelevant.",
            "Latency includes in-process identity, query embedding, retrieval, ACL/time filtering, fusion and snippets; excludes HTTP and generation.",
        ],
    }


def evaluate_ann(out_dir: Path, questions: list[Question], *, samples: int, seed: int) -> dict:
    if samples == 0:
        return {"status": "not_measured", "reason": "disabled with --ann-queries 0"}
    import faiss
    import numpy as np
    from contextledger import vectors

    directory = out_dir / "vectors/enterpriserag"
    status = json.loads((directory / "status.json").read_text())
    n, dim = int(status["rows"]), int(status["dim"])
    embeddings = directory / "embeddings.f32"
    if not embeddings.exists():
        return {"status": "not_measured", "reason": "retained embeddings.f32 is required for exact ground truth"}
    if embeddings.stat().st_size != n * dim * 4:
        raise ValueError("embedding file size does not match the index")
    chosen = [q for q in questions if q.corpus == "enterpriserag"]
    random.Random(seed).shuffle(chosen)
    chosen = chosen[:samples]
    if not chosen:
        return {"status": "not_measured", "reason": "no EnterpriseRAG queries"}
    data = np.memmap(embeddings, dtype=np.float32, mode="r", shape=(n, dim))
    exact = faiss.IndexFlatIP(dim)
    exact.add(data)
    store = vectors.get_store(out_dir, "enterpriserag")
    k = min(80, n)
    recalls, latencies = [], []
    for q in chosen:
        vector = vectors._embed_query(q.text)
        _, expected = exact.search(vector, k)
        started = time.perf_counter()
        ids, dists = store.index.search(vector, k, store.nprobe, True, 1)
        latencies.append((time.perf_counter() - started) * 1000)
        found = {row_id for row_id, _ in vectors._neighbors(ids[0], dists[0], n)}
        recalls.append(len(found & set(expected[0].tolist())) / k)
    return {
        "status": "measured", "corpus": "enterpriserag", "queries": len(chosen), "k": k,
        "unfiltered_chunk_id_recall": sum(recalls) / len(recalls),
        "index_only_latency_ms": {"p50": percentile(latencies, .5), "p95": percentile(latencies, .95),
                                  "p99": percentile(latencies, .99)},
        "ground_truth": "exact FlatIP over all retained normalized chunk embeddings; no ACL",
        "nprobe": store.nprobe, "nbits": status["nbits"], "dim": dim,
        "notes": "Index timing excludes query embedding, SQL, ACL and document deduplication. Equal-distance IDs are not interchangeable in this overlap metric.",
    }


def resources(out_dir: Path, connection: sqlite3.Connection) -> dict:
    corpora = {}
    for row in connection.execute("SELECT corpus, count(*) n FROM documents GROUP BY corpus"):
        corpus = row["corpus"]
        directory = out_dir / "vectors" / corpus
        corpora[corpus] = {
            "documents": row["n"],
            "by_source": {item["source"]: item["n"] for item in connection.execute(
                "SELECT source,count(*) n FROM documents WHERE corpus=? GROUP BY source", (corpus,))},
            "chunks": connection.execute("SELECT count(*) FROM chunks WHERE corpus=?", (corpus,)).fetchone()[0],
            "ivf_index_bytes": (directory / "ivf.index").stat().st_size if (directory / "ivf.index").exists() else None,
            "vector_artifacts_bytes": sum(p.stat().st_size for p in directory.rglob("*") if p.is_file()),
        }
    digest = hashlib.sha256()
    for row in connection.execute("SELECT corpus,doc_id,content_hash,acl_json,day FROM documents ORDER BY corpus,doc_id"):
        digest.update(json.dumps(tuple(row), ensure_ascii=False).encode())
        digest.update(b"\n")
    for row in connection.execute("SELECT * FROM principals ORDER BY principal_id"):
        digest.update(json.dumps(tuple(row), ensure_ascii=False).encode())
        digest.update(b"\n")
    return {"corpora": corpora, "store_sha256": digest.hexdigest(),
            "canonical_database_bytes": (out_dir / "canonical.sqlite").stat().st_size}


def environment() -> dict:
    packages = {}
    for package in ("numpy", "torch", "sentence-transformers", "faiss-cpu", "pyarrow"):
        try:
            packages[package] = version(package)
        except PackageNotFoundError:
            packages[package] = None
    cpuinfo = Path("/proc/cpuinfo")
    cpu = platform.processor()
    if cpuinfo.exists():
        cpu = next((line.split(":", 1)[1].strip() for line in cpuinfo.read_text().splitlines()
                    if line.startswith("model name")), cpu)
    provenance_path = Path(__file__).resolve().parents[1] / "runtime/rabitq-dist/source.json"
    return {"python": platform.python_version(), "platform": platform.platform(), "cpu": cpu,
            "cpu_affinity": sorted(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else None,
            "packages": packages,
            "native_bindings": json.loads(provenance_path.read_text()) if provenance_path.exists() else None,
            "peak_benchmark_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
            "memory_note": "Process peak includes model, retained vectors, exact ground truth and synthetic scenarios; not serving-index memory."}


def run_evaluation(out_dir: Path, *, modes: tuple[str, ...] = MODES,
                   cutoffs: tuple[int, ...] = (1, 5, 10, 20), repeats: int = 1,
                   seed: int = 42, limit: int | None = None, ann_queries: int = 32,
                   questions_path: Path | None = None, threads: int = 1) -> dict:
    if not modes or any(mode not in MODES for mode in modes):
        raise ValueError("select keyword, vector and/or hybrid")
    if not cutoffs or min(cutoffs) < 1 or max(cutoffs) > 80:
        raise ValueError("top-k must be between 1 and 80")
    if repeats < 1 or threads < 1 or ann_queries < 0 or (limit is not None and limit < 1):
        raise ValueError("repeats, threads and limit must be positive; ann-queries must be nonnegative")
    out_dir = out_dir.resolve()
    db_path = out_dir / "canonical.sqlite"
    if not db_path.exists():
        raise FileNotFoundError(f"missing {db_path}; run Part A setup first")
    started = time.perf_counter()
    questions, provenance = load_questions(questions_path)
    # Read-only evaluation never changes the live corpus or its ACLs.
    connection = sqlite3.connect(db_path.as_uri() + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        resource_stats = resources(out_dir, connection)
        if any(mode != "keyword" for mode in modes) or ann_queries:
            import faiss
            import torch
            from contextledger import vectors

            torch.set_num_threads(threads)
            faiss.omp_set_num_threads(threads)
            warmup_started = time.perf_counter()
            for corpus in ("enterpriserag", "orgforge"):
                vectors.get_store(out_dir, corpus)
                vectors._embed_query("evaluation warmup")
            warmup_seconds = time.perf_counter() - warmup_started
        else:
            warmup_seconds = 0.0
        retrieval = evaluate_retrieval(connection, questions, modes=tuple(dict.fromkeys(modes)),
                                       cutoffs=tuple(sorted(set(cutoffs))), repeats=repeats,
                                       seed=seed, limit=limit)
    finally:
        connection.close()
    ann = evaluate_ann(out_dir, questions, samples=ann_queries, seed=seed)
    from contextledger.eval_scenarios import evaluate_scenarios

    scenarios = evaluate_scenarios(modes=tuple(dict.fromkeys(modes)))
    report = {
        "schema_version": 1, "created_at": datetime.now(timezone.utc).isoformat(),
        "configuration": {"seed": seed, "modes": list(modes), "top_k": list(cutoffs),
                          "repeats": repeats, "limit": limit, "threads": threads,
                          "concurrency": 1, "ann_queries": ann_queries,
                          "vector_chunk_candidates": 80,
                          "keyword_candidate_window": max(max(cutoffs) * 10, 50),
                          "warmup": "Model and native indexes warmed; queries measured once per repeat; OS cache is not controlled."},
        "environment": environment(),
        "datasets": provenance, "resources": resource_stats, "warmup_seconds": warmup_seconds,
        "retrieval": retrieval, "ann": ann, "scenarios": scenarios,
        "not_measured": {
            "answer_quality_citations_abstention_tokens_ttft_cost": "Part A has no answer-generation chain; no LLM judge/API was called.",
            "ingest_and_embedding_throughput": "Existing build has no full stage timing; this run reuses it without rebuilding the live dataset.",
            "live_source_update_visibility": "Requires source-update notifications and a serving sync pipeline; historical as-of filtering is tested separately.",
            "vector_insert_delete_concurrency": "Current pinned RaBitQ binding has no add/remove API; no streaming claim is made.",
            "source_native_acl_fidelity": "Synthetic effective ACL fixtures test enforcement, not complete connector-native policy semantics.",
            "login_session_and_admin_ui": "Part A currently uses principal IDs; login/admin integration requires separate end-to-end testing.",
            "browser_identity_switch_cache_and_prompt_leakage": "Backend identity switching is tested; browser/session caching and prompt/answer leakage require the integrated UI/generation chain.",
        },
        "references": ["https://github.com/onyx-dot-app/EnterpriseRAG-Bench",
                       "https://huggingface.co/datasets/aeriesec/orgforge",
                       "https://github.com/CGCL-codes/CANDOR-Bench"],
        "seconds": time.perf_counter() - started,
    }
    report_path = out_dir / "evaluation.json"
    temporary = report_path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(report_path)
    print(f"Evaluation saved to {report_path}", flush=True)
    for corpus, modes_summary in retrieval["summary"].items():
        for mode, summary in modes_summary.items():
            chosen_k = "10" if "10" in summary["top_k"] else next(iter(summary["top_k"]))
            recall = summary["top_k"][chosen_k]["document_recall"]
            print(f"{corpus}/{mode}: document recall@{chosen_k}={recall} p95={summary['latency_ms']['p95']:.2f} ms "
                  f"covered={summary['scored_fully_covered_queries']}/{summary['queries']}", flush=True)
    print(f"Returned-evidence checks: {scenarios['passed']}/{scenarios['total']}; "
          f"pre-retrieval candidate isolation: {scenarios['gates']['pre_retrieval_candidate_isolation']}", flush=True)
    return report
