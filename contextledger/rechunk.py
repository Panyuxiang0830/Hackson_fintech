"""Rebuild derived chunks without changing documents, FTS, or permissions."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import time

from contextledger.models import SourceDoc
from contextledger.processors import CHUNKING_VERSION, MAX_TOKENS, chunk_document
from contextledger.store import chunk_digest


def rechunk(out_dir: Path, *, corpora=None, tokenizer=None, contextual=True,
            max_tokens=MAX_TOKENS, overlap_tokens=32) -> dict:
    out_dir = out_dir.resolve()
    database = out_dir / "canonical.sqlite"
    if not database.exists():
        raise FileNotFoundError(database)
    vectors_root = out_dir / "vectors"
    if vectors_root.is_symlink() or (vectors_root.exists() and any(
            not path.resolve().is_relative_to(out_dir) or path.is_symlink()
            for path in vectors_root.glob("*/status.json"))):
        raise ValueError("rechunk needs private vector artifacts; prepare a fresh-vectors snapshot first")
    started = time.perf_counter()
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    summaries = {}
    try:
        selected = sorted(set(corpora)) if corpora is not None else [row[0] for row in
            connection.execute("SELECT DISTINCT corpus FROM documents ORDER BY corpus")]
        if not selected:
            raise ValueError("no corpora selected")
        connection.execute("BEGIN IMMEDIATE")
        has_datasets = connection.execute("SELECT 1 FROM sqlite_master WHERE name='datasets'").fetchone()
        for corpus in selected:
            count = connection.execute("SELECT COUNT(*) FROM documents WHERE corpus=?", (corpus,)).fetchone()[0]
            if not count:
                raise ValueError(f"unknown corpus: {corpus}")
            old_count = connection.execute("SELECT COUNT(*) FROM chunks WHERE corpus=?", (corpus,)).fetchone()[0]
            old_digest = chunk_digest(connection, corpus)
            rows = connection.execute("SELECT * FROM documents WHERE corpus=? ORDER BY doc_id", (corpus,))
            new_count = 0
            for i, row in enumerate(rows, 1):
                doc = SourceDoc(corpus, row["doc_id"], row["source"], row["title"],
                                row["text"], row["day"], row["ts"], row["dept"],
                                json.loads(row["actors_json"]), json.loads(row["extra_json"]))
                pieces = chunk_document(doc, tokenizer=tokenizer, contextual=contextual,
                                        max_tokens=max_tokens, overlap_tokens=overlap_tokens)
                if doc.text.strip() and not pieces:
                    raise ValueError(f"no chunks for {corpus}/{doc.doc_id}")
                replacements = [(p.chunk_id, p.corpus, p.doc_id, p.ordinal, p.text) for p in pieces]
                existing = [tuple(item) for item in connection.execute(
                    "SELECT * FROM chunks WHERE corpus=? AND doc_id=? ORDER BY ordinal", (corpus, doc.doc_id))]
                if existing != replacements:
                    connection.execute("DELETE FROM chunks WHERE corpus=? AND doc_id=?", (corpus, doc.doc_id))
                    connection.executemany("INSERT INTO chunks VALUES (?,?,?,?,?)", replacements)
                new_count += len(pieces)
                if i % 5000 == 0 or i == count:
                    print(f"rechunk {corpus}: {i}/{count}, {new_count} chunks", flush=True)
            connection.execute("""DELETE FROM chunks WHERE corpus=? AND NOT EXISTS (
                SELECT 1 FROM documents d WHERE d.corpus=chunks.corpus AND d.doc_id=chunks.doc_id)""", (corpus,))
            summaries[corpus] = {"documents": count, "old_chunks": old_count,
                                  "chunks": new_count, "chunks_sha256": chunk_digest(connection, corpus)}
            summaries[corpus]["changed"] = summaries[corpus]["chunks_sha256"] != old_digest
            if has_datasets:
                dataset = connection.execute("SELECT metadata_json FROM datasets WHERE corpus=?", (corpus,)).fetchone()
                if dataset:
                    metadata = json.loads(dataset[0])
                    metadata["chunks"] = new_count
                    connection.execute("UPDATE datasets SET metadata_json=? WHERE corpus=?",
                                       (json.dumps(metadata, ensure_ascii=False), corpus))
        if any(summary["changed"] for summary in summaries.values()) and connection.execute(
                "SELECT 1 FROM sqlite_master WHERE name='cl_index_state'").fetchone():
            # The Qdrant collection still addresses the old chunks. Mark it
            # stale in the same transaction, even in a standalone Part A run.
            connection.execute("UPDATE cl_index_state SET state='stale' WHERE id=1")
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()
    # Stale vectors must not serve newly numbered chunks, even when counts match.
    changed = [corpus for corpus in selected if summaries[corpus]["changed"]]
    if changed:
        (out_dir / "vectors/meta.json").unlink(missing_ok=True)
    for corpus in changed:
        (out_dir / "vectors" / corpus / "status.json").unlink(missing_ok=True)
    vectors = sys.modules.get("contextledger.vectors")
    if vectors is not None:
        with vectors._LOCK:
            for key in list(vectors._STORES):
                if key[0] == str(out_dir) and key[1] in changed:
                    del vectors._STORES[key]
    report = {"version": CHUNKING_VERSION, "max_tokens": max_tokens,
              "overlap_tokens": overlap_tokens, "contextual": contextual,
              "processor_sha256": hashlib.sha256(Path(chunk_document.__code__.co_filename).read_bytes()).hexdigest(),
              "corpora": summaries, "seconds": time.perf_counter() - started}
    manifest_path = out_dir / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        manifest["chunking"] = report
        if changed:
            manifest.pop("vectors", None)
        with sqlite3.connect(database) as conn:
            manifest["chunks"] = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
            if has_datasets:
                manifest["supplemental"] = {row[0]: json.loads(row[1]) for row in
                                            conn.execute("SELECT corpus,metadata_json FROM datasets")}
        temporary = manifest_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
        temporary.replace(manifest_path)
    return report
