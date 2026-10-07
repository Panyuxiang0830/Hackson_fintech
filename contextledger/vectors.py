"""RaBitQ IVF indexes for Part A.

Each company has its own index. Embeddings stay on disk after the build;
queries load the RaBitQ index and the row map only. ACL is not stored in
the codes. Callers filter with can_see after search.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import threading
import time
from pathlib import Path

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

import numpy as np

from contextledger.processors import MODEL_NAME, MODEL_REVISION
from contextledger.store import chunk_digest, connect

DIM = 384
NBITS = 8
METRIC = "ip"
# OrgForge is small enough to probe every cluster. EnterpriseRAG probes 128 of 1024.
CLUSTER_PLAN = {
    "orgforge": {"num_clusters": 128, "nprobe": 128},
    "enterpriserag": {"num_clusters": 1024, "nprobe": 128},
}
_PREVIEW = {
    "orgforge": [
        "database storing athlete wearable telemetry",
        "backup power pack for the field radios",
    ],
    "enterpriserag": [
        "runbook",
        "steps to restore service after an outage",
    ],
}

_MODEL = None
_STORES: dict[tuple[str, str], "CorpusIndex"] = {}
_LOCK = threading.Lock()


class CorpusIndex:
    def __init__(self, index, rows: list[tuple[str, str]], nprobe: int, status_signature=None):
        self.index = index
        self.rows = rows
        self.nprobe = nprobe
        self.status_signature = status_signature

    @property
    def n(self) -> int:
        return len(self.rows)


def vectors_dir(out_dir: Path) -> Path:
    return out_dir / "vectors"


def corpus_dir(out_dir: Path, corpus: str) -> Path:
    return vectors_dir(out_dir) / corpus


def indexes_ready(out_dir: Path, corpus: str | None = None) -> tuple[bool, str]:
    meta_path = vectors_dir(out_dir) / "meta.json"
    if not meta_path.exists():
        return False, "missing vectors/meta.json; run: python -m contextledger vectors"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    if meta.get("model") != MODEL_NAME or meta.get("dim") != DIM:
        return False, "vector meta does not match this build"
    missing = []
    corpora = [corpus] if corpus else list(meta.get("corpora") or {})
    for current in corpora:
        info = (meta.get("corpora") or {}).get(current)
        index_path = corpus_dir(out_dir, current) / "ivf.index"
        if not info or not index_path.exists():
            missing.append(current)
    if missing:
        return False, "missing index for " + ", ".join(missing)
    rows = sum(int(meta["corpora"][current]["rows"]) for current in corpora)
    return True, f"RaBitQ IVF {meta['nbits']}-bit {meta['metric']} · {rows} chunks · {MODEL_NAME}"


def build_vectors(out_dir: Path, *, batch_size: int = 256) -> dict:
    """Embed every chunk and build one RaBitQ IVF index per corpus."""
    out_dir = out_dir.resolve()
    db_path = out_dir / "canonical.sqlite"
    if not db_path.exists():
        raise SystemExit(f"missing {db_path}; run: python -m contextledger build")
    started = time.time()
    summary = {}
    with connect(db_path) as connection:
        corpora = [row[0] for row in connection.execute("SELECT DISTINCT corpus FROM chunks ORDER BY corpus")]
    for corpus in corpora:
        plan = CLUSTER_PLAN.get(corpus, {"num_clusters": 128, "nprobe": 128})
        summary[corpus] = _build_corpus(
            out_dir,
            corpus,
            num_clusters=plan["num_clusters"],
            nprobe=plan["nprobe"],
            batch_size=batch_size,
        )
    meta = {
        "model": MODEL_NAME,
        "revision": MODEL_REVISION,
        "dim": DIM,
        "normalized": True,
        "metric": METRIC,
        "nbits": NBITS,
        "fast_quantization": True,
        "corpora": summary,
    }
    vectors_dir(out_dir).mkdir(parents=True, exist_ok=True)
    meta["seconds"] = round(time.time() - started, 1)
    (vectors_dir(out_dir) / "meta.json").write_text(
        json.dumps(meta, indent=2) + "\n", encoding="utf-8"
    )
    _update_manifest(out_dir, meta)
    print(json.dumps({"vectors": summary, "seconds": meta["seconds"]}, indent=2), flush=True)
    return meta


def preload(out_dir: Path) -> None:
    ready, detail = indexes_ready(out_dir)
    print(detail, flush=True)
    if not ready:
        return
    meta = json.loads((vectors_dir(out_dir) / "meta.json").read_text(encoding="utf-8"))
    for corpus in meta["corpora"]:
        get_store(out_dir, corpus)
    _model()


def get_store(out_dir: Path, corpus: str) -> CorpusIndex:
    out_dir = out_dir.resolve()
    key = (str(out_dir), corpus)
    with _LOCK:
        status_path = corpus_dir(out_dir, corpus) / "status.json"
        if not status_path.exists():
            raise FileNotFoundError(f"missing vector status for {corpus}; rebuild vectors")
        stat = status_path.stat()
        status_signature = (stat.st_mtime_ns, stat.st_size, stat.st_ino)
        cached = _STORES.get(key)
        if cached is not None and cached.status_signature == status_signature:
            return cached
        directory = corpus_dir(out_dir, corpus)
        status_path = directory / "status.json"
        if not status_path.exists():
            raise FileNotFoundError(f"missing {status_path}")
        status = json.loads(status_path.read_text(encoding="utf-8"))
        if status.get("model") != MODEL_NAME or int(status.get("dim", 0)) != DIM:
            raise RuntimeError(f"{corpus} vector index does not match {MODEL_NAME}")
        _ensure_bindings()
        from rabitqlib import IvfIndex

        index = IvfIndex.load(str(directory / "ivf.index"))
        rows = _load_rows(directory / "rows.sqlite", int(status["rows"]))
        store = CorpusIndex(index, rows, int(status["nprobe"]), status_signature)
        _STORES[key] = store
        return store


def search_chunks(out_dir: Path, corpus: str, query: str, *, k: int = 80) -> list[dict]:
    """Return doc ids for one corpus, best chunk first. Lower dist is nearer."""
    store = get_store(out_dir, corpus)
    if store.n == 0 or not query.strip():
        return []
    query_vec = _embed_query(query)
    topk = min(k, store.n)
    ids, dists = store.index.search(query_vec, topk, store.nprobe, True, 1)
    best: dict[str, tuple[float, str]] = {}
    for row_id, dist in _neighbors(ids[0], dists[0], store.n):
        doc_id, chunk_id = store.rows[row_id]
        current = best.get(doc_id)
        if current is None or dist < current[0]:
            best[doc_id] = (dist, chunk_id)
    ranked = sorted(best.items(), key=lambda item: (item[1][0], item[0]))
    return [
        {"doc_id": doc_id, "chunk_id": chunk_id, "dist": dist}
        for doc_id, (dist, chunk_id) in ranked
    ]


def _build_corpus(
    out_dir: Path,
    corpus: str,
    *,
    num_clusters: int,
    nprobe: int,
    batch_size: int,
) -> dict:
    directory = corpus_dir(out_dir, corpus)
    directory.mkdir(parents=True, exist_ok=True)
    db_path = out_dir / "canonical.sqlite"
    with connect(db_path) as connection:
        n = connection.execute(
            "SELECT COUNT(*) AS n FROM chunks WHERE corpus = ?", (corpus,)
        ).fetchone()["n"]
        signature = chunk_digest(connection, corpus)
    nlist = _choose_nlist(n, num_clusters)
    nprobe = min(nprobe, nlist)
    status_path = directory / "status.json"
    index_path = directory / "ivf.index"
    if status_path.exists() and index_path.exists():
        status = json.loads(status_path.read_text(encoding="utf-8"))
        if (status.get("index_done") and int(status.get("rows", -1)) == n
                and status.get("model") == MODEL_NAME and status.get("revision") == MODEL_REVISION
                and status.get("chunks_sha256") == signature):
            print(f"{corpus}: index already built ({n} chunks)", flush=True)
            return _public_status(status)

    print(f"{corpus}: embedding {n} chunks", flush=True)
    _embed_corpus(db_path, directory, corpus, n, batch_size, signature=signature)
    _preview_nearest(directory, n, _PREVIEW.get(corpus, []))
    print(f"{corpus}: clustering into {nlist} lists", flush=True)
    data = np.memmap(directory / "embeddings.f32", dtype=np.float32, mode="r", shape=(n, DIM))
    centroids, cluster_ids = _cluster(data, nlist)
    _ensure_bindings()
    from rabitqlib import IvfIndex

    print(f"{corpus}: quantizing with RaBitQ {NBITS}-bit {METRIC}", flush=True)
    index = IvfIndex(DIM, n, nlist, NBITS, METRIC)
    started = time.time()
    index.build(
        data,
        centroids,
        cluster_ids,
        num_threads=min(24, os.cpu_count() or 8),
        fast_quantization=True,
    )
    index.save(str(index_path))
    status = {
        "corpus": corpus,
        "model": MODEL_NAME,
        "revision": MODEL_REVISION,
        "dim": DIM,
        "rows": n,
        "normalized": True,
        "metric": METRIC,
        "nbits": NBITS,
        "num_clusters": nlist,
        "nprobe": nprobe,
        "fast_quantization": True,
        "index_done": True,
        "chunks_sha256": signature,
        "quantize_seconds": round(time.time() - started, 1),
    }
    status_path.write_text(json.dumps(status, indent=2) + "\n", encoding="utf-8")
    del index, centroids, cluster_ids, data
    print(f"{corpus}: saved {index_path}", flush=True)
    return _public_status(status)


def _embed_corpus(db_path: Path, directory: Path, corpus: str, n: int, batch_size: int,
                  *, signature: str | None = None) -> None:
    embed_path = directory / "embeddings.f32"
    progress_path = directory / "embed_rows.txt"
    rows_path = directory / "rows.sqlite"
    if signature is None:
        with connect(db_path) as connection:
            signature = chunk_digest(connection, corpus)
    signature_path = directory / "embed_signature.json"
    expected_signature = {"model": MODEL_NAME, "revision": MODEL_REVISION,
                          "dim": DIM, "chunks_sha256": signature}
    existing_signature = json.loads(signature_path.read_text()) if signature_path.exists() else None
    if existing_signature != expected_signature:
        model = _model()
        with connect(db_path) as connection:
            cursor = connection.execute("SELECT text FROM chunks WHERE corpus=? ORDER BY rowid", (corpus,))
            while True:
                batch = cursor.fetchmany(batch_size)
                if not batch:
                    break
                tokens = model.tokenizer([row["text"] or "" for row in batch],
                                         add_special_tokens=True, truncation=False)["input_ids"]
                if any(len(ids) > model.max_seq_length for ids in tokens):
                    raise RuntimeError("chunk exceeds embedding token limit; run contextledger rechunk")
        for path in (embed_path, rows_path, progress_path):
            path.unlink(missing_ok=True)
        signature_path.write_text(json.dumps(expected_signature) + "\n")
    expected = n * DIM * 4
    done = int(progress_path.read_text()) if progress_path.exists() else 0
    if embed_path.exists() and embed_path.stat().st_size != expected:
        embed_path.unlink()
        rows_path.unlink(missing_ok=True)
        progress_path.unlink(missing_ok=True)
        done = 0
    if done > n:
        done = 0
        rows_path.unlink(missing_ok=True)
        progress_path.unlink(missing_ok=True)
    if done == n and embed_path.exists():
        print(f"{corpus}: embeddings already on disk", flush=True)
        return

    matrix = np.memmap(embed_path, dtype=np.float32, mode="r+" if embed_path.exists() else "w+", shape=(n, DIM))
    rows = sqlite3.connect(rows_path)
    rows.execute(
        """
        CREATE TABLE IF NOT EXISTS vec_rows (
            row_id INTEGER PRIMARY KEY,
            doc_id TEXT NOT NULL,
            chunk_id TEXT NOT NULL
        )
        """
    )
    rows.commit()
    model = _model()
    source = connect(db_path)
    try:
        cursor = source.execute(
            """
            SELECT chunk_id, doc_id, text
            FROM chunks
            WHERE corpus = ?
            ORDER BY rowid
            LIMIT -1 OFFSET ?
            """,
            (corpus, done),
        )
        started = time.time()
        seen = done
        while True:
            batch = cursor.fetchmany(batch_size)
            if not batch:
                break
            texts = [row["text"] or "" for row in batch]
            lengths = model.tokenizer(texts, add_special_tokens=True, truncation=False)["input_ids"]
            if any(len(tokens) > model.max_seq_length for tokens in lengths):
                raise RuntimeError("chunk exceeds embedding token limit; run contextledger rechunk")
            encoded = model.encode(
                texts,
                batch_size=batch_size,
                normalize_embeddings=True,
                convert_to_numpy=True,
                show_progress_bar=False,
            )
            encoded = np.ascontiguousarray(encoded, dtype=np.float32)
            if encoded.shape != (len(batch), DIM):
                raise RuntimeError(f"expected {(len(batch), DIM)} embeddings, got {encoded.shape}")
            matrix[seen : seen + len(batch)] = encoded
            rows.executemany(
                "INSERT OR REPLACE INTO vec_rows (row_id, doc_id, chunk_id) VALUES (?, ?, ?)",
                [
                    (seen + offset, row["doc_id"], row["chunk_id"])
                    for offset, row in enumerate(batch)
                ],
            )
            rows.commit()
            matrix.flush()
            seen += len(batch)
            progress_path.write_text(str(seen))
            if seen == n or (seen // batch_size) % 25 == 0:
                rate = (seen - done) / max(time.time() - started, 1e-6)
                print(f"{corpus}: embedded {seen}/{n} ({rate:.0f} chunks/s)", flush=True)
    finally:
        source.close()
        rows.close()
        matrix.flush()
        del matrix
    if seen != n:
        raise RuntimeError(f"{corpus}: embedded {seen} of {n} chunks")


def _preview_nearest(directory: Path, n: int, queries: list[str]) -> None:
    if n == 0:
        return
    data = np.memmap(directory / "embeddings.f32", dtype=np.float32, mode="r", shape=(n, DIM))
    rows = _load_rows(directory / "rows.sqlite", n)
    matrix = np.asarray(data)
    for query in queries:
        scores = matrix @ _embed_query(query)[0]
        top_n = min(5, n)
        chosen = np.argpartition(-scores, top_n - 1)[:top_n]
        chosen = chosen[np.argsort(-scores[chosen])]
        print(f"nearest {query!r}", flush=True)
        for row_id in chosen.tolist():
            print(f"  {scores[row_id]:.3f} {rows[row_id][0]}", flush=True)
    del matrix, data


def _cluster(data: np.ndarray, nlist: int) -> tuple[np.ndarray, np.ndarray]:
    import faiss

    faiss.omp_set_num_threads(min(24, os.cpu_count() or 8))
    if not data.flags["C_CONTIGUOUS"]:
        data = np.ascontiguousarray(data)
    index = faiss.index_factory(DIM, f"IVF{nlist},Flat", faiss.METRIC_INNER_PRODUCT)
    index.verbose = True
    started = time.time()
    index.train(data)
    print(f"IVF training {time.time() - started:.1f}s", flush=True)
    centroids = np.ascontiguousarray(index.quantizer.reconstruct_n(0, nlist), dtype=np.float32)
    _, nearest = index.quantizer.search(data, 1)
    cluster_ids = nearest.reshape(-1).astype(np.uint32)
    if int(cluster_ids.max()) >= nlist:
        raise RuntimeError("faiss returned a cluster id outside the list")
    cluster_ids = _repair_empty(cluster_ids, nlist)
    del index
    return centroids, cluster_ids


def _repair_empty(cluster_ids: np.ndarray, nlist: int) -> np.ndarray:
    counts = np.bincount(cluster_ids, minlength=nlist)
    empty = np.flatnonzero(counts == 0)
    if empty.size == 0:
        return cluster_ids
    cluster_ids = cluster_ids.copy()
    for cid in empty.tolist():
        donor = int(np.argmax(counts))
        if counts[donor] <= 1:
            break
        moved = int(np.flatnonzero(cluster_ids == donor)[0])
        cluster_ids[moved] = np.uint32(cid)
        counts[donor] -= 1
        counts[cid] += 1
    still_empty = int(np.count_nonzero(np.bincount(cluster_ids, minlength=nlist) == 0))
    print(f"repaired empty clusters, {still_empty} still empty", flush=True)
    return cluster_ids


def _choose_nlist(n: int, requested: int) -> int:
    cap = max(1, n // 32)
    return max(1, min(requested, cap))


def _public_status(status: dict) -> dict:
    return {
        "rows": int(status["rows"]),
        "num_clusters": int(status["num_clusters"]),
        "nprobe": int(status["nprobe"]),
        "nbits": int(status.get("nbits", NBITS)),
        "metric": status.get("metric", METRIC),
    }


def _load_rows(path: Path, n: int) -> list[tuple[str, str]]:
    connection = sqlite3.connect(path)
    try:
        loaded = [("", "")] * n
        count = 0
        for row_id, doc_id, chunk_id in connection.execute(
            "SELECT row_id, doc_id, chunk_id FROM vec_rows ORDER BY row_id"
        ):
            if row_id < 0 or row_id >= n:
                raise RuntimeError(f"row id {row_id} outside 0..{n - 1}")
            loaded[row_id] = (doc_id, chunk_id)
            count += 1
    finally:
        connection.close()
    if count != n or any(not chunk_id for _, chunk_id in loaded):
        raise RuntimeError(f"row map {path} has {count} of {n} rows")
    return loaded


def _neighbors(ids_row, dists_row, n: int) -> list[tuple[int, float]]:
    pairs = [(int(row_id), float(dist)) for row_id, dist in zip(ids_row.tolist(), dists_row.tolist())]
    # Unfilled RaBitQ slots stay at the (0, 0) they were initialized to.
    while pairs and pairs[-1][0] == 0 and pairs[-1][1] == 0.0:
        pairs.pop()
    return [(row_id, dist) for row_id, dist in pairs if 0 <= row_id < n]


def _embed_query(text: str) -> np.ndarray:
    encoded = _model().encode(
        [text],
        normalize_embeddings=True,
        convert_to_numpy=True,
        show_progress_bar=False,
    )
    return np.ascontiguousarray(encoded, dtype=np.float32)


def _model():
    global _MODEL
    if _MODEL is None:
        import torch
        from sentence_transformers import SentenceTransformer

        device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"loading {MODEL_NAME} on {device}", flush=True)
        _MODEL = SentenceTransformer(MODEL_NAME, revision=MODEL_REVISION, device=device)
    return _MODEL


def _ensure_bindings() -> None:
    dist = Path(__file__).resolve().parents[1] / "runtime" / "rabitq-dist"
    if not (dist / "rabitqlib" / "__init__.py").exists():
        raise ImportError(
            f"RaBitQ Python bindings are not installed under {dist}. "
            "Configure RaBitQ-Library with RABITQ_BUILD_PYTHON_BINDINGS=ON "
            "and install into that prefix."
        )
    entry = str(dist)
    if entry not in sys.path:
        sys.path.insert(0, entry)


def _update_manifest(out_dir: Path, meta: dict) -> None:
    path = out_dir / "manifest.json"
    if not path.exists():
        return
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["vectors"] = {
        "model": meta["model"],
        "dim": meta["dim"],
        "metric": meta["metric"],
        "nbits": meta["nbits"],
        "corpora": meta["corpora"],
    }
    note = "Vector indexes are per company: RaBitQ IVF, 8-bit, inner product. ACL runs after search."
    notes = [item for item in manifest.get("notes", []) if not str(item).startswith("Vector indexes")]
    notes.append(note)
    manifest["notes"] = notes
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
