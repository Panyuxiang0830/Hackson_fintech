"""Search over the Part A indexes, with the ACL applied after lookup.

Keyword search uses FTS5. Vector search uses the per-company RaBitQ IVF
index. Hybrid search fuses the two with reciprocal rank on documents the
principal is already allowed to see. Withheld rows contribute a count only.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from contextledger.acl import can_see
from contextledger.models import Principal
from contextledger.store import load_principal

MODES = ("keyword", "vector", "hybrid")


def search(
    connection: sqlite3.Connection,
    *,
    corpus: str,
    query: str,
    principal_id: str,
    as_of_day: int | None = None,
    limit: int = 8,
    mode: str = "keyword",
) -> dict:
    if mode == "vector":
        return search_vector(
            connection,
            corpus=corpus,
            query=query,
            principal_id=principal_id,
            as_of_day=as_of_day,
            limit=limit,
        )
    if mode == "hybrid":
        return search_hybrid(
            connection,
            corpus=corpus,
            query=query,
            principal_id=principal_id,
            as_of_day=as_of_day,
            limit=limit,
        )
    return search_fts(
        connection,
        corpus=corpus,
        query=query,
        principal_id=principal_id,
        as_of_day=as_of_day,
        limit=limit,
    )


def search_fts(
    connection: sqlite3.Connection,
    *,
    corpus: str,
    query: str,
    principal_id: str,
    as_of_day: int | None = None,
    limit: int = 8,
) -> dict:
    """Return visible hits plus how many candidates the ACL removed."""
    empty = _empty("keyword")
    principal = load_principal(connection, principal_id)
    if principal is None or principal.corpus != corpus:
        return empty
    doc_ids = _fts_doc_ids(connection, corpus, query, max(limit * 10, 50))
    if not doc_ids:
        return empty
    return _finish(
        connection,
        principal,
        query,
        as_of_day,
        doc_ids,
        mode="keyword",
        snippets={},
        limit=limit,
    )


def search_vector(
    connection: sqlite3.Connection,
    *,
    corpus: str,
    query: str,
    principal_id: str,
    as_of_day: int | None = None,
    limit: int = 8,
    k: int = 80,
) -> dict:
    empty = _empty("vector")
    ready, detail = _ready(connection, corpus)
    if not ready:
        empty["error"] = detail
        return empty
    principal = load_principal(connection, principal_id)
    if principal is None or principal.corpus != corpus:
        return empty
    from contextledger.vectors import search_chunks

    found = search_chunks(_out_dir(connection), corpus, query, k=k)
    doc_ids = [item["doc_id"] for item in found]
    snippets = {item["doc_id"]: item["chunk_id"] for item in found}
    return _finish(
        connection,
        principal,
        query,
        as_of_day,
        doc_ids,
        mode="vector",
        snippets=snippets,
        limit=limit,
    )


def search_hybrid(
    connection: sqlite3.Connection,
    *,
    corpus: str,
    query: str,
    principal_id: str,
    as_of_day: int | None = None,
    limit: int = 8,
) -> dict:
    empty = _empty("hybrid")
    ready, detail = _ready(connection, corpus)
    if not ready:
        empty["error"] = detail
        return empty
    principal = load_principal(connection, principal_id)
    if principal is None or principal.corpus != corpus:
        return empty
    from contextledger.vectors import search_chunks

    keyword_ids = _fts_doc_ids(connection, corpus, query, max(limit * 10, 50))
    vector_hits = search_chunks(_out_dir(connection), corpus, query, k=80)
    vector_ids = [item["doc_id"] for item in vector_hits]
    snippets = {item["doc_id"]: item["chunk_id"] for item in vector_hits}
    combined = list(dict.fromkeys([*keyword_ids, *vector_ids]))
    visible, withheld = _partition(connection, principal, combined, as_of_day)
    visible_set = set(visible)
    fused = _rrf(
        [
            [doc_id for doc_id in keyword_ids if doc_id in visible_set],
            [doc_id for doc_id in vector_ids if doc_id in visible_set],
        ]
    )
    hits = _materialize(connection, principal.corpus, fused[:limit], query, snippets)
    return {"hits": hits, "withheld": withheld, "scanned": len(combined), "mode": "hybrid"}


def open_document(
    connection: sqlite3.Connection,
    *,
    corpus: str,
    doc_id: str,
    principal_id: str,
    as_of_day: int | None = None,
) -> dict | None:
    principal = load_principal(connection, principal_id)
    if principal is None or principal.corpus != corpus:
        return None
    doc = connection.execute(
        """
        SELECT doc_id, title, source, day, ts, dept, text, acl_json, acl_basis, extra_json, version
        FROM documents
        WHERE corpus = ? AND doc_id = ?
        """,
        (corpus, doc_id),
    ).fetchone()
    if doc is None:
        return None
    acl = json.loads(doc["acl_json"])
    if not can_see(principal, acl, doc["day"], as_of_day):
        return None
    return {
        "doc_id": doc["doc_id"],
        "title": doc["title"],
        "source": doc["source"],
        "day": doc["day"],
        "ts": doc["ts"],
        "dept": doc["dept"],
        "acl_basis": doc["acl_basis"],
        "text": doc["text"],
        "metadata": json.loads(doc["extra_json"]),
        "version": doc["version"],
    }


def _empty(mode: str) -> dict:
    return {"hits": [], "withheld": 0, "scanned": 0, "mode": mode}


def _ready(connection: sqlite3.Connection, corpus: str) -> tuple[bool, str]:
    from contextledger.vectors import indexes_ready

    return indexes_ready(_out_dir(connection), corpus)


def _out_dir(connection: sqlite3.Connection) -> Path:
    row = connection.execute("PRAGMA database_list").fetchone()
    path = row[2] if row is not None else ""
    if not path:
        raise RuntimeError("SQLite did not report the database path")
    return Path(path).resolve().parent


def _fts_query(text: str) -> str:
    tokens = []
    current = []
    for char in text:
        if char.isalnum() or char in {"_", "-"}:
            current.append(char)
        elif current:
            token = "".join(current)
            if len(token) >= 2:
                tokens.append('"' + token.replace('"', "") + '"')
            current = []
    if current:
        token = "".join(current)
        if len(token) >= 2:
            tokens.append('"' + token.replace('"', "") + '"')
    return " OR ".join(tokens[:12])


def _fts_doc_ids(connection: sqlite3.Connection, corpus: str, query: str, window: int) -> list[str]:
    match = _fts_query(query)
    if not match:
        return []
    rows = connection.execute(
        """
        SELECT doc_id
        FROM docs_fts
        WHERE docs_fts MATCH ? AND corpus = ?
        ORDER BY bm25(docs_fts)
        LIMIT ?
        """,
        (match, corpus, window),
    ).fetchall()
    return [row["doc_id"] for row in rows]


def _snippet(text: str, query: str, width: int = 240) -> str:
    lowered = text.lower()
    position = -1
    for token in _fts_query(query).replace('"', "").split(" OR "):
        if not token:
            continue
        position = lowered.find(token.lower())
        if position >= 0:
            break
    if position < 0:
        position = 0
    start = max(0, position - 90)
    end = min(len(text), start + width)
    fragment = " ".join(text[start:end].split())
    if start > 0:
        fragment = "…" + fragment
    if end < len(text):
        fragment = fragment + "…"
    return fragment


def _finish(
    connection: sqlite3.Connection,
    principal: Principal,
    query: str,
    as_of_day: int | None,
    doc_ids: list[str],
    *,
    mode: str,
    snippets: dict[str, str],
    limit: int,
) -> dict:
    visible, withheld = _partition(connection, principal, doc_ids, as_of_day)
    hits = _materialize(connection, principal.corpus, visible[:limit], query, snippets)
    return {"hits": hits, "withheld": withheld, "scanned": len(doc_ids), "mode": mode}


def _partition(
    connection: sqlite3.Connection,
    principal: Principal,
    doc_ids: list[str],
    as_of_day: int | None,
) -> tuple[list[str], int]:
    rows = _acl_rows(connection, principal.corpus, doc_ids)
    visible = []
    withheld = 0
    seen = set()
    for doc_id in doc_ids:
        if doc_id in seen:
            continue
        seen.add(doc_id)
        row = rows.get(doc_id)
        if row is None:
            continue
        acl = json.loads(row["acl_json"])
        if not can_see(principal, acl, row["day"], as_of_day):
            withheld += 1
            continue
        visible.append(doc_id)
    return visible, withheld


def _acl_rows(connection: sqlite3.Connection, corpus: str, doc_ids: list[str]) -> dict[str, sqlite3.Row]:
    found = {}
    for start in range(0, len(doc_ids), 200):
        batch = doc_ids[start : start + 200]
        placeholders = ",".join("?" * len(batch))
        rows = connection.execute(
            f"""
            SELECT doc_id, source, day, acl_json, acl_basis
            FROM documents
            WHERE corpus = ? AND doc_id IN ({placeholders})
            """,
            (corpus, *batch),
        ).fetchall()
        for row in rows:
            found[row["doc_id"]] = row
    return found


def _materialize(
    connection: sqlite3.Connection,
    corpus: str,
    doc_ids: list[str],
    query: str,
    snippets: dict[str, str],
) -> list[dict]:
    if not doc_ids:
        return []
    details = {}
    placeholders = ",".join("?" * len(doc_ids))
    for row in connection.execute(
        f"""
        SELECT doc_id, title, source, day, dept, text, acl_basis
        FROM documents
        WHERE corpus = ? AND doc_id IN ({placeholders})
        """,
        (corpus, *doc_ids),
    ):
        details[row["doc_id"]] = row
    chunk_ids = [snippets[doc_id] for doc_id in doc_ids if doc_id in snippets]
    chunk_text = _chunk_texts(connection, chunk_ids)
    hits = []
    for doc_id in doc_ids:
        doc = details.get(doc_id)
        if doc is None:
            continue
        chunk_id = snippets.get(doc_id)
        text = chunk_text.get(chunk_id, "") if chunk_id else (doc["text"] or "")
        if not text:
            text = doc["text"] or ""
        hits.append(
            {
                "doc_id": doc["doc_id"],
                "title": doc["title"],
                "source": doc["source"],
                "day": doc["day"],
                "dept": doc["dept"],
                "acl_basis": doc["acl_basis"],
                "snippet": _snippet(text, query),
            }
        )
    return hits


def _chunk_texts(connection: sqlite3.Connection, chunk_ids: list[str]) -> dict[str, str]:
    if not chunk_ids:
        return {}
    found = {}
    placeholders = ",".join("?" * len(chunk_ids))
    for row in connection.execute(
        f"SELECT chunk_id, text FROM chunks WHERE chunk_id IN ({placeholders})",
        tuple(chunk_ids),
    ):
        found[row["chunk_id"]] = row["text"] or ""
    return found


def _rrf(rankings: list[list[str]], constant: int = 60) -> list[str]:
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, doc_id in enumerate(ranking, start=1):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (constant + rank)
    return [doc_id for doc_id, _score in sorted(scores.items(), key=lambda item: (-item[1], item[0]))]
