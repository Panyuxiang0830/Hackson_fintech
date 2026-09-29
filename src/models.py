from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


CLASSIFICATION_LEVELS = {
    "public": 0,
    "internal": 1,
    "confidential": 2,
    "restricted": 3,
}


@dataclass(frozen=True)
class User:
    id: str
    name: str
    department: str
    role: str
    clearance: str
    projects: tuple[str, ...] = field(default_factory=tuple)
    employment_type: str = "employee"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "User":
        return cls(
            id=data["id"],
            name=data["name"],
            department=data["department"],
            role=data["role"],
            clearance=data["clearance"],
            projects=tuple(data.get("projects", [])),
            employment_type=data.get("employment_type", "employee"),
        )


@dataclass(frozen=True)
class Document:
    id: str
    source: str
    title: str
    content: str
    created_at: str
    updated_at: str
    classification: str
    allowed_departments: tuple[str, ...] = field(default_factory=tuple)
    allowed_roles: tuple[str, ...] = field(default_factory=tuple)
    project: str | None = None
    status: str = "active"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Document":
        return cls(
            id=data["id"],
            source=data["source"],
            title=data["title"],
            content=data["content"],
            created_at=data["created_at"],
            updated_at=data["updated_at"],
            classification=data["classification"],
            allowed_departments=tuple(data.get("allowed_departments", [])),
            allowed_roles=tuple(data.get("allowed_roles", [])),
            project=data.get("project"),
            status=data.get("status", "active"),
        )


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    reason: str


@dataclass(frozen=True)
class Evidence:
    document: Document
    score: float
    access_reason: str


@dataclass(frozen=True)
class AnswerResult:
    request_id: str
    user: User
    question: str
    answer: str
    evidence: tuple[Evidence, ...]
    denied_document_count: int
    decision: str
    provider: str
    audit_record: dict[str, Any]

