"""Shared canonical hashing and verification types for transactional audit."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any


GENESIS_HASH = "0" * 64


class AuditIntegrityError(RuntimeError):
    pass


@dataclass(frozen=True)
class AuditVerification:
    valid: bool
    event_count: int
    head_hash: str
    error: str | None = None


def _canonical_bytes(record: dict[str, Any]) -> bytes:
    payload = {key: value for key, value in record.items() if key != "event_hash"}
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _event_hash(record: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_bytes(record)).hexdigest()
