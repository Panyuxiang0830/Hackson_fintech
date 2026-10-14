"""Build Part A: raw files, canonical documents, ACL, chunks, and FTS."""

from __future__ import annotations

import json
import shutil
from collections import Counter
from pathlib import Path

from contextledger.acl import (
    ERAG_ROLE_SOURCES,
    assign_enterpriserag_acl,
    assign_orgforge_acl,
    can_see,
    enterpriserag_principals,
    orgforge_principals,
    role_sources_from_questions,
)
from contextledger.connectors import (
    ERAG_REPO,
    ORG_REPO,
    hub_file,
    iter_enterpriserag,
    iter_orgforge,
    load_orgforge_questions,
    load_orgforge_snapshot,
)
from contextledger.models import CanonicalDoc, Chunk, SourceDoc
from contextledger.processors import chunk_document
from contextledger.search import search_fts, search_hybrid, search_vector
from contextledger.store import (
    connect,
    content_hash,
    init_db,
    insert_documents,
    insert_principals,
    load_principal,
    write_raw_jsonl,
)


def _dedupe(docs: list[SourceDoc]) -> tuple[list[SourceDoc], int]:
    seen: set[tuple[str, str]] = set()
    kept: list[SourceDoc] = []
    dropped = 0
    for doc in docs:
        key = (doc.corpus, doc.doc_id)
        if key in seen:
            dropped += 1
            continue
        seen.add(key)
        kept.append(doc)
    return kept, dropped


def _reset_output(out_dir: Path) -> None:
    import os
    from contextledger.unified_service import validate_security_path

    validate_security_path(out_dir, Path(os.getenv("SECURITY_DIR", "runtime/security")))
    # A misplaced state directory is protected even if SECURITY_DIR was changed.
    if out_dir.exists() and (list(out_dir.rglob("identities.sqlite")) or list(out_dir.rglob("audit.sqlite"))):
        raise ValueError("Refusing to rebuild a directory containing identity/audit state")
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)


def _canonical(doc: SourceDoc, acl: list[str], basis: str, chunks: list[Chunk]) -> CanonicalDoc:
    digest = content_hash(doc.text)
    return CanonicalDoc(
        corpus=doc.corpus,
        doc_id=doc.doc_id,
        source=doc.source,
        title=doc.title,
        text=doc.text,
        day=doc.day,
        ts=doc.ts,
        dept=doc.dept,
        actors=doc.actors,
        acl=acl,
        acl_basis=basis,
        version=digest[:12],
        content_hash=digest,
        extra=doc.extra,
        chunks=[chunk.chunk_id for chunk in chunks],
    )


def build(
    out_dir: Path,
    *,
    limit: int | None = None,
    erag_slack_limit: int | None = 3000,
) -> dict:
    """Ingest both corpora and write runtime/part_a.

    erag_slack_limit samples Slack evenly. Pass None to keep all 285,605 threads.
    limit caps every source, for a smoke run.
    """
    print("resolving dataset files", flush=True)
    org_parquet = hub_file(ORG_REPO, "corpus/corpus-00000.parquet")
    org_questions_path = hub_file(ORG_REPO, "questions/eval_questions.jsonl")
    org_snapshot_path = hub_file(ORG_REPO, "supplemental/simulation_snapshot.json")
    erag_parquet = hub_file(ERAG_REPO, "data/documents/test.parquet")

    print("reading OrgForge artifacts", flush=True)
    org_docs = iter_orgforge(org_parquet, limit=limit)
    print(f"  orgforge docs {len(org_docs)}", flush=True)
    print("reading EnterpriseRAG sources", flush=True)
    erag_docs = iter_enterpriserag(erag_parquet, slack_limit=erag_slack_limit, limit=limit)
    print(f"  enterpriserag docs {len(erag_docs)}", flush=True)
    docs, dropped = _dedupe(org_docs + erag_docs)
    if dropped:
        print(f"  dropped {dropped} duplicate corpus/doc_id rows", flush=True)

    questions = load_orgforge_questions(org_questions_path)
    snapshot = load_orgforge_snapshot(org_snapshot_path)
    org_role_sources = role_sources_from_questions(questions)
    principals = orgforge_principals(org_docs, snapshot) + enterpriserag_principals()

    print("assigning ACLs and chunking", flush=True)
    canonical: list[CanonicalDoc] = []
    chunks: list[Chunk] = []
    basis_counts: Counter = Counter()
    for index, doc in enumerate(docs):
        if not (doc.text or "").strip():
            doc.text = doc.title or doc.doc_id
        if doc.corpus == "orgforge":
            acl, basis = assign_orgforge_acl(doc, principals, org_role_sources)
        else:
            acl, basis = assign_enterpriserag_acl(doc, principals)
        doc_chunks = chunk_document(doc)
        basis_counts[f"{doc.corpus}:{basis}"] += 1
        canonical.append(_canonical(doc, acl, basis, doc_chunks))
        chunks.extend(doc_chunks)
        if index and index % 10000 == 0:
            print(f"  prepared {index}", flush=True)

    print("writing raw store, canonical store, and FTS", flush=True)
    _reset_output(out_dir)
    raw_dir = out_dir / "raw"
    for corpus in ("orgforge", "enterpriserag"):
        for source in sorted({doc.source for doc in docs if doc.corpus == corpus}):
            records = []
            for doc in docs:
                if doc.corpus == corpus and doc.source == source:
                    payload = dict(doc.raw)
                    payload["sha256"] = content_hash(json.dumps(doc.raw, ensure_ascii=False, sort_keys=True, default=str))
                    records.append(payload)
            write_raw_jsonl(raw_dir / corpus / f"{source}.jsonl", records)

    db_path = out_dir / "canonical.sqlite"
    connection = connect(db_path)
    init_db(connection)
    role_sources = {"orgforge": org_role_sources, "enterpriserag": ERAG_ROLE_SOURCES}
    with connection:
        insert_principals(connection, principals, role_sources)
        insert_documents(connection, canonical, chunks)

    by_source = Counter((doc.corpus, doc.source) for doc in canonical)
    manifest = {
        "part": "A",
        "db": str(db_path),
        "documents": len(canonical),
        "chunks": len(chunks),
        "principals": len(principals),
        "by_source": {f"{corpus}/{source}": count for (corpus, source), count in sorted(by_source.items())},
        "acl_basis": dict(basis_counts),
        "erag_slack_limit": erag_slack_limit,
        "per_source_limit": limit,
        "duplicate_rows_dropped": dropped,
        "notes": [
            "OrgForge is Apex Athletics. EnterpriseRAG is Redwood Inference. They stay in separate corpus ids.",
            "EnterpriseRAG parquet has no channel, author, or timestamp. ACL there is source-level.",
            "OrgForge Slack ACL follows channel names. DMs stay on the named people.",
            "Time and employment are applied at query time, not baked into the ACL list.",
        ],
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    connection.close()
    print(json.dumps(manifest["by_source"], indent=2), flush=True)
    print(f"chunks {len(chunks)} principals {len(principals)}", flush=True)
    return manifest


def check(out_dir: Path) -> dict:
    """Run the ACL, freshness, keyword, and vector checks Part A has to satisfy."""
    connection = connect(out_dir / "canonical.sqlite")
    report: dict = {"ok": True, "checks": []}

    def record(name: str, passed: bool, detail: str) -> None:
        report["checks"].append({"name": name, "ok": passed, "detail": detail})
        if not passed:
            report["ok"] = False
        print(f"[{'ok' if passed else 'FAIL'}] {name}: {detail}", flush=True)

    counts = connection.execute(
        "SELECT corpus, source, COUNT(*) AS n FROM documents GROUP BY corpus, source ORDER BY corpus, source"
    ).fetchall()
    record("sources", len(counts) >= 6, ", ".join(f"{row['corpus']}/{row['source']}={row['n']}" for row in counts))

    employed = "(active_until IS NULL OR active_until >= 60) AND (active_from IS NULL OR active_from <= 0)"
    sales = connection.execute(
        f"SELECT principal_id FROM principals WHERE corpus = 'orgforge' AND role = 'sales_marketing' AND {employed} LIMIT 1"
    ).fetchone()
    backend = connection.execute(
        f"SELECT principal_id FROM principals WHERE corpus = 'orgforge' AND role = 'engineering_backend' AND {employed} LIMIT 1"
    ).fetchone()
    jira = connection.execute(
        """
        SELECT doc_id, title, acl_json, day FROM documents
        WHERE corpus = 'orgforge' AND source = 'jira' AND dept = 'Engineering_Backend'
        LIMIT 1
        """
    ).fetchone()
    if sales and backend and jira:
        acl = json.loads(jira["acl_json"])
        record(
            "jira hides sales",
            sales["principal_id"] not in acl and backend["principal_id"] in acl,
            f"{jira['doc_id']} sales={sales['principal_id'] in acl} backend={backend['principal_id'] in acl}",
        )
    else:
        record("jira hides sales", False, "missing sales principal, backend principal, or jira doc")

    dm_rows = connection.execute(
        """
        SELECT doc_id, title, acl_json FROM documents
        WHERE corpus = 'orgforge' AND acl_basis = 'slack_dm'
        LIMIT 30
        """
    ).fetchall()
    outsider = connection.execute(
        "SELECT principal_id FROM principals WHERE corpus = 'orgforge' AND role = 'hr_ops' LIMIT 1"
    ).fetchone()
    private_dm = None
    if outsider:
        for candidate in dm_rows:
            acl = json.loads(candidate["acl_json"])
            if acl and outsider["principal_id"] not in acl:
                private_dm = (candidate, acl)
                break
    if private_dm:
        candidate, acl = private_dm
        record(
            "dm stays private",
            True,
            f"{candidate['title']} acl={len(acl)} excludes {outsider['principal_id']}",
        )
    else:
        record("dm stays private", False, "no DM whose ACL excludes the HR principal")

    jordan = load_principal(connection, "orgforge:Jordan")
    future = connection.execute(
        """
        SELECT doc_id, day, acl_json FROM documents
        WHERE corpus = 'orgforge' AND source = 'slack' AND day >= 40
          AND acl_json LIKE '%orgforge:Jordan%'
        LIMIT 1
        """
    ).fetchone()
    if jordan and jordan.active_until is not None:
        if future:
            visible_later = can_see(jordan, json.loads(future["acl_json"]), future["day"], as_of_day=20)
            record(
                "departure cuts visibility",
                visible_later is False and jordan.active_until == 11,
                f"Jordan active_until={jordan.active_until} sees day {future['day']} at as_of 20: {visible_later}",
            )
        else:
            record(
                "departure cuts visibility",
                jordan.active_until == 11,
                f"Jordan active_until={jordan.active_until}; no later slack lists Jordan, employment gate still recorded",
            )
    else:
        record("departure cuts visibility", False, "Jordan missing from roster")

    mkt = connection.execute(
        """
        SELECT doc_id, acl_json FROM documents
        WHERE corpus = 'orgforge' AND source = 'confluence' AND doc_id LIKE 'CONF-MKT-%'
        LIMIT 1
        """
    ).fetchone()
    if mkt and backend:
        acl = json.loads(mkt["acl_json"])
        record(
            "marketing confluence",
            backend["principal_id"] not in acl,
            f"{mkt['doc_id']} backend_in={backend['principal_id'] in acl}",
        )
    else:
        record("marketing confluence", False, "missing CONF-MKT or backend principal")

    hits = search_fts(
        connection,
        corpus="orgforge",
        query="TitanDB",
        principal_id=backend["principal_id"] if backend else "",
        as_of_day=60,
        limit=5,
    )["hits"]
    record("fts TitanDB", len(hits) > 0, ", ".join(hit["doc_id"] for hit in hits[:5]) or "no hits")

    hidden = search_fts(
        connection,
        corpus="orgforge",
        query="TitanDB",
        principal_id=sales["principal_id"] if sales else "",
        as_of_day=60,
        limit=8,
    )["hits"]
    jira_leaked = [hit["doc_id"] for hit in hidden if hit["source"] == "jira"]
    record("sales search skips jira", len(jira_leaked) == 0, f"jira hits in sales results: {jira_leaked[:5]}")

    early = search_fts(
        connection,
        corpus="orgforge",
        query="incident",
        principal_id=backend["principal_id"] if backend else "",
        as_of_day=3,
        limit=8,
    )["hits"]
    late_days = [hit["day"] for hit in early if hit["day"] is not None and hit["day"] > 3]
    record("as_of drops future docs", len(late_days) == 0, f"future days returned: {late_days}")

    contractor = search_fts(
        connection,
        corpus="enterpriserag",
        query="runbook",
        principal_id="enterpriserag:contractor",
        limit=8,
    )["hits"]
    contractor_sources = sorted({hit["source"] for hit in contractor})
    record(
        "contractor misses jira and confluence",
        "jira" not in contractor_sources and "confluence" not in contractor_sources,
        f"sources={contractor_sources or 'no hits'}",
    )

    _vector_checks(connection, record, backend, sales)
    from contextledger.supplemental import check_supplemental

    check_supplemental(connection, record)
    connection.close()
    (out_dir / "check-report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def _vector_checks(connection, record, backend, sales) -> None:
    """ACL still applies when the candidates come from the vector index."""
    wearable = "database storing athlete wearable telemetry"
    power = "backup power pack for the field radios"
    jax = search_vector(
        connection,
        corpus="orgforge",
        query=wearable,
        principal_id="orgforge:Jax",
        as_of_day=60,
        limit=8,
    )
    if jax.get("error"):
        record("vector index", False, jax["error"])
        return
    record("vector index", True, "loaded")
    record(
        "vector wearable store",
        any(hit["source"] == "confluence" for hit in jax["hits"]),
        ", ".join(f"{hit['source']}:{hit['doc_id']}" for hit in jax["hits"][:5]) or "no hits",
    )
    vince = search_vector(
        connection,
        corpus="orgforge",
        query=wearable,
        principal_id=sales["principal_id"] if sales else "",
        as_of_day=60,
        limit=8,
    )
    leaked = [hit["doc_id"] for hit in vince["hits"] if hit["source"] in {"confluence", "jira"}]
    record(
        "vector sales skips confluence and jira",
        len(leaked) == 0,
        f"leaked={leaked[:5]} sources={sorted({hit['source'] for hit in vince['hits']}) or 'none'}",
    )
    liam = search_vector(
        connection,
        corpus="orgforge",
        query=power,
        principal_id="orgforge:Liam",
        as_of_day=60,
        limit=8,
    )
    record(
        "vector finds the dm",
        any(hit["doc_id"].startswith("slack_dm_liam_morgan") for hit in liam["hits"]),
        ", ".join(hit["doc_id"] for hit in liam["hits"][:5]) or "no hits",
    )
    dave = search_vector(
        connection,
        corpus="orgforge",
        query=power,
        principal_id="orgforge:Dave",
        as_of_day=60,
        limit=8,
    )
    dave_leaked = [hit["doc_id"] for hit in dave["hits"] if hit["doc_id"].startswith("slack_dm_liam_morgan")]
    record("vector hr misses that dm", len(dave_leaked) == 0, f"leaked={dave_leaked}")
    left = search_hybrid(
        connection,
        corpus="orgforge",
        query="incident",
        principal_id="orgforge:Jordan",
        as_of_day=40,
        limit=8,
    )
    record(
        "vector departure",
        len(left["hits"]) == 0 and left.get("withheld", 0) > 0,
        f"hits={len(left['hits'])} withheld={left.get('withheld', 0)}",
    )
    early = search_vector(
        connection,
        corpus="orgforge",
        query="incident",
        principal_id=backend["principal_id"] if backend else "",
        as_of_day=3,
        limit=8,
    )
    late_days = [hit["day"] for hit in early["hits"] if hit["day"] is not None and hit["day"] > 3]
    record("vector as_of drops future docs", len(late_days) == 0, f"future days: {late_days}")
    hybrid = search_hybrid(
        connection,
        corpus="orgforge",
        query="TitanDB",
        principal_id="orgforge:Jax",
        as_of_day=60,
        limit=5,
    )
    record(
        "hybrid TitanDB",
        any(hit["source"] == "confluence" for hit in hybrid["hits"]),
        ", ".join(hit["doc_id"] for hit in hybrid["hits"][:5]) or "no hits",
    )
    sales_hybrid = search_hybrid(
        connection,
        corpus="orgforge",
        query="TitanDB",
        principal_id="orgforge:Vince",
        as_of_day=60,
        limit=8,
    )
    wiki = {"CONF-ENG-001", "CONF-ENG-002", "CONF-ENG-003", "CONF-QA-003"}
    sales_leaked = [
        hit["doc_id"]
        for hit in sales_hybrid["hits"]
        if hit["source"] == "jira" or hit["doc_id"] in wiki
    ]
    record(
        "hybrid sales misses the wiki",
        len(sales_leaked) == 0
        and sales_hybrid["withheld"] > 0
        and any(hit["source"] == "slack" for hit in sales_hybrid["hits"]),
        f"leaked={sales_leaked[:5]} withheld={sales_hybrid['withheld']} "
        + ", ".join(hit["doc_id"] for hit in sales_hybrid["hits"][:5]),
    )
    engineer = search_vector(
        connection,
        corpus="enterpriserag",
        query="runbook",
        principal_id="enterpriserag:engineer",
        limit=8,
    )
    contractor_vec = search_vector(
        connection,
        corpus="enterpriserag",
        query="runbook",
        principal_id="enterpriserag:contractor",
        limit=8,
    )
    forbidden = [hit["doc_id"] for hit in contractor_vec["hits"] if hit["source"] in {"jira", "confluence"}]
    record(
        "vector contractor",
        len(engineer["hits"]) > 0 and len(forbidden) == 0,
        f"engineer={len(engineer['hits'])} contractor_sources={sorted({hit['source'] for hit in contractor_vec['hits']}) or 'none'} leaked={forbidden[:5]}",
    )
