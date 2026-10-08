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

from contextledger.benchmark_quality import measure_hits, measure_ingest
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
    gold_answer: str = ""
    answer_facts: tuple[str, ...] = ()
    is_answerable: bool | None = None


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
        "reference_precision": len(matches) / len(found) if found else None,
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
            gold_answer = ""
            facts: tuple[str, ...] = ()
            if corpus == "enterpriserag":
                text, gold = row["question"], row["expected_doc_ids"]
                principal, day = "enterpriserag:engineer", None
                raw_answer = row.get("gold_answer") or ""
                gold_answer = raw_answer if isinstance(raw_answer, str) else ""
                facts = _answer_facts(row.get("answer_facts"))
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
            answerable = row.get("is_answerable")
            if answerable is not None and not isinstance(answerable, bool):
                raise ValueError(f"is_answerable must be boolean: {corpus}/{qid}")
            questions.append(Question(qid, corpus, text, tuple(dict.fromkeys(gold)),
                                      row["question_type"], principal, day, gold_answer, facts, answerable))
    return questions, provenance


def _answer_facts(value) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,) if value.strip() else ()
    if isinstance(value, (list, tuple)):
        return tuple(item.strip() for item in value if isinstance(item, str) and item.strip())
    return ()


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
        values = [row["scores"][str(k)][key] for row in items if row["scores"][str(k)][key] is not None]
        return sum(values) / len(values) if values else None

    return {
        "queries": len(rows), "measurements": len(latencies),
        "scored_fully_covered_queries": len(covered),
        "scored_all_reference_queries": len(with_reference),
        "latency_ms": {"p50": percentile(latencies, .5), "p95": percentile(latencies, .95),
                       "p99": percentile(latencies, .99), "mean": sum(latencies) / len(latencies) if latencies else None},
        "serial_queries_per_second": len(latencies) * 1000 / sum(latencies) if sum(latencies) else None,
        "top_k": {str(k): {
            "document_recall": average(covered, "recall", k),
            "hit_rate": average(covered, "hit", k),
            "all_evidence_rate": average(covered, "all_evidence", k),
            "mrr": average(covered, "reciprocal_rank", k),
            "reference_precision": average(covered, "reference_precision", k),
            "all_reference_questions_recall": average(with_reference, "recall", k),
            "recall_ceiling": _mean(min(k, len(set(row["reference_document_ids"]))) /
                                    len(set(row["reference_document_ids"])) for row in covered),
            "questions_with_more_references_than_k": sum(len(set(row["reference_document_ids"])) > k
                                                        for row in covered),
        } for k in cutoffs},
    }


def evaluate_retrieval(connection: sqlite3.Connection, questions: list[Question], *,
                       modes: tuple[str, ...], cutoffs: tuple[int, ...], repeats: int,
                       seed: int, limit: int | None = None, retrieval_depth: int = 20) -> dict:
    if not cutoffs or min(cutoffs) < 1 or max(cutoffs) > retrieval_depth or retrieval_depth > 80:
        raise ValueError("top-k must be between 1 and retrieval-depth (at most 80)")
    coverage, labels = classify_questions(connection, questions)
    selected = list(questions)
    random.Random(seed).shuffle(selected)
    if limit is not None:
        selected = selected[:limit]
    rows = []
    for mode in modes:
        for i, q in enumerate(selected):
            latencies = []
            stage_measurements = []
            ranked = []
            result = {"hits": []}
            for _ in range(repeats):
                started = time.perf_counter()
                result = search(connection, corpus=q.corpus, query=q.text,
                                principal_id=q.principal_id, as_of_day=q.as_of_day, limit=retrieval_depth, mode=mode,
                                profile=True)
                latencies.append((time.perf_counter() - started) * 1000)
                stage_measurements.append(result.get("stages_ms") or {})
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
                         "latency_ms": latencies, "stage_measurements": stage_measurements,
                         "extractive_diagnostics": measure_hits(q.text, result["hits"], q.gold, gold_answer=q.gold_answer,
                                                 answer_facts=q.answer_facts, as_of_day=q.as_of_day,
                                                 is_answerable=q.is_answerable),
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
            "stages_ms": _stage_summary(items),
            "extractive_diagnostics": _extractive_summary(items),
            "by_question_type": {kind: _summarize(group, cutoffs) for kind, group in sorted(by_type.items())},
        }
    return {
        "coverage_all_questions": coverage, "summary": summary, "queries": rows,
        "extractive_method": _extractive_method(),
        "sampling": {"available_questions": len(questions), "selected_questions": len(selected),
                     "selected_questions_sha256": hashlib.sha256(json.dumps(
                         sorted((q.corpus, q.question_id) for q in selected)).encode()).hexdigest()},
        "cost": _cost_summary(rows),
        "notes": [
            "Document recall is a per-question fraction averaged over the stated population (macro recall). All-evidence rate requires every gold document in top-k.",
            "Primary scores include only questions with every reference document imported; their original reference sets are unchanged. Imported coverage does not imply ACL/time visibility.",
            "All-reference scores include missing-evidence questions, exposing corpus coverage losses.",
            "EnterpriseRAG document scores measure reference-document retrieval, not ANN agreement. Extractive answer checks are separate and are not a model judgment.",
            "OrgForge scores are artifact-retrieval proxies: SILENCE uses the expected search space; causal/perspective reasoning is not scored.",
            "reference_precision is gold overlap among returned documents. It is not full precision: non-reference documents are not proven irrelevant.",
            "Answer text is an extractive copy of overlapping sentences from authorized hit snippets. Fact coverage is lexical, not an LLM judge.",
            "Nonverbatim sentence rate is a structural copy check, not hallucination rate. Extractive copy is 0 by construction; copied evidence can still be wrong or stale.",
            "Empty reference evidence does not mean unanswerable. Abstention agreement requires an explicit is_answerable label and applies only to the extractive diagnostic.",
            "Approximate tokens are ceil(characters / 4). No API USD and no time-to-first-token are measured.",
            "Future-hit rate counts returned hits whose document day is after the question as-of day.",
            "Latency includes in-process identity, query embedding, retrieval, ACL/time filtering, fusion and snippets; excludes HTTP and generation.",
            "Stage timings are identity, retrieve, acl_filter and materialize. They are omitted from the demo response unless profile is requested.",
            "Scoring cutoffs truncate one ranking at a fixed retrieval depth; changing --top-k alone does not change candidate retrieval. Stage distributions include all repeats.",
        ],
    }


def _mean(values) -> float | None:
    kept = [value for value in values if value is not None]
    return sum(kept) / len(kept) if kept else None


def _stage_summary(rows: list[dict]) -> dict:
    buckets = defaultdict(list)
    for row in rows:
        for stages in row["stage_measurements"]:
            for name, value in stages.items():
                buckets[name].append(value)
    return {
        name: {"measurements": len(values), "p50": percentile(values, .5), "p95": percentile(values, .95), "p99": percentile(values, .99)}
        for name, values in buckets.items()
    }


def _extractive_summary(rows: list[dict]) -> dict:
    labelled = [row for row in rows if row["extractive_diagnostics"]["abstention_matches_label"] is not None]
    as_of_rows = [row for row in rows if row["as_of_day"] is not None]
    future_rows = [row for row in as_of_rows if row["extractive_diagnostics"]["future_hits"]]
    return {
        "queries": len(rows),
        "queries_with_reference_evidence": sum(bool(row["reference_document_ids"]) for row in rows),
        "queries_with_scorable_facts": sum(row["extractive_diagnostics"]["lexical_fact_overlap"] is not None for row in rows),
        "citation_recall": _mean(row["extractive_diagnostics"]["citation_recall"] for row in rows),
        "citation_reference_precision": _mean(row["extractive_diagnostics"]["citation_reference_precision"] for row in rows),
        "lexical_fact_overlap": _mean(row["extractive_diagnostics"]["lexical_fact_overlap"] for row in rows),
        "lexical_gold_answer_overlap": _mean(row["extractive_diagnostics"]["lexical_gold_answer_overlap"] for row in rows),
        "nonverbatim_sentence_rate": _mean(row["extractive_diagnostics"]["nonverbatim_sentence_rate"] for row in rows),
        "explicit_answerability_labels": len(labelled),
        "abstention_label_agreement": _mean(row["extractive_diagnostics"]["abstention_matches_label"] for row in labelled),
        "future_hit_rate": len(future_rows) / len(as_of_rows) if as_of_rows else None,
        "future_hit_queries": len(future_rows),
        "queries_with_as_of_day": len(as_of_rows),
    }


def _cost_summary(rows: list[dict]) -> dict:
    def token_stats(key):
        values = [row["extractive_diagnostics"][key] for row in rows]
        return {"p50": percentile(values, .5), "p95": percentile(values, .95), "p99": percentile(values, .99),
                "mean": _mean(values)}

    return {
        "llm_api_calls": 0,
        "llm_usd": None,
        "reason": "Extractive copy from retrieved snippets. No model API was called, so USD cost and TTFT are not measured.",
        "approx_prompt_tokens": token_stats("approx_prompt_tokens"),
        "approx_answer_tokens": token_stats("approx_answer_tokens"),
    }


def _extractive_method() -> dict:
    return {
        "answer": "extractive sentence copy from authorized hit snippets",
        "fact_coverage": "lexical: every number must appear and at least 60% of content words longer than 3 characters",
        "nonverbatim_sentence_rate": "substring check only; copied evidence is not necessarily true and zero is not zero hallucinations",
        "abstention": "requires an explicit is_answerable label; never inferred from empty reference IDs",
        "reference_precision": "gold overlap among returned documents; non-gold documents are not proven irrelevant",
        "tokens": "ceil(characters/4); not tokenizer counts",
        "llm_api_calls": 0,
        "llm_usd": None,
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
            "vector_configuration": json.loads((directory / "status.json").read_text())
                                    if (directory / "status.json").exists() else None,
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
                   questions_path: Path | None = None, threads: int = 1,
                   retrieval_depth: int = 20, report_path: Path | None = None) -> dict:
    if not modes or any(mode not in MODES for mode in modes):
        raise ValueError("select keyword, vector and/or hybrid")
    if not cutoffs or min(cutoffs) < 1 or not 1 <= retrieval_depth <= 80 or max(cutoffs) > retrieval_depth:
        raise ValueError("top-k must be between 1 and retrieval-depth (at most 80)")
    if repeats < 1 or threads < 1 or ann_queries < 0 or (limit is not None and limit < 1):
        raise ValueError("repeats, threads and limit must be positive; ann-queries must be nonnegative")
    out_dir = out_dir.resolve()
    report_path = (report_path or out_dir / "evaluation.json").resolve()
    if report_path.suffix != ".json" or report_path.is_relative_to(out_dir / "vectors"):
        raise ValueError("report must be a JSON file outside the vector artifacts")
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
                                       seed=seed, limit=limit, retrieval_depth=retrieval_depth)
    finally:
        connection.close()
    ann = evaluate_ann(out_dir, questions, samples=ann_queries, seed=seed)
    from contextledger.eval_scenarios import evaluate_scenarios

    scenarios = evaluate_scenarios(modes=tuple(dict.fromkeys(modes)))
    ingest = measure_ingest()
    report = {
        "schema_version": 2, "created_at": datetime.now(timezone.utc).isoformat(),
        "evaluation_scope": {
            "kind": "regression",
            "retrieval_entrypoint": "contextledger.search.search",
            "reranker": None, "answer_provider": None,
            "serving_pipeline_verified": False,
            "independent_final_test": "not_measured",
            "reason": "The public benchmark has already been inspected and used for tuning. A new seed or split of the same questions does not establish an independent final test.",
        },
        "final_assessment": {
            "status": "not_measured",
            "required_evidence": [
                "Freeze the model, chunking, index, candidate, reranking and prompt configuration before testing unseen questions.",
                "Run the deployed answering pipeline and grade generated answers, facts and citation support against fixed references or independent adjudication.",
                "Measure request-to-response latency, actual API token usage/cost, source-update visibility and authorization/revocation/audit across that pipeline.",
            ],
            "fixture_gates": scenarios["gates"],
            "note": "Successful execution and passed synthetic fixtures are not final system acceptance or a hackathon score.",
        },
        "configuration": {"seed": seed, "modes": list(dict.fromkeys(modes)), "top_k": sorted(set(cutoffs)),
                          "repeats": repeats, "limit": limit, "threads": threads,
                          "concurrency": 1, "ann_queries": ann_queries,
                          "retrieval_depth": retrieval_depth,
                          "vector_chunk_candidates": 80,
                          "keyword_candidate_window": max(retrieval_depth * 10, 50),
                          "warmup": "Model and native indexes warmed; queries measured once per repeat; OS cache is not controlled."},
        "environment": environment(),
        "datasets": provenance, "resources": resource_stats, "warmup_seconds": warmup_seconds,
        "retrieval": retrieval, "ann": ann, "scenarios": scenarios, "ingest_fixture": ingest,
        "not_measured": {
            "generated_answer_quality": "No answering model runs. Lexical overlap and a zero nonverbatim copy rate do not measure answer correctness, semantic fact coverage, citation support or hallucination rate.",
            "independent_final_test": "Questions already used for tuning are regression data; no unseen frozen-configuration final test is run.",
            "deployed_pipeline_and_end_to_end_latency": "This runs in-process Part A retrieval without the offline BGE/Qwen refinement, HTTP/login, generation or integrated audit. It does not reproduce the saved refinement score or verify deployment.",
            "llm_judge_api_usd_and_ttft": "Answers are extractive copies. No LLM judge and no paid API were called. llm_usd is null. There is no token stream, so TTFT is not measured.",
            "full_corpus_ingest_and_embedding_throughput": "A temporary paragraph-chunk fixture reports ingest throughput. The full corpus and embedding throughput are not measured, and this run does not rebuild the live store.",
            "live_source_update_visibility": "Requires source-update notifications and a serving sync pipeline; historical as-of filtering is tested separately.",
            "vector_insert_delete_concurrency": "Current pinned RaBitQ binding has no add/remove API; no streaming claim is made.",
            "source_native_acl_fidelity": "Synthetic effective ACL fixtures test enforcement, not complete connector-native policy semantics.",
            "login_session_and_admin_ui": "Part A currently uses principal IDs; login/admin integration requires separate end-to-end testing.",
            "browser_session_cache": "The fixture identity switch builds the next prompt only from that principal's hits. Browser and session caches are not measured.",
        },
        "references": ["https://github.com/onyx-dot-app/EnterpriseRAG-Bench",
                       "https://huggingface.co/datasets/aeriesec/orgforge",
                       "https://github.com/CGCL-codes/CANDOR-Bench"],
        "seconds": time.perf_counter() - started,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
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
          f"extractive prompt/answer fixture: {scenarios['gates']['extractive_prompt_and_answer_leak']}; "
          f"pre-retrieval candidate isolation: {scenarios['gates']['pre_retrieval_candidate_isolation']}", flush=True)
    print("Scope: retrieval regression; final system assessment is not measured.", flush=True)
    return report
