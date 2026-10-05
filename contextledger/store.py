"""SQLite canonical store, raw JSONL, and the FTS index."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from contextledger.models import CanonicalDoc, Chunk, Principal

SCHEMA = """
CREATE TABLE principals (
    principal_id TEXT PRIMARY KEY,
    corpus TEXT NOT NULL,
    name TEXT NOT NULL,
    role TEXT NOT NULL,
    dept TEXT NOT NULL,
    active_from INTEGER,
    active_until INTEGER
);

CREATE TABLE role_source (
    corpus TEXT NOT NULL,
    role TEXT NOT NULL,
    source TEXT NOT NULL,
    PRIMARY KEY (corpus, role, source)
);

CREATE TABLE documents (
    corpus TEXT NOT NULL,
    doc_id TEXT NOT NULL,
    source TEXT NOT NULL,
    title TEXT NOT NULL,
    text TEXT NOT NULL,
    day INTEGER,
    ts TEXT,
    dept TEXT NOT NULL,
    actors_json TEXT NOT NULL,
    acl_json TEXT NOT NULL,
    acl_basis TEXT NOT NULL,
    version TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    extra_json TEXT NOT NULL,
    PRIMARY KEY (corpus, doc_id)
);

CREATE INDEX documents_source ON documents (corpus, source);
CREATE INDEX documents_day ON documents (corpus, day);

CREATE TABLE chunks (
    chunk_id TEXT PRIMARY KEY,
    corpus TEXT NOT NULL,
    doc_id TEXT NOT NULL,
    ordinal INTEGER NOT NULL,
    text TEXT NOT NULL
);

CREATE INDEX chunks_doc ON chunks (corpus, doc_id);

CREATE VIRTUAL TABLE docs_fts USING fts5(
    doc_id UNINDEXED,
    corpus UNINDEXED,
    source UNINDEXED,
    title,
    text
);
"""


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    return connection


def init_db(connection: sqlite3.Connection) -> None:
    connection.executescript(SCHEMA)
    connection.commit()


def write_raw_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def insert_principals(
    connection: sqlite3.Connection,
    principals: list[Principal],
    role_sources: dict[str, dict[str, set[str]]],
) -> None:
    connection.executemany(
        """
        INSERT INTO principals (principal_id, corpus, name, role, dept, active_from, active_until)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                principal.principal_id,
                principal.corpus,
                principal.name,
                principal.role,
                principal.dept,
                principal.active_from,
                principal.active_until,
            )
            for principal in principals
        ],
    )
    rows = []
    for corpus, mapping in role_sources.items():
        for role, sources in mapping.items():
            for source in sorted(sources):
                rows.append((corpus, role, source))
    connection.executemany("INSERT INTO role_source (corpus, role, source) VALUES (?, ?, ?)", rows)


def insert_documents(
    connection: sqlite3.Connection,
    documents: list[CanonicalDoc],
    chunks: list[Chunk],
) -> None:
    connection.executemany(
        """
        INSERT INTO documents (
            corpus, doc_id, source, title, text, day, ts, dept,
            actors_json, acl_json, acl_basis, version, content_hash, extra_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                doc.corpus,
                doc.doc_id,
                doc.source,
                doc.title,
                doc.text,
                doc.day,
                doc.ts,
                doc.dept,
                json.dumps(doc.actors, ensure_ascii=False),
                json.dumps(doc.acl, ensure_ascii=False),
                doc.acl_basis,
                doc.version,
                doc.content_hash,
                json.dumps(doc.extra, ensure_ascii=False),
            )
            for doc in documents
        ],
    )
    connection.executemany(
        "INSERT INTO docs_fts (doc_id, corpus, source, title, text) VALUES (?, ?, ?, ?, ?)",
        [(doc.doc_id, doc.corpus, doc.source, doc.title, doc.text) for doc in documents],
    )
    connection.executemany(
        "INSERT INTO chunks (chunk_id, corpus, doc_id, ordinal, text) VALUES (?, ?, ?, ?, ?)",
        [(chunk.chunk_id, chunk.corpus, chunk.doc_id, chunk.ordinal, chunk.text) for chunk in chunks],
    )


def load_principal(connection: sqlite3.Connection, principal_id: str) -> Principal | None:
    row = connection.execute(
        "SELECT * FROM principals WHERE principal_id = ?",
        (principal_id,),
    ).fetchone()
    if row is None:
        return None
    return Principal(
        corpus=row["corpus"],
        principal_id=row["principal_id"],
        name=row["name"],
        role=row["role"],
        dept=row["dept"],
        active_from=row["active_from"],
        active_until=row["active_until"],
    )
