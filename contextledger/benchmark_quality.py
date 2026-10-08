"""Offline quality checks that do not call a model or an API.

Reference precision counts gold document overlap only. A document that is
not in the gold set is not proven irrelevant. Extractive answers copy
sentences from the hit text supplied by the caller.
"""

from __future__ import annotations

from contextlib import closing
import math
import tempfile
import time
from pathlib import Path

from contextledger.models import CanonicalDoc, Chunk
from contextledger.store import connect, content_hash, init_db, insert_documents

AUTHORITY_ORDER = ("confluence", "jira", "google_drive", "slack")
PARAGRAPH_CHARS = 400


def reference_precision(gold: tuple[str, ...] | list[str], ranked: list[str], k: int) -> float | None:
    found = list(dict.fromkeys(ranked))[:k]
    if not found:
        return None
    return len(set(gold).intersection(found)) / len(found)


def approx_tokens(text: str) -> int:
    """Character estimate. This is not a model tokenizer count."""
    if not text:
        return 0
    return math.ceil(len(text) / 4)


def build_prompt(query: str, hits: list[dict]) -> str:
    """Build a prompt from the hits the caller already decided to show."""
    blocks = []
    for hit in hits:
        body = hit.get("snippet") or hit.get("text") or ""
        blocks.append(f"[{hit.get('doc_id', '')}] {hit.get('title', '')}\n{body}")
    evidence = "\n\n".join(blocks)
    return f"Question: {query}\n\nEvidence:\n{evidence}"


def _sentences(text: str) -> list[str]:
    parts = []
    start = 0
    index = 0
    while index < len(text):
        char = text[index]
        decimal = (
            char == "."
            and index > 0
            and text[index - 1].isdigit()
            and index + 1 < len(text)
            and text[index + 1].isdigit()
        )
        if char in "!?" or (char == "." and not decimal):
            sentence = text[start : index + 1].strip()
            if sentence:
                parts.append(sentence)
            start = index + 1
        index += 1
    tail = text[start:].strip()
    if tail:
        parts.append(tail)
    return parts


def _content_words(text: str) -> set[str]:
    words = set()
    current = []
    for char in text.lower():
        if char.isalnum():
            current.append(char)
            continue
        if current:
            token = "".join(current)
            if len(token) > 3:
                words.add(token)
            current = []
    if current:
        token = "".join(current)
        if len(token) > 3:
            words.add(token)
    return words


def _numbers(text: str) -> list[str]:
    found = []
    current = []
    for char in text:
        if char.isdigit() or (char == "." and current and current[-1].isdigit()):
            current.append(char)
            continue
        if current:
            token = "".join(current).strip(".")
            if token:
                found.append(token)
            current = []
    if current:
        token = "".join(current).strip(".")
        if token:
            found.append(token)
    return found


def _fact_covered(answer: str, fact: str) -> float | None:
    """1 when every number appears and at least 60% of long words appear."""
    if not fact or not fact.strip():
        return None
    answer_numbers = set(_numbers(answer))
    if any(number not in answer_numbers for number in _numbers(fact)):
        return 0.0
    words = _content_words(fact)
    if not words:
        return 1.0 if _numbers(fact) else None
    overlap = sum(word in _content_words(answer) for word in words) / len(words)
    return 1.0 if overlap >= 0.6 else 0.0


def compose_extractive_answer(query: str, hits: list[dict]) -> dict:
    """Copy overlapping evidence sentences. Abstain when none overlap."""
    query_words = _content_words(query)
    copied = []
    citations = []
    bodies = []
    for hit in hits:
        body = (hit.get("snippet") or hit.get("text") or "").strip()
        if not body:
            continue
        bodies.append(body)
        doc_id = hit.get("doc_id") or ""
        used = False
        for sentence in _sentences(body):
            if query_words and _content_words(sentence) & query_words:
                copied.append(sentence)
                used = True
        if used and doc_id and doc_id not in citations:
            citations.append(doc_id)
    return {
        "answer": " ".join(copied),
        "abstained": not copied,
        "citations": citations,
        "evidence": "\n".join(bodies),
    }


def score_answer(
    *,
    gold_doc_ids: tuple[str, ...] | list[str],
    citations: list[str],
    answer: str,
    evidence: str,
    gold_answer: str = "",
    answer_facts: tuple[str, ...] | list[str] = (),
    is_answerable: bool | None = None,
) -> dict:
    """Lexical diagnostics only; empty reference ids do not label answerability."""
    gold = set(gold_doc_ids)
    cited = list(dict.fromkeys(citations))
    citation_recall = len(gold.intersection(cited)) / len(gold) if gold else None
    citation_reference_precision = (
        len(gold.intersection(cited)) / len(cited) if cited and gold else None
    )
    facts = [fact for fact in answer_facts if isinstance(fact, str) and fact.strip()]
    fact_scores = [_fact_covered(answer, fact) for fact in facts]
    scorable = [score for score in fact_scores if score is not None]
    fact_coverage = sum(scorable) / len(scorable) if scorable else None
    sentences = _sentences(answer) if answer.strip() else []
    nonverbatim_rate = (
        sum(sentence not in evidence for sentence in sentences) / len(sentences) if sentences else None
    )
    return {
        "citation_recall": citation_recall,
        "citation_reference_precision": citation_reference_precision,
        "lexical_fact_overlap": fact_coverage,
        "scorable_answer_facts": len(scorable),
        "lexical_gold_answer_overlap": _fact_covered(answer, gold_answer),
        "nonverbatim_sentence_rate": nonverbatim_rate,
        "abstained": not answer.strip(),
        "abstention_matches_label": bool(answer.strip()) == is_answerable if is_answerable is not None else None,
    }


def measure_hits(
    query: str,
    hits: list[dict],
    gold: tuple[str, ...],
    *,
    gold_answer: str = "",
    answer_facts: tuple[str, ...] = (),
    as_of_day: int | None = None,
    is_answerable: bool | None = None,
) -> dict:
    """Score hits without retaining the answer text."""
    composed = compose_extractive_answer(query, hits)
    scored = score_answer(
        gold_doc_ids=gold,
        citations=composed["citations"],
        answer=composed["answer"],
        evidence=composed["evidence"],
        gold_answer=gold_answer,
        answer_facts=answer_facts,
        is_answerable=is_answerable,
    )
    scored["approx_prompt_tokens"] = approx_tokens(build_prompt(query, hits))
    scored["approx_answer_tokens"] = approx_tokens(composed["answer"])
    if as_of_day is None:
        scored["future_hits"] = None
    else:
        scored["future_hits"] = sum(
            1
            for hit in hits
            if isinstance(hit.get("day"), int) and not isinstance(hit.get("day"), bool) and hit["day"] > as_of_day
        )
    return scored


def authority_preference(hits: list[dict]) -> dict:
    """Report source rank. This does not change retrieval order."""
    sources = [hit.get("source") for hit in hits if hit.get("source")]
    top = sources[0] if sources else None
    preferred = next((source for source in AUTHORITY_ORDER if source in sources), None)
    return {
        "top_source": top,
        "preferred_source": preferred,
        "top_is_preferred": (top == preferred) if preferred is not None else None,
    }


def stale_rank(hits: list[dict], current_id: str, superseded_id: str) -> dict:
    ids = [hit.get("doc_id") for hit in hits]
    current_rank = ids.index(current_id) + 1 if current_id in ids else None
    superseded_rank = ids.index(superseded_id) + 1 if superseded_id in ids else None
    current_ahead = current_rank is not None and (superseded_rank is None or current_rank < superseded_rank)
    return {
        "current_rank": current_rank,
        "superseded_rank": superseded_rank,
        "current_ahead_of_superseded": current_ahead,
    }


def paragraph_chunks(text: str, width: int = PARAGRAPH_CHARS) -> list[str]:
    """Split fixture text on paragraphs. This is not the MiniLM chunker."""
    paragraphs = [part.strip() for part in text.split("\n\n") if part.strip()]
    if not paragraphs and text.strip():
        paragraphs = [text.strip()]
    pieces = []
    for paragraph in paragraphs:
        if len(paragraph) <= width:
            pieces.append(paragraph)
            continue
        for start in range(0, len(paragraph), width):
            pieces.append(paragraph[start : start + width])
    return pieces


def measure_ingest(documents: list[tuple[str, str]] | None = None) -> dict:
    """Time paragraph chunking and a temporary SQLite insert.

    Embedding is not loaded. The live store is not opened.
    """
    samples = documents or [
        ("policy", "Authoritative upload limit is 10 MiB.\n\n" + ("detail " * 80)),
        ("incident", "The postmortem says the upload limit is 10 MiB."),
        ("status", "Project state is open."),
    ]
    started = time.perf_counter()
    canonical = []
    chunks = []
    for doc_id, text in samples:
        pieces = paragraph_chunks(text)
        chunk_ids = []
        for ordinal, piece in enumerate(pieces):
            chunk_id = f"ingest/{doc_id}/{ordinal}"
            chunk_ids.append(chunk_id)
            chunks.append(Chunk(chunk_id, "ingest", doc_id, ordinal, piece))
        digest = content_hash(text)
        canonical.append(CanonicalDoc(
            "ingest", doc_id, "confluence", doc_id, text, 1, None, "fixture", [],
            ["ingest:alice"], "declared_fixture", digest[:12], digest, {}, chunk_ids,
        ))
    chunk_seconds = time.perf_counter() - started
    insert_started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="contextledger-ingest-") as directory:
        db_path = Path(directory) / "canonical.sqlite"
        with closing(connect(db_path)) as connection:
            init_db(connection)
            insert_documents(connection, canonical, chunks)
            connection.commit()
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        index_bytes = db_path.stat().st_size
        for suffix in ("-wal", "-shm"):
            extra = Path(str(db_path) + suffix)
            if extra.exists():
                index_bytes += extra.stat().st_size
    insert_seconds = time.perf_counter() - insert_started
    elapsed = max(chunk_seconds + insert_seconds, 1e-9)
    return {
        "documents": len(canonical),
        "chunks": len(chunks),
        "chunking": "paragraph-400 fixture chunker. Embedding models are not loaded.",
        "embedding": "not_measured",
        "docs_per_second": len(canonical) / elapsed,
        "chunks_per_second": len(chunks) / elapsed,
        "chunk_seconds": chunk_seconds,
        "insert_seconds": insert_seconds,
        "index_bytes": index_bytes,
        "live_store": False,
    }
