"""Isolated adapters for the existing unified retrieval path."""

from __future__ import annotations

import hashlib
import math
import re
from pathlib import Path

from contextledger.freshness_workload import key


class Encoder:
    def __init__(self, workload, embedding="minilm"):
        self.embedding = embedding
        texts = sorted({row["text"] for row in workload.revisions.values()} |
                       {row["query"] for row in workload.queries})
        if embedding == "minilm":
            from sentence_transformers import SentenceTransformer
            self.model_name = "sentence-transformers/all-MiniLM-L6-v2"
            model = SentenceTransformer(self.model_name, device="cpu", local_files_only=True)
            matrix = model.encode(texts, normalize_embeddings=True, batch_size=64,
                                  convert_to_numpy=True, show_progress_bar=False)
            self.dim = int(matrix.shape[1])
            self.cache = dict(zip(texts, matrix.tolist()))
        elif embedding == "fixture":
            self.model_name = "fixture-token-hash-128-v1"
            self.dim = 128
            self.cache = {text: self._fixture(text) for text in texts}
        else:
            raise ValueError("unknown embedding")

    def _fixture(self, text):
        vector = [0.0] * self.dim
        for token in re.findall(r"\w+", text.lower()):
            slot = int.from_bytes(hashlib.sha256(token.encode()).digest()[:4], "little") % self.dim
            vector[slot] += 1.0
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]

    def __call__(self, text):
        return self.cache[text]


class SnapshotReplay:
    """Source deliveries mutate only a temporary canonical store.

    Publication uses the production snapshot metadata, payload and service
    checks. Qdrant's local engine is a correctness fixture, not server HNSW.
    """

    def __init__(self, workload, directory: Path, encoder: Encoder):
        from qdrant_client import QdrantClient
        from contextledger.audit_store import AuditStore
        from contextledger.filtered_index import FilteredIndex
        from contextledger.identity_store import IdentityStore
        from contextledger.models import Principal
        from contextledger.store import connect, init_db, insert_principals
        from contextledger.unified_service import UnifiedService
        self.workload, self.encoder = workload, encoder
        self.db_path = directory / "content" / "canonical.sqlite"
        self.identities = IdentityStore(directory / "security" / "identities.sqlite")
        self.client = QdrantClient(":memory:")
        self.actors = {}
        self.collection = None
        self.generation = 0
        corpora = sorted({revision["corpus"] for revision in workload.revisions.values()})
        db = connect(self.db_path)
        try:
            init_db(db)
            principals = []
            for alias in workload.actors:
                actor = self.identities.register("freshness-eval", alias, alias)
                self.actors[alias] = actor.id
                for corpus in corpora:
                    principal = corpus + ":" + alias
                    principals.append(Principal(corpus, principal, alias, "engineer", "eng"))
                    if any(alias in revision["allowed_actors"] and revision["corpus"] == corpus
                           for revision in workload.revisions.values()):
                        self.identities.bind(actor.id, corpus, principal, True)
            insert_principals(db, principals, {})
            db.commit()
        finally:
            db.close()
        self.index = FilteredIndex(self.db_path, self.client, self.identities, embed=encoder)
        # Search never calls the answer model, regardless of ambient API settings.
        self.service = UnifiedService(self.index, self.identities,
                                      AuditStore(directory / "security" / "audit.sqlite"), answer=object())
        for event in workload.events:
            if event.get("initial"):
                self.receive(event)
        self.publish()

    def receive(self, event):
        from contextledger.filtered_index import point_id
        from contextledger.models import CanonicalDoc, Chunk
        from contextledger.store import connect, insert_documents
        db = connect(self.db_path)
        try:
            with db:
                for table in ("documents", "chunks", "docs_fts"):
                    db.execute(f"DELETE FROM {table} WHERE corpus=? AND doc_id=?", (event["corpus"], event["doc_id"]))
                if event["op"] == "upsert":
                    revision = self.workload.revisions[key(event)]
                    chunk_id = point_id(revision["corpus"], revision["doc_id"], revision["version"], 0)
                    extra = {"classification": "internal", "controlled_replay": True,
                             "source_event_ms": event["at_ms"]}
                    doc = CanonicalDoc(revision["corpus"], revision["doc_id"], revision["source"],
                        revision["title"], revision["text"], None, None, "eng", [],
                        [revision["corpus"] + ":" + alias for alias in revision["allowed_actors"]],
                        "explicit synthetic workload ACL", revision["version"], revision["content_hash"], extra, [chunk_id])
                    insert_documents(db, [doc], [Chunk(chunk_id, doc.corpus, doc.doc_id, 0, doc.text)])
        finally:
            db.close()

    def publish(self):
        from qdrant_client import models as qm
        from contextledger.filtered_index import payload_for, point_id, prepare_snapshot
        from contextledger.store import connect
        self.generation += 1
        collection = "freshness_snapshot_" + str(self.generation)
        db = connect(self.db_path)
        try:
            prepare_snapshot(db, collection, str(self.generation), self.encoder.model_name, self.encoder.dim)
            self.client.create_collection(collection, vectors_config=qm.VectorParams(
                size=self.encoder.dim, distance=qm.Distance.COSINE))
            points = []
            for chunk in db.execute("SELECT * FROM chunks ORDER BY corpus,doc_id"):
                metadata = db.execute("SELECT * FROM cl_metadata WHERE corpus=? AND doc_id=?",
                                      (chunk["corpus"], chunk["doc_id"])).fetchone()
                points.append(qm.PointStruct(id=point_id(chunk["corpus"], chunk["doc_id"], metadata["version"], chunk["chunk_id"]),
                    vector=self.encoder(chunk["text"]), payload=payload_for(chunk, metadata)))
            if points:
                self.client.upsert(collection, points, wait=True)
            if self.client.count(collection, exact=True).count != len(points):
                raise RuntimeError("replay publication count mismatch")
            with db:
                db.execute("UPDATE cl_index_state SET state='ready' WHERE id=1")
            for (corpus,) in db.execute("SELECT DISTINCT corpus FROM documents"):
                self.index.consistent(db, corpus)
            old = self.collection
            self.collection = collection
            if old:
                self.client.delete_collection(old)
        finally:
            db.close()

    def search(self, query, mode):
        from contextledger.filtered_index import IndexUnavailable
        from contextledger.unified_service import PermissionChanged
        try:
            response, hits = self.service.search(self.actors[query["actor_id"]], query["corpus"],
                                                 query["query"], mode=mode)
            return {"status": "ok", "request_id": response["request_id"], "hits": [
                {field: hit[field] for field in ("corpus", "doc_id", "version", "content_hash")} for hit in hits]}
        except (IndexUnavailable, PermissionChanged, PermissionError) as error:
            return {"status": "unavailable", "error": type(error).__name__, "hits": []}

    def close(self):
        self.client.close()
