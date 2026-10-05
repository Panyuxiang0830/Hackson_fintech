"""Source-specific cleanup and chunking.

Confluence keeps its section structure. Slack stays one thread. Jira and Drive
are windowed. Drive text in these corpora is already extracted, so there is no
OCR step.
"""

from __future__ import annotations

import re

from contextledger.models import Chunk, SourceDoc

_HEADING = re.compile(r"(?m)^#{1,3} ")
_AUTHOR = re.compile(r"(?m)^\*\*Author:\*\*\s*(.+)$")
_DATE = re.compile(r"(?m)^\*\*Date:\*\*\s*(.+)$")


def _window(text: str, size: int = 1200, overlap: int = 150) -> list[str]:
    text = text.strip()
    if not text:
        return []
    if len(text) <= size:
        return [text]
    chunks = []
    start = 0
    while start < len(text):
        end = min(len(text), start + size)
        chunks.append(text[start:end].strip())
        if end >= len(text):
            break
        start = max(0, end - overlap)
    return [chunk for chunk in chunks if chunk]


def process_confluence(doc: SourceDoc) -> list[str]:
    author = _AUTHOR.search(doc.text)
    dated = _DATE.search(doc.text)
    if author:
        doc.extra["author"] = author.group(1).strip()
    if dated:
        doc.extra["doc_date"] = dated.group(1).strip()
    parts = _HEADING.split(doc.text)
    sections = [part.strip() for part in parts if part and part.strip()]
    if len(sections) <= 1:
        return _window(doc.text)
    chunks = []
    for section in sections:
        chunks.extend(_window(section, size=1600, overlap=120))
    return chunks or _window(doc.text)


def process_slack(doc: SourceDoc) -> list[str]:
    lines = [line.rstrip() for line in doc.text.splitlines()]
    cleaned = []
    blank = 0
    for line in lines:
        if not line.strip():
            blank += 1
            if blank <= 1 and cleaned:
                cleaned.append("")
            continue
        blank = 0
        cleaned.append(line.strip())
    text = "\n".join(cleaned).strip()
    doc.text = text or doc.text.strip()
    if doc.title.startswith("#"):
        doc.extra["channel"] = doc.title.split()[0].rstrip(":：,.")
    return _window(doc.text, size=1400, overlap=120)


def process_jira(doc: SourceDoc) -> list[str]:
    return _window(doc.text, size=1400, overlap=120)


def process_drive(doc: SourceDoc) -> list[str]:
    if _HEADING.search(doc.text):
        return process_confluence(doc)
    return _window(doc.text, size=1200, overlap=150)


_PROCESSORS = {
    "confluence": process_confluence,
    "slack": process_slack,
    "jira": process_jira,
    "google_drive": process_drive,
}


def chunk_document(doc: SourceDoc) -> list[Chunk]:
    processor = _PROCESSORS.get(doc.source, process_drive)
    pieces = processor(doc)
    chunks = []
    for ordinal, text in enumerate(pieces):
        chunks.append(
            Chunk(
                chunk_id=f"{doc.corpus}:{doc.doc_id}:{ordinal}",
                corpus=doc.corpus,
                doc_id=doc.doc_id,
                ordinal=ordinal,
                text=text,
            )
        )
    return chunks
