"""Source sections with bounded tokens and source-derived context."""

from __future__ import annotations

from bisect import bisect_left
from functools import lru_cache
import re

from contextledger.models import Chunk, SourceDoc

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
MODEL_REVISION = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"
MAX_TOKENS = 256
CHUNKING_VERSION = "sections-tokens-context-v1"
_AUTHOR = re.compile(r"(?m)^\*\*Author:\*\*\s*(.+)$")
_DATE = re.compile(r"(?m)^\*\*Date:\*\*\s*(.+)$")
_HEADING = re.compile(r"^ {0,3}(#{1,6})\s+(.+?)\s*#*\s*$")
_SETEXT = re.compile(r"^ {0,3}(=+|-+)\s*$")
_FIELD = re.compile(r"^([\w /()-]{3,60}):\s*$")
_BOUNDARY = re.compile(r"\n[ \t]*\n|\n|[.!?。！？](?:[ \t]+|$)")


@lru_cache(maxsize=1)
def chunk_tokenizer():
    from transformers import AutoTokenizer

    return AutoTokenizer.from_pretrained(MODEL_NAME, revision=MODEL_REVISION, use_fast=True)


def _sections(text: str):
    lines = text.splitlines(keepends=True)
    path: list[tuple[int, str]] = []
    body: list[str] = []
    fence = None
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        marker = stripped[:3] if stripped.startswith(("```", "~~~")) else None
        if marker:
            fence = None if fence == marker else marker if fence is None else fence
        heading = _HEADING.match(line) if fence is None else None
        underline = (_SETEXT.match(lines[i + 1]) if fence is None and stripped
                     and i + 1 < len(lines) and len(lines[i + 1].strip()) >= 3 else None)
        field = _FIELD.match(line) if fence is None else None
        if heading or underline or field:
            if "".join(body).strip():
                yield tuple(title for _, title in path), "".join(body)
            if heading:
                level, title = len(heading[1]), heading[2]
            elif underline:
                level, title = (1 if underline[1].startswith("=") else 2), stripped
            else:
                level, title = 2, field[1]
            path = [(depth, label) for depth, label in path if depth < level]
            path.append((level, title))
            body = [line]
            if underline:
                i += 1
                body.append(lines[i])
        else:
            body.append(line)
        i += 1
    if "".join(body).strip():
        yield tuple(title for _, title in path), "".join(body)


def _prefix(title, path, tokenizer, budget):
    def trim(text, limit, tail=False):
        offsets = tokenizer(text, add_special_tokens=False, return_offsets_mapping=True,
                            truncation=False)["offset_mapping"]
        if len(offsets) <= limit:
            return text
        return text[offsets[-limit][0]:] if tail else text[:offsets[limit - 1][1]]

    title_tokens = len(tokenizer.encode(title.strip(), add_special_tokens=False))
    section_budget = max(1, budget - min(title_tokens, budget // 2))
    section = trim(" > ".join(path), section_budget, tail=True) if path else ""
    section_tokens = len(tokenizer.encode(section, add_special_tokens=False))
    title = trim(title.strip(), max(1, budget - section_tokens))
    text = "\n".join(part for part in (title, section) if part)
    return text + "\n\n" if text else ""


def _token_windows(text, prefix, tokenizer, max_tokens, overlap_tokens):
    encoded = tokenizer(text, add_special_tokens=False, return_offsets_mapping=True,
                        truncation=False)
    offsets = encoded["offset_mapping"]
    if not offsets:
        return
    starts = [start for start, _ in offsets]
    special = tokenizer.num_special_tokens_to_add(pair=False)
    capacity = max_tokens - special - len(tokenizer.encode(prefix, add_special_tokens=False)) - 3
    if capacity <= overlap_tokens:
        raise ValueError("context leaves insufficient body token budget")
    first, start = 0, 0
    while first < len(offsets):
        stop = min(first + capacity, len(offsets))
        end = len(text) if stop == len(offsets) else offsets[stop][0]
        if stop < len(offsets):
            lower = offsets[first + capacity * 3 // 5][0]
            boundaries = [start + match.end() for match in _BOUNDARY.finditer(text[start:end])
                          if start + match.end() >= lower]
            if boundaries:
                end = boundaries[-1]
                stop = bisect_left(starts, end)
        candidate = prefix + text[start:end].strip()
        while len(tokenizer.encode(candidate, add_special_tokens=True,
                                   truncation=False)) > max_tokens:
            stop -= 1
            if stop <= first:
                raise ValueError("a source token cannot fit in the chunk budget")
            end = offsets[stop][0]
            candidate = prefix + text[start:end].strip()
        if text[start:end].strip():
            yield candidate
        if end >= len(text):
            break
        # Reuse original character spans, never decode tokens back into source text.
        first = max(first + 1, stop - overlap_tokens)
        start = min(offsets[first][0], end)


def chunk_document(doc: SourceDoc, *, tokenizer=None, max_tokens=MAX_TOKENS,
                   overlap_tokens=32, contextual=True) -> list[Chunk]:
    if max_tokens < 32 or overlap_tokens < 0 or overlap_tokens >= max_tokens // 2:
        raise ValueError("invalid chunk size or overlap")
    tokenizer = tokenizer if tokenizer is not None else chunk_tokenizer()
    if not getattr(tokenizer, "is_fast", False):
        raise ValueError("chunking requires a fast tokenizer with character offsets")
    for pattern, name in ((_AUTHOR, "author"), (_DATE, "doc_date")):
        match = pattern.search(doc.text)
        if match:
            doc.extra[name] = match[1].strip()
    if doc.source == "slack" and doc.title.startswith("#"):
        doc.extra["channel"] = doc.title.split()[0].rstrip(":：,.")
    text = doc.text
    # Some exported Drive documents encode all line breaks as literal escapes.
    if doc.source in ("google_drive", "confluence") and "\n" not in text and text.count("\\n") >= 2:
        text = text.replace("\\n", "\n")
    chunks = []
    for path, body in _sections(text):
        prefix = _prefix(doc.title, path, tokenizer, min(64, max_tokens // 4)) if contextual else ""
        for piece in _token_windows(body, prefix, tokenizer, max_tokens, overlap_tokens):
            ordinal = len(chunks)
            chunks.append(Chunk(f"{doc.corpus}:{doc.doc_id}:{ordinal}", doc.corpus,
                                doc.doc_id, ordinal, piece))
    return chunks
