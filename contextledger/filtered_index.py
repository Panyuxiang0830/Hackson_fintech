"""Qdrant + FTS with trusted prefilters and a fail-closed snapshot publication gate.

The first integration publishes a whole offline snapshot. Fine-grained incremental
publication, historical versions and live freshness remain separate work.
"""

from __future__ import annotations

import hashlib
import difflib
import json
import re
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from qdrant_client import models as qm

from contextledger.identity_store import Actor, IdentityStore
from contextledger.search import _fts_query, _rrf, _snippet, contains_terms, entity_terms
from contextledger.store import connect

LEVELS = {"public": 0, "internal": 1, "confidential": 2, "restricted": 3}
POLICY_VERSION = "snapshot-acl-and-local-deny-v1"
MODEL = "sentence-transformers/all-MiniLM-L6-v2"


class IndexUnavailable(RuntimeError):
    pass


def now():
    return datetime.now(timezone.utc).isoformat()


def point_id(corpus, doc_id, version, chunk_id):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, json.dumps([corpus, doc_id, version, chunk_id])))


def _name(value):
    if isinstance(value, dict):
        return str(value.get("key") or value.get("id") or value.get("name") or "")
    return str(value or "")


@dataclass(frozen=True)
class Scope:
    actor: Actor
    corpus: str
    principals: tuple[str, ...]
    roles: tuple[str, ...]
    departments: tuple[str, ...]
    denied: dict[str, list[str]]
    day: int | None


class FilteredIndex:
    def __init__(self, db_path: Path, client, identity: IdentityStore, embed=None):
        self.db_path = Path(db_path)
        self.client = client
        self.identity = identity
        self.embed = embed or self._embed
        self.expected_model = MODEL if embed is None else None

    @staticmethod
    def _embed(query):
        from contextledger.vectors import _embed_query
        return _embed_query(query)[0].tolist()

    def scope(self, actor: Actor, corpus: str, day=None) -> Scope:
        if not actor.enabled:
            raise PermissionError("account disabled")
        if day is not None and (type(day) is not int or not 0 <= day <= 60):
            raise ValueError("as_of must be a day between 0 and 60")
        ids, denied = self.identity.scope(actor, corpus)
        valid, roles, departments = [], set(), {actor.department} if actor.department else set()
        with connect(self.db_path) as db:
            for principal_id in ids:
                row = db.execute("SELECT * FROM principals WHERE principal_id=? AND corpus=?",
                                 (principal_id, corpus)).fetchone()
                if row is None:
                    continue
                # Historical queries never restore an ex-employee's access.
                if corpus == "orgforge" and ((row["active_from"] is not None and row["active_from"] > 60)
                        or (row["active_until"] is not None and row["active_until"] < 60)):
                    continue
                valid.append(principal_id)
                roles.add(row["role"])
                departments.add(row["dept"])
        if corpus in denied.get("corpus", []) or "*" in denied.get("corpus", []):
            valid = []
        return Scope(actor, corpus, tuple(valid), tuple(sorted(roles)), tuple(sorted(departments)),
                     denied, day if corpus == "orgforge" else None)

    @staticmethod
    def sql_filter(scope: Scope):
        clauses = ["d.corpus=?", "m.classification<=?"]
        params: list = [scope.corpus, scope.actor.clearance]
        if not scope.principals:
            clauses.append("0")
        else:
            placeholders = ",".join("?" for _ in scope.principals)
            clauses.append(f"EXISTS (SELECT 1 FROM cl_acl a WHERE a.corpus=d.corpus AND a.doc_id=d.doc_id AND a.principal_id IN ({placeholders}))")
            params.extend(scope.principals)
        if scope.day is not None:
            clauses.append("(d.day IS NULL OR d.day<=?)")
            params.append(scope.day)
        for field, values in (("roles_json", scope.roles), ("departments_json", scope.departments)):
            placeholders = ",".join("?" for _ in values) or "NULL"
            clauses.append(f"(m.{field}='[]' OR EXISTS (SELECT 1 FROM json_each(m.{field}) j WHERE j.value IN ({placeholders})))")
            params.extend(values)
        if scope.actor.projects:
            placeholders = ",".join("?" for _ in scope.actor.projects)
            clauses.append(f"m.project IN ({placeholders})")
            params.extend(scope.actor.projects)
        for kind, field in (("source", "d.source"), ("project", "m.project"),
                            ("department", "m.department"), ("document", "d.doc_id")):
            values = scope.denied.get(kind, [])
            if "*" in values:
                clauses.append("0")
            elif values:
                clauses.append(f"{field} NOT IN ({','.join('?' for _ in values)})")
                params.extend(values)
        return " AND ".join(clauses), params

    @staticmethod
    def vector_filter(scope: Scope):
        def match(key, value):
            return qm.FieldCondition(key=key, match=qm.MatchValue(value=value))
        must = [match("corpus", scope.corpus), match("published", True),
                qm.FieldCondition(key="acl", match=qm.MatchAny(any=list(scope.principals))),
                qm.FieldCondition(key="classification", range=qm.Range(lte=scope.actor.clearance))]
        if scope.day is not None:
            must.append(qm.FieldCondition(key="day", range=qm.Range(lte=scope.day)))
        for field, values in (("roles", scope.roles), ("departments", scope.departments)):
            must.append(qm.Filter(should=[match(field + "_unrestricted", True),
                qm.FieldCondition(key=field, match=qm.MatchAny(any=list(values)))]))
        if scope.actor.projects:
            must.append(qm.FieldCondition(key="project", match=qm.MatchAny(any=list(scope.actor.projects))))
        must_not = []
        for kind, field in (("source", "source"), ("project", "project"),
                            ("department", "department"), ("document", "doc_id")):
            values = scope.denied.get(kind, [])
            if values:
                # '*' is handled by the service/SQL gate before a vector call.
                must_not.append(qm.FieldCondition(key=field, match=qm.MatchAny(any=values)))
        return qm.Filter(must=must, must_not=must_not or None)

    @staticmethod
    def state(db):
        try:
            state = db.execute("SELECT * FROM cl_index_state WHERE id=1").fetchone()
        except sqlite3.OperationalError as error:
            raise IndexUnavailable("Snapshot not indexed. Run the integration index command.") from error
        if not state or state["state"] != "ready":
            raise IndexUnavailable("Snapshot indexing is pending or failed; retrieval is blocked.")
        return dict(state)

    def consistent(self, db, corpus):
        state = self.state(db)
        if self.expected_model and (state["model"] != self.expected_model or state["dim"] != 384):
            raise IndexUnavailable("Embedding model/configuration differs from published index.")
        if _published_guard_matches(db, corpus):
            return state
        _scan_snapshot(db, corpus)
        return state

    def install_snapshot_guard(self):
        """Seal an already-published snapshot so later reads skip the full scan.

        An immediate transaction keeps the scan and the stored counter on one
        snapshot. A later document or metadata write increments the counter and
        retrieval fails closed until the snapshot is published again.
        """
        with connect(self.db_path) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                self.state(db)
            except IndexUnavailable:
                return
            _ensure_guard_schema(db)
            for (corpus,) in db.execute("SELECT DISTINCT corpus FROM cl_metadata"):
                if db.execute("SELECT 1 FROM cl_mutation_published WHERE corpus=?", (corpus,)).fetchone():
                    continue
                _scan_snapshot(db, corpus)
                db.execute("INSERT INTO cl_mutation(corpus, n) VALUES (?, 0) ON CONFLICT(corpus) DO NOTHING", (corpus,))
                current = db.execute("SELECT n FROM cl_mutation WHERE corpus=?", (corpus,)).fetchone()[0]
                db.execute("INSERT INTO cl_mutation_published(corpus, n) VALUES (?, ?)", (corpus, current))
            db.commit()

    def search(self, scope: Scope, query: str, mode="hybrid", limit=8):
        if mode not in {"keyword", "vector", "hybrid"}:
            raise ValueError("unknown retrieval mode")
        where, args = self.sql_filter(scope)
        if not scope.principals or any("*" in scope.denied.get(k, []) for k in ("source", "project", "department", "document")):
            return [], None
        with connect(self.db_path) as db:
            db.execute("BEGIN")
            state = self.consistent(db, scope.corpus)
            keyword = []
            anchors = entity_terms(query)
            match = _fts_query(query)
            if mode != "vector" and match:
                keyword = [r[0] for r in db.execute(f"""SELECT d.doc_id FROM docs_fts
                    JOIN documents d ON d.corpus=docs_fts.corpus AND d.doc_id=docs_fts.doc_id
                    JOIN cl_metadata m ON m.corpus=d.corpus AND m.doc_id=d.doc_id
                    WHERE docs_fts MATCH ? AND {where}
                    ORDER BY bm25(docs_fts) LIMIT ?""", (match, *args, max(50, limit * 10)))]
            # Unknown explicit entities must not turn nearest neighbours into facts.
            if mode != "vector" and anchors and not keyword:
                return [], state["generation"]
            vector, chunks = [], {}
            if mode != "keyword":
                try:
                    embedding_query = " ".join(anchors) if anchors and re.search(r"[\u4e00-\u9fff]", query) else query
                    results = self.client.query_points(state["collection"], query=self.embed(embedding_query),
                        query_filter=self.vector_filter(scope), limit=80, with_payload=True).points
                except Exception as error:
                    raise IndexUnavailable("Filtered vector backend unavailable; no unfiltered fallback.") from error
                for point in results:
                    payload = point.payload or {}
                    if payload.get("corpus") != scope.corpus:
                        continue
                    doc_id = payload.get("doc_id")
                    if doc_id not in chunks:
                        vector.append(doc_id)
                        chunks[doc_id] = payload
            ranking = _rrf([keyword, vector]) if mode == "hybrid" else keyword if mode == "keyword" else vector
            hits = []
            for doc_id in ranking:
                hit = self._document(db, scope, doc_id, chunks.get(doc_id), query)
                if hit and (not anchors or contains_terms(hit["full_text"], anchors)):
                    hits.append(hit)
                    if len(hits) >= limit:
                        break
            return hits, state["generation"]

    def _document(self, db, scope, doc_id, vector_payload=None, query=""):
        where, args = self.sql_filter(scope)
        row = db.execute(f"""SELECT d.*,m.project,m.classification,m.indexed_at FROM documents d
            JOIN cl_metadata m ON m.corpus=d.corpus AND m.doc_id=d.doc_id
            WHERE {where} AND d.doc_id=?""", (*args, doc_id)).fetchone()
        if row is None:
            return None
        if hashlib.sha256(row["text"].encode()).hexdigest() != row["content_hash"]:
            raise IndexUnavailable("Canonical content hash mismatch.")
        if vector_payload:
            if vector_payload.get("version") != row["version"] or vector_payload.get("content_hash") != row["content_hash"]:
                return None
            chunk = db.execute("SELECT * FROM chunks WHERE chunk_id=? AND corpus=? AND doc_id=?",
                (vector_payload.get("chunk_id"), scope.corpus, doc_id)).fetchone()
            if chunk is None or hashlib.sha256(chunk["text"].encode()).hexdigest() != vector_payload.get("chunk_hash"):
                return None
        else:
            tokens = _fts_query(query).replace('"', '').split(" OR ")[:8]
            order = "MAX(" + ",".join("instr(lower(text),?)" for _ in tokens) + ") DESC," if len(tokens) > 1 else "instr(lower(text),?) DESC," if tokens and tokens[0] else ""
            arguments = tokens if order else []
            chunk = db.execute(f"SELECT * FROM chunks WHERE corpus=? AND doc_id=? ORDER BY {order} ordinal LIMIT 1",
                               (scope.corpus, doc_id, *[t.lower() for t in arguments])).fetchone()
        anchors = entity_terms(query)
        if anchors:
            # The English embedding may prefer a heading-only chunk. Choose a
            # substantive lexical chunk in the same authorised document instead.
            options = db.execute("SELECT * FROM chunks WHERE corpus=? AND doc_id=? ORDER BY ordinal",
                                 (scope.corpus, doc_id)).fetchall()
            scored = [(sum(len(re.findall(r"\b" + re.escape(term) + r"\b", item["text"], re.I)) for term in anchors),
                       min(len(item["text"].split()), 150), item) for item in options
                      if contains_terms(item["text"], anchors)]
            if scored:
                chunk = max(scored, key=lambda item: (item[0], item[1]))[2]
        if chunk is not None:
            expected = db.execute("SELECT content_hash FROM cl_chunks WHERE chunk_id=? AND corpus=? AND doc_id=?",
                                  (chunk["chunk_id"], scope.corpus, doc_id)).fetchone()
            if expected is None or expected[0] != hashlib.sha256(chunk["text"].encode()).hexdigest():
                raise IndexUnavailable("Derived chunk changed; rebuild before using it as evidence.")
        extra = json.loads(row["extra_json"])
        text = chunk["text"] if chunk else row["text"][:5000]
        return {"doc_id": row["doc_id"], "corpus": row["corpus"], "source": row["source"],
                "title": row["title"], "text": text, "full_text": row["text"],
                "chunk_id": chunk["chunk_id"] if chunk else None, "snippet": _snippet(text, query),
                "day": row["day"], "ts": row["ts"], "dept": row["dept"],
                "version": row["version"], "content_hash": row["content_hash"],
                "acl_basis": row["acl_basis"], "metadata": extra,
                "indexed_at": row["indexed_at"], "source_url": extra.get("source_url") or extra.get("url"),
                "freshness": "consistent_with_offline_snapshot", "source_check": "unknown"}

    def open(self, scope, doc_id):
        with connect(self.db_path) as db:
            db.execute("BEGIN")
            state = self.consistent(db, scope.corpus)
            hit = self._document(db, scope, doc_id)
            return hit, state["generation"]

    def suggestions(self, scope, query):
        """Only names found in currently authorised titles, never global vocab."""
        anchors = entity_terms(query)
        if len(anchors) != 1 or not scope.principals:
            return []
        term = anchors[0]
        where, args = self.sql_filter(scope)
        with connect(self.db_path) as db:
            db.execute("BEGIN")
            self.consistent(db, scope.corpus)
            titles = db.execute(f"SELECT d.title FROM documents d JOIN cl_metadata m ON m.corpus=d.corpus AND m.doc_id=d.doc_id WHERE {where} AND instr(lower(d.title),?)>0 LIMIT 200",
                                (*args, term[:2].lower())).fetchall()
        names = {name for row in titles for name in entity_terms(row[0])}
        ranked = sorted(((difflib.SequenceMatcher(None, term.lower(), name.lower()).ratio(), name) for name in names),
                        key=lambda item: (-item[0], item[1]))
        return [name for score, name in ranked if score >= .7 and name.lower() != term.lower()][:3]


def _scan_snapshot(db, corpus):
    mismatch = db.execute("""SELECT 1 FROM documents d LEFT JOIN cl_metadata m
        ON m.corpus=d.corpus AND m.doc_id=d.doc_id WHERE d.corpus=? AND (
        m.doc_id IS NULL OR d.version!=m.version OR d.content_hash!=m.content_hash OR
        d.acl_json!=m.acl_snapshot OR d.extra_json!=m.extra_snapshot OR
        NOT (d.day IS m.day) OR NOT (d.ts IS m.ts) OR d.source!=m.source OR d.dept!=m.department OR d.title!=m.title)
        LIMIT 1""", (corpus,)).fetchone()
    removed = db.execute("""SELECT 1 FROM cl_metadata m LEFT JOIN documents d
        ON m.corpus=d.corpus AND m.doc_id=d.doc_id WHERE m.corpus=? AND d.doc_id IS NULL LIMIT 1""", (corpus,)).fetchone()
    if mismatch or removed:
        raise IndexUnavailable("Known source snapshot changed; rebuild before retrieval.")


def _ensure_guard_schema(db):
    # Separate executes keep an open transaction intact. executescript would commit it.
    statements = [
        """CREATE TABLE IF NOT EXISTS cl_mutation (
            corpus TEXT PRIMARY KEY, n INTEGER NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS cl_mutation_published (
            corpus TEXT PRIMARY KEY, n INTEGER NOT NULL)""",
        """CREATE TRIGGER IF NOT EXISTS cl_guard_documents_ai AFTER INSERT ON documents BEGIN
            INSERT INTO cl_mutation(corpus, n) VALUES (NEW.corpus, 1)
            ON CONFLICT(corpus) DO UPDATE SET n = n + 1;
        END""",
        """CREATE TRIGGER IF NOT EXISTS cl_guard_documents_au AFTER UPDATE ON documents BEGIN
            INSERT INTO cl_mutation(corpus, n) VALUES (NEW.corpus, 1)
            ON CONFLICT(corpus) DO UPDATE SET n = n + 1;
            INSERT INTO cl_mutation(corpus, n) VALUES (OLD.corpus, 1)
            ON CONFLICT(corpus) DO UPDATE SET n = n + 1 WHERE OLD.corpus <> NEW.corpus;
        END""",
        """CREATE TRIGGER IF NOT EXISTS cl_guard_documents_ad AFTER DELETE ON documents BEGIN
            INSERT INTO cl_mutation(corpus, n) VALUES (OLD.corpus, 1)
            ON CONFLICT(corpus) DO UPDATE SET n = n + 1;
        END""",
        """CREATE TRIGGER IF NOT EXISTS cl_guard_metadata_ai AFTER INSERT ON cl_metadata BEGIN
            INSERT INTO cl_mutation(corpus, n) VALUES (NEW.corpus, 1)
            ON CONFLICT(corpus) DO UPDATE SET n = n + 1;
        END""",
        """CREATE TRIGGER IF NOT EXISTS cl_guard_metadata_au AFTER UPDATE ON cl_metadata
        WHEN OLD.source <> NEW.source OR OLD.version <> NEW.version OR OLD.content_hash <> NEW.content_hash
            OR OLD.acl_snapshot <> NEW.acl_snapshot OR OLD.extra_snapshot <> NEW.extra_snapshot
            OR NOT (OLD.day IS NEW.day) OR NOT (OLD.ts IS NEW.ts)
            OR OLD.department <> NEW.department OR OLD.title <> NEW.title
        BEGIN
            INSERT INTO cl_mutation(corpus, n) VALUES (NEW.corpus, 1)
            ON CONFLICT(corpus) DO UPDATE SET n = n + 1;
            INSERT INTO cl_mutation(corpus, n) VALUES (OLD.corpus, 1)
            ON CONFLICT(corpus) DO UPDATE SET n = n + 1 WHERE OLD.corpus <> NEW.corpus;
        END""",
        """CREATE TRIGGER IF NOT EXISTS cl_guard_metadata_ad AFTER DELETE ON cl_metadata BEGIN
            INSERT INTO cl_mutation(corpus, n) VALUES (OLD.corpus, 1)
            ON CONFLICT(corpus) DO UPDATE SET n = n + 1;
        END""",
    ]
    for statement in statements:
        db.execute(statement)


def _published_guard_matches(db, corpus):
    try:
        published = db.execute("SELECT n FROM cl_mutation_published WHERE corpus=?", (corpus,)).fetchone()
        current = db.execute("SELECT n FROM cl_mutation WHERE corpus=?", (corpus,)).fetchone()
    except sqlite3.OperationalError:
        return False
    if published is None or current is None:
        return False
    if int(published[0]) != int(current[0]):
        raise IndexUnavailable("Known source snapshot changed; rebuild before retrieval.")
    return True


def _sync_published_guard(db):
    _ensure_guard_schema(db)
    for (corpus,) in db.execute("SELECT DISTINCT corpus FROM documents"):
        db.execute("INSERT OR IGNORE INTO cl_mutation(corpus, n) VALUES (?, 0)", (corpus,))
    for corpus, count in db.execute("SELECT corpus, n FROM cl_mutation"):
        db.execute("INSERT OR REPLACE INTO cl_mutation_published(corpus, n) VALUES (?, ?)", (corpus, count))


def prepare_snapshot(db, collection: str, generation: str, model: str, dim: int):
    db.executescript("""
        CREATE TABLE IF NOT EXISTS cl_index_state (
            id INTEGER PRIMARY KEY CHECK(id=1), collection TEXT NOT NULL, generation TEXT NOT NULL,
            state TEXT NOT NULL, indexed_at TEXT NOT NULL, model TEXT NOT NULL, dim INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS cl_metadata (
            corpus TEXT NOT NULL,doc_id TEXT NOT NULL,source TEXT NOT NULL,version TEXT NOT NULL,
            content_hash TEXT NOT NULL,acl_snapshot TEXT NOT NULL,extra_snapshot TEXT NOT NULL,
            day INTEGER,ts TEXT,department TEXT NOT NULL,project TEXT NOT NULL,
            classification INTEGER NOT NULL,roles_json TEXT NOT NULL,departments_json TEXT NOT NULL,
            indexed_at TEXT NOT NULL,title TEXT NOT NULL,PRIMARY KEY(corpus,doc_id));
        CREATE TABLE IF NOT EXISTS cl_acl (
            corpus TEXT NOT NULL,doc_id TEXT NOT NULL,principal_id TEXT NOT NULL,
            PRIMARY KEY(corpus,doc_id,principal_id));
        CREATE INDEX IF NOT EXISTS cl_acl_principal ON cl_acl(corpus,principal_id,doc_id);
        CREATE INDEX IF NOT EXISTS cl_metadata_project ON cl_metadata(corpus,project,classification);
        CREATE TABLE IF NOT EXISTS cl_chunks (
            chunk_id TEXT PRIMARY KEY,corpus TEXT NOT NULL,doc_id TEXT NOT NULL,content_hash TEXT NOT NULL);
    """)
    timestamp = now()
    if "title" not in {row[1] for row in db.execute("PRAGMA table_info(cl_metadata)")}:
        db.execute("ALTER TABLE cl_metadata ADD COLUMN title TEXT NOT NULL DEFAULT ''")
    with db:
        db.execute("INSERT OR REPLACE INTO cl_index_state VALUES (1,?,?, 'building',?,?,?)",
                   (collection, generation, timestamp, model, dim))
        db.execute("DELETE FROM cl_metadata")
        db.execute("DELETE FROM cl_acl")
        db.execute("DELETE FROM cl_chunks")
        for doc in db.execute("SELECT corpus,doc_id,source,version,content_hash,acl_json,extra_json,day,ts,dept,title FROM documents"):
            extra = json.loads(doc["extra_json"])
            classification = extra.get("classification", "internal")
            level = LEVELS.get(classification, 4) if isinstance(classification, str) else 4
            roles, departments = extra.get("allowed_roles", []), extra.get("allowed_departments", [])
            if not isinstance(roles, list) or not isinstance(departments, list):
                raise ValueError("invalid explicit access constraints")
            db.execute("INSERT INTO cl_metadata VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (doc["corpus"], doc["doc_id"], doc["source"], doc["version"], doc["content_hash"],
                 doc["acl_json"], doc["extra_json"], doc["day"], doc["ts"], doc["dept"],
                 _name(extra.get("project")), level, json.dumps(roles), json.dumps(departments), timestamp, doc["title"]))
            db.executemany("INSERT OR IGNORE INTO cl_acl VALUES (?,?,?)",
                          [(doc["corpus"], doc["doc_id"], principal) for principal in json.loads(doc["acl_json"])])
        db.executemany("INSERT INTO cl_chunks VALUES (?,?,?,?)",
            ((chunk["chunk_id"], chunk["corpus"], chunk["doc_id"], hashlib.sha256(chunk["text"].encode()).hexdigest())
             for chunk in db.execute("SELECT * FROM chunks")))
        _sync_published_guard(db)


def payload_for(chunk, meta):
    roles, departments = json.loads(meta["roles_json"]), json.loads(meta["departments_json"])
    return {"corpus": meta["corpus"], "doc_id": meta["doc_id"], "chunk_id": chunk["chunk_id"],
            "version": meta["version"], "content_hash": meta["content_hash"],
            "chunk_hash": hashlib.sha256(chunk["text"].encode()).hexdigest(),
            "acl": json.loads(meta["acl_snapshot"]), "source": meta["source"],
            "department": meta["department"], "project": meta["project"],
            "classification": meta["classification"], "day": meta["day"] if meta["day"] is not None else -1,
            "published": True, "roles": roles, "roles_unrestricted": not roles,
            "departments": departments, "departments_unrestricted": not departments}


def migrate(db_path: Path, client, *, batch_size=128, reuse_embeddings=False):
    """Build a new collection, validate count, then publish; failed builds stay blocked."""
    import numpy as np

    from contextledger.vectors import DIM, _model

    generation = uuid.uuid4().hex
    collection = "contextledger_" + generation
    db = connect(db_path)
    prepare_snapshot(db, collection, generation, MODEL, DIM)
    client.create_collection(collection, vectors_config=qm.VectorParams(size=DIM, distance=qm.Distance.COSINE, on_disk=True))
    for key in ("corpus", "doc_id", "acl", "source", "department", "project", "roles", "departments"):
        client.create_payload_index(collection, key, qm.PayloadSchemaType.KEYWORD, wait=True)
    for key in ("published", "roles_unrestricted", "departments_unrestricted"):
        client.create_payload_index(collection, key, qm.PayloadSchemaType.BOOL, wait=True)
    for key in ("classification", "day"):
        client.create_payload_index(collection, key, qm.PayloadSchemaType.INTEGER, wait=True)
    written = 0
    try:
        corpora = [row[0] for row in db.execute("SELECT DISTINCT corpus FROM chunks ORDER BY corpus")]
        for corpus in corpora:
            matrix, cache = None, None
            if reuse_embeddings:
                directory = Path(db_path).parent / "vectors" / corpus
                status = json.loads((directory / "status.json").read_text())
                count = db.execute("SELECT COUNT(*) FROM chunks WHERE corpus=?", (corpus,)).fetchone()[0]
                if status.get("model") != MODEL or status.get("dim") != DIM or status.get("rows") != count:
                    raise ValueError("Part A embedding cache configuration does not match")
                matrix = np.memmap(directory / "embeddings.f32", dtype=np.float32, mode="r", shape=(count, DIM))
                cache = sqlite3.connect((directory / "rows.sqlite").resolve().as_uri() + "?mode=ro", uri=True)
                cache.row_factory = sqlite3.Row
                cursor = cache.execute("SELECT row_id,doc_id,chunk_id FROM vec_rows ORDER BY row_id")
            else:
                cursor = db.execute("SELECT * FROM chunks WHERE corpus=? ORDER BY rowid", (corpus,))
            try:
                while True:
                    rows = cursor.fetchmany(batch_size)
                    if not rows:
                        break
                    if matrix is not None:
                        chunks = [db.execute("SELECT * FROM chunks WHERE corpus=? AND chunk_id=? AND doc_id=?",
                                  (corpus, row["chunk_id"], row["doc_id"])).fetchone() for row in rows]
                        if any(chunk is None for chunk in chunks):
                            raise ValueError("Part A row mapping does not match canonical chunks")
                        vectors = [matrix[row["row_id"]].tolist() for row in rows]
                    else:
                        chunks = rows
                        vectors = _model().encode([row["text"] for row in chunks], normalize_embeddings=True,
                                  batch_size=batch_size, convert_to_numpy=True).tolist()
                    points = []
                    for chunk, vector in zip(chunks, vectors):
                        meta = db.execute("SELECT * FROM cl_metadata WHERE corpus=? AND doc_id=?", (corpus, chunk["doc_id"])).fetchone()
                        points.append(qm.PointStruct(id=point_id(corpus, chunk["doc_id"], meta["version"], chunk["chunk_id"]),
                                                      vector=vector, payload=payload_for(chunk, meta)))
                    client.upsert(collection, points, wait=True)
                    written += len(points)
                    if written % (batch_size * 20) == 0:
                        print(f"Qdrant indexed {written} chunks", flush=True)
            finally:
                if cache is not None:
                    cache.close()
                del matrix
        expected = db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        if written != expected or client.count(collection, exact=True).count != expected:
            raise RuntimeError("Qdrant publication count mismatch")
        # Reject a concurrently changed source snapshot before publishing.
        with db:
            published_at = now()
            changed = db.execute("UPDATE cl_index_state SET state='ready',indexed_at=? WHERE id=1 AND generation=? AND state='building'", (published_at, generation)).rowcount
            if changed != 1:
                raise RuntimeError("A newer index generation superseded this build")
            db.execute("UPDATE cl_metadata SET indexed_at=?", (published_at,))
            index = FilteredIndex(db_path, client, None)
            for corpus in corpora:
                index.consistent(db, corpus)
        print(f"Published {collection}: {written} chunks", flush=True)
        return {"collection": collection, "generation": generation, "chunks": written}
    except Exception:
        with db:
            db.execute("UPDATE cl_index_state SET state='failed' WHERE id=1 AND generation=?", (generation,))
        raise
    finally:
        db.close()
