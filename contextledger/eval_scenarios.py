"""Declared ACL/time fixtures on the real search path; temporary stores only."""

from __future__ import annotations

import json
from contextlib import ExitStack, closing
from pathlib import Path
import tempfile
import time
from unittest.mock import patch

from contextledger.models import CanonicalDoc, Chunk, Principal
from contextledger.search import open_document, search
from contextledger.store import connect, content_hash, init_db, insert_documents, insert_principals

SOURCES = ("slack", "jira", "confluence", "google_drive")


def _fixture(out_dir: Path) -> None:
    with closing(connect(out_dir / "canonical.sqlite")) as connection, connection:
        init_db(connection)
        principals, documents, chunks = [], [], []
        for corpus in ("eval_alpha", "eval_beta"):
            for name in ("alice", "bob", "joined", "departed"):
                principals.append(Principal(corpus, f"{corpus}:{name}", name, "fixture", "fixture",
                                            30 if name == "joined" else 0,
                                            20 if name == "departed" else None))
            for source in SOURCES:
                for category in ("public", "private", "future"):
                    doc_id = f"{source}-{category}"
                    text = f"{corpus} {source} {category} budget release evidence. Canary {corpus}_{doc_id}."
                    digest = content_hash(text)
                    allowed = [f"{corpus}:alice"] if category == "private" else [
                        f"{corpus}:{name}" for name in ("alice", "bob", "joined", "departed")]
                    chunk_id = f"{corpus}/{doc_id}/0"
                    chunks.append(Chunk(chunk_id, corpus, doc_id, 0, text))
                    documents.append(CanonicalDoc(corpus, doc_id, source, doc_id, text,
                                                  50 if category == "future" else 1, None, "fixture", [],
                                                  allowed, "declared_fixture", digest[:12], digest, {}, [chunk_id]))
        insert_principals(connection, principals, {})
        insert_documents(connection, documents, chunks)
        connection.commit()


def evaluate_scenarios(*, modes: tuple[str, ...]) -> dict:
    cases = []
    with tempfile.TemporaryDirectory(prefix="contextledger-eval-") as directory:
        out_dir = Path(directory)
        _fixture(out_dir)
        if any(mode != "keyword" for mode in modes):
            from contextledger.vectors import build_vectors

            build_vectors(out_dir, batch_size=32)
        with closing(connect(out_dir / "canonical.sqlite")) as connection, connection, ExitStack() as traces:
            from contextledger import search as search_module

            candidates = []
            keyword_lookup = search_module._fts_doc_ids

            def keyword_trace(*args, **kwargs):
                found = keyword_lookup(*args, **kwargs)
                candidates.extend(found)
                return found

            traces.enter_context(patch.object(search_module, "_fts_doc_ids", keyword_trace))
            if any(mode != "keyword" for mode in modes):
                from contextledger import vectors

                vector_lookup = vectors.search_chunks

                def vector_trace(*args, **kwargs):
                    found = vector_lookup(*args, **kwargs)
                    candidates.extend(item["doc_id"] for item in found)
                    return found

                traces.enter_context(patch.object(vectors, "search_chunks", vector_trace))

                def clear_fixture_indexes():
                    with vectors._LOCK:
                        for corpus in ("eval_alpha", "eval_beta"):
                            vectors._STORES.pop((str(out_dir.resolve()), corpus), None)

                traces.callback(clear_fixture_indexes)

            def probe(name, source, category, user, day, allowed, *, corpus="eval_alpha"):
                doc_id = f"{source}-{category}"
                for mode in modes:
                    candidates.clear()
                    result = search(connection, corpus=corpus, query=f"{source} {category} budget release evidence",
                                    principal_id=user, as_of_day=day, mode=mode, limit=32)
                    if result.get("error"):
                        raise RuntimeError(result["error"])
                    found = doc_id in {hit["doc_id"] for hit in result["hits"]}
                    opened = open_document(connection, corpus=corpus, doc_id=doc_id,
                                           principal_id=user, as_of_day=day) is not None
                    cases.append({"case": name, "source": source, "mode": mode,
                                  "expected_access": allowed, "retrieved_target": found,
                                  "opened_target": opened, "candidate_target": doc_id in candidates,
                                  "passed": found == allowed and opened == allowed})

            for source in SOURCES:
                probe("authorised", source, "private", "eval_alpha:alice", 60, True)
                probe("unauthorised", source, "private", "eval_alpha:bob", 60, False)
                probe("public_positive_control", source, "public", "eval_alpha:bob", 60, True)
                probe("future_excluded", source, "future", "eval_alpha:alice", 49, False)
                probe("future_boundary_visible", source, "future", "eval_alpha:alice", 50, True)
            probe("unknown_user", "jira", "private", "eval_alpha:unknown", 60, False)
            probe("cross_corpus_identity", "jira", "private", "eval_beta:alice", 60, False)
            probe("before_joining", "slack", "public", "eval_alpha:joined", 29, False)
            probe("joining_boundary", "slack", "public", "eval_alpha:joined", 30, True)
            probe("departure_boundary", "slack", "public", "eval_alpha:departed", 20, True)
            probe("after_departure", "slack", "public", "eval_alpha:departed", 21, False)
            probe("before_revocation", "jira", "private", "eval_alpha:alice", 60, True)
            started = time.perf_counter()
            connection.execute("UPDATE documents SET acl_json='[]' WHERE corpus='eval_alpha' AND doc_id='jira-private'")
            connection.commit()
            probe("revoked_next_request", "jira", "private", "eval_alpha:alice", 60, False)
            revocation_probe_ms = (time.perf_counter() - started) * 1000
            connection.execute("UPDATE documents SET acl_json=? WHERE corpus='eval_alpha' AND doc_id='jira-private'",
                               (json.dumps(["eval_alpha:alice", "eval_alpha:bob"]),))
            connection.commit()
            probe("permission_restored", "jira", "private", "eval_alpha:alice", 60, True)
            probe("newly_granted", "jira", "private", "eval_alpha:bob", 60, True)
            connection.execute("UPDATE documents SET acl_json=? WHERE corpus='eval_alpha' AND doc_id='jira-private'",
                               (json.dumps(["eval_alpha:alice"]),))
            connection.commit()
            probe("switch_to_revoked_user", "jira", "private", "eval_alpha:bob", 60, False)
            probe("switch_back_to_allowed_user", "jira", "private", "eval_alpha:alice", 60, True)
            probe("other_corpus_unaffected", "jira", "private", "eval_beta:alice", 60, True, corpus="eval_beta")
    negative = [case for case in cases if not case["expected_access"]]
    positive = [case for case in cases if case["expected_access"]]
    leaks = sum(case["retrieved_target"] or case["opened_target"] for case in negative)
    denied = sum(not case["retrieved_target"] or not case["opened_target"] for case in positive)
    future = [case for case in cases if case["case"] == "future_excluded"]
    candidate_violations = sum(case["candidate_target"] for case in negative)
    return {
        "scope": "Synthetic effective ACLs/time boundaries on real Part A search/open paths; not native source-policy or browser/session validation.",
        "passed": sum(case["passed"] for case in cases), "total": len(cases),
        "negative_cases": len(negative), "positive_cases": len(positive),
        "unauthorised_target_leak_cases": leaks,
        "unauthorised_target_leak_rate": leaks / len(negative),
        "false_denial_cases": denied, "false_denial_rate": denied / len(positive),
        "future_target_leak_cases": sum(case["retrieved_target"] or case["opened_target"] for case in future),
        "future_negative_cases": len(future),
        "denied_target_candidate_cases": candidate_violations,
        "denied_target_candidate_rate": candidate_violations / len(negative),
        "revocation_write_and_all_mode_probes_ms": revocation_probe_ms,
        "cases": cases,
        "gates": {
            "returned_evidence_and_open_access": "passed" if not leaks and not denied else "failed",
            "pre_retrieval_candidate_isolation": "not_met: denied targets observed before ACL/time filtering" if candidate_violations else "passed",
        },
        "mvp_audit": evaluate_audit(),
    }


def evaluate_audit() -> dict:
    from src.audit import AuditService
    from src.data import load_documents, load_users
    from src.service import KnowledgeService

    cases = []
    with tempfile.TemporaryDirectory(prefix="contextledger-audit-eval-") as directory:
        root = Path(directory)
        service = KnowledgeService(load_documents(), root / "service.jsonl", users=load_users())
        service.answerer.provider = "mock"
        result = service.ask("alice", "What was the incident root cause?")
        records = service.query_audit("carol", user_id="alice", request_id=result.request_id)
        required = {"request_id", "timestamp", "user_id", "question", "retrieved_document_ids",
                    "final_answer", "authorization_decisions"}
        complete = len(records) == 1 and required.issubset(records[0])
        complete = complete and len(records[0]["authorization_decisions"]) == len(load_documents())
        cases.append({"case": "complete_queryable_record", "passed": complete})
        timestamp = records[0]["timestamp"] if records else "2026-01-01T00:00:00+00:00"
        selected = service.query_audit("carol", user_id="alice", start=timestamp, end=timestamp)
        cases.append({"case": "user_time_query", "passed": [row["request_id"] for row in selected] == [result.request_id]})
        try:
            service.query_audit("bob", user_id="alice")
            denied = False
        except PermissionError:
            denied = True
        cases.append({"case": "unauthorised_audit_query", "passed": denied})
        cases.append({"case": "valid_audit_chain", "passed": service.audit_integrity().valid})
        for mutation in ("modify", "delete_tail", "reorder"):
            path = root / f"{mutation}.jsonl"
            audit = AuditService(path)
            audit.append({"request_id": "one", "timestamp": timestamp, "user_id": "alice", "final_answer": "first"})
            audit.append({"request_id": "two", "timestamp": timestamp, "user_id": "alice", "final_answer": "second"})
            lines = path.read_text().splitlines()
            if mutation == "modify":
                row = json.loads(lines[0])
                row["final_answer"] = "tampered"
                lines[0] = json.dumps(row)
            elif mutation == "delete_tail":
                lines = lines[:-1]
            else:
                lines.reverse()
            path.write_text("\n".join(lines) + "\n")
            cases.append({"case": f"detect_{mutation}", "passed": not audit.verify().valid})
    return {"scope": "Separate src/ MVP fixture service, mock answers; not integrated Part A audit coverage or externally anchored tamper resistance.",
            "passed": sum(case["passed"] for case in cases), "total": len(cases), "cases": cases}
