"""Records shared by the Part A ingest path."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SourceDoc:
    corpus: str
    doc_id: str
    source: str
    title: str
    text: str
    day: int | None
    ts: str | None
    dept: str
    actors: list[str]
    extra: dict = field(default_factory=dict)
    raw: dict = field(default_factory=dict)


@dataclass
class Principal:
    corpus: str
    principal_id: str
    name: str
    role: str
    dept: str
    active_from: int | None = None
    active_until: int | None = None


@dataclass
class CanonicalDoc:
    corpus: str
    doc_id: str
    source: str
    title: str
    text: str
    day: int | None
    ts: str | None
    dept: str
    actors: list[str]
    acl: list[str]
    acl_basis: str
    version: str
    content_hash: str
    extra: dict
    chunks: list[str]


@dataclass
class Chunk:
    chunk_id: str
    corpus: str
    doc_id: str
    ordinal: int
    text: str
