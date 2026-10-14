"""Tiny unified-service audit fixture; no legacy JSON or production stores."""
from contextlib import closing, contextmanager
import json
from pathlib import Path
from unittest.mock import patch


@contextmanager
def audit_fixture(root: Path):
    from qdrant_client import QdrantClient, models as qm
    from contextledger.access.identity_store import IdentityStore
    from contextledger.application.service import UnifiedService
    from contextledger.audit.store import AuditStore
    from contextledger.retrieval.filtered_index import (
        FilteredIndex, payload_for, point_id, prepare_snapshot,
    )
    from contextledger.storage.models import CanonicalDoc, Chunk, Principal
    from contextledger.storage.store import connect, content_hash, init_db, insert_documents, insert_principals

    db_path = root / "content/canonical.sqlite"
    ids = IdentityStore(root / "security/identities.sqlite")
    alice = ids.register("https://audit.fixture", "alice", "Alice")
    bob = ids.register("https://audit.fixture", "bob", "Bob")
    compliance = ids.register("https://audit.fixture", "compliance", "Compliance")
    ids.update(compliance.id, role="compliance")
    for actor in (alice, bob, compliance):
        ids.bind(actor.id, "audit", "audit:reader", True)
    client = QdrantClient(":memory:")
    try:
        client.create_collection("audit_fixture", vectors_config=qm.VectorParams(size=2, distance=qm.Distance.COSINE))
        with closing(connect(db_path)) as db, db:
            init_db(db)
            insert_principals(db, [Principal("audit", "audit:reader", "Reader", "engineer", "eng")], {})
            text = "Release incident root cause: a queue retry defect."
            digest = content_hash(text)
            doc = CanonicalDoc("audit", "audit-doc", "jira", "Incident", text, None, None,
                               "eng", [], ["audit:reader"], "declared_fixture",
                               digest[:12], digest, {}, ["audit-chunk"])
            insert_documents(db, [doc], [Chunk("audit-chunk", "audit", doc.doc_id, 0, text)])
            prepare_snapshot(db, "audit_fixture", "audit-generation", "fixture", 2)
            points = []
            for chunk in db.execute("SELECT * FROM chunks"):
                meta = db.execute("SELECT * FROM cl_metadata WHERE corpus=? AND doc_id=?",
                                  (chunk["corpus"], chunk["doc_id"])).fetchone()
                points.append(qm.PointStruct(id=point_id(chunk["corpus"], chunk["doc_id"], meta["version"], chunk["chunk_id"]),
                                             vector=[1., 0.], payload=payload_for(chunk, meta)))
            client.upsert("audit_fixture", points)
            db.execute("UPDATE cl_index_state SET state='ready'")
            db.commit()
        index = FilteredIndex(db_path, client, ids, embed=lambda query: [1., 0.])
        with patch.dict("os.environ", {"LLM_PROVIDER": "mock", "LLM_API_KEY": ""}):
            service = UnifiedService(index, ids, AuditStore(root / "security/audit.sqlite"))
        yield service, alice, bob, compliance
    finally:
        client.close()


def tamper(audit, mutation: str):
    """Mutate only a caller-owned temporary audit database, for chain probes."""
    with audit.db() as db:
        rows = db.execute("SELECT sequence,payload FROM events ORDER BY sequence").fetchall()
        if mutation == "modify":
            record = json.loads(rows[0][1])
            record["answer"] = "tampered"
            db.execute("UPDATE events SET payload=? WHERE sequence=?", (json.dumps(record), rows[0][0]))
        elif mutation == "delete_tail":
            db.execute("DELETE FROM events WHERE sequence=?", (rows[-1][0],))
        elif mutation == "reorder":
            db.execute("UPDATE events SET payload=? WHERE sequence=?", (rows[1][1], rows[0][0]))
            db.execute("UPDATE events SET payload=? WHERE sequence=?", (rows[0][1], rows[1][0]))
        else:
            raise ValueError("Unknown audit fixture mutation")
