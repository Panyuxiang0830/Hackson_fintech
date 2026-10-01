from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from threading import RLock
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


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class AuditService:
    """Append-only JSONL audit log with a hash chain and local head checkpoint."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.head_path = path.with_name(f"{path.stem}.head.json")
        self._lock = RLock()

    def _read_records(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        records: list[dict[str, Any]] = []
        for line_number, line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as error:
                raise AuditIntegrityError(f"invalid JSON at audit line {line_number}") from error
        return records

    def verify(self) -> AuditVerification:
        with self._lock:
            return self._verify()

    def _verify(self) -> AuditVerification:
        try:
            records = self._read_records()
        except AuditIntegrityError as error:
            return AuditVerification(False, 0, GENESIS_HASH, str(error))

        previous_hash = GENESIS_HASH
        for index, record in enumerate(records, start=1):
            if record.get("sequence") != index:
                return AuditVerification(False, len(records), previous_hash, f"sequence mismatch at event {index}")
            if record.get("previous_hash") != previous_hash:
                return AuditVerification(False, len(records), previous_hash, f"chain mismatch at event {index}")
            expected_hash = _event_hash(record)
            if record.get("event_hash") != expected_hash:
                return AuditVerification(False, len(records), previous_hash, f"content hash mismatch at event {index}")
            previous_hash = expected_hash

        if not records and not self.head_path.exists():
            return AuditVerification(True, 0, GENESIS_HASH)
        if not self.head_path.exists():
            return AuditVerification(False, len(records), previous_hash, "head checkpoint is missing")

        try:
            checkpoint = json.loads(self.head_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return AuditVerification(False, len(records), previous_hash, "head checkpoint is invalid JSON")

        if checkpoint.get("event_count") != len(records):
            return AuditVerification(False, len(records), previous_hash, "event count differs from checkpoint")
        if checkpoint.get("head_hash") != previous_hash:
            return AuditVerification(False, len(records), previous_hash, "head hash differs from checkpoint")
        return AuditVerification(True, len(records), previous_hash)

    def _write_checkpoint(self, event_count: int, head_hash: str) -> None:
        payload = json.dumps(
            {"event_count": event_count, "head_hash": head_hash},
            ensure_ascii=False,
            sort_keys=True,
        )
        temporary = self.head_path.with_suffix(self.head_path.suffix + ".tmp")
        temporary.write_text(payload + "\n", encoding="utf-8")
        os.replace(temporary, self.head_path)

    def append(self, record: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            return self._append(record)

    def _append(self, record: dict[str, Any]) -> dict[str, Any]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        verification = self._verify()
        if not verification.valid:
            raise AuditIntegrityError(verification.error or "audit chain verification failed")

        sealed = dict(record)
        sealed["sequence"] = verification.event_count + 1
        sealed["previous_hash"] = verification.head_hash
        sealed["event_hash"] = _event_hash(sealed)

        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(sealed, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        self._write_checkpoint(sealed["sequence"], sealed["event_hash"])
        return sealed

    def query(
        self,
        *,
        user_id: str | None = None,
        request_id: str | None = None,
        document_id: str | None = None,
        start: str | None = None,
        end: str | None = None,
    ) -> list[dict[str, Any]]:
        with self._lock:
            return self._query(
                user_id=user_id,
                request_id=request_id,
                document_id=document_id,
                start=start,
                end=end,
            )

    def _query(
        self,
        *,
        user_id: str | None = None,
        request_id: str | None = None,
        document_id: str | None = None,
        start: str | None = None,
        end: str | None = None,
    ) -> list[dict[str, Any]]:
        verification = self._verify()
        if not verification.valid:
            raise AuditIntegrityError(verification.error or "audit chain verification failed")

        start_at = _parse_timestamp(start) if start else None
        end_at = _parse_timestamp(end) if end else None
        results: list[dict[str, Any]] = []
        for record in self._read_records():
            if user_id and record.get("user_id") != user_id:
                continue
            if request_id and record.get("request_id") != request_id:
                continue
            if document_id:
                retrieved = record.get("retrieved_document_ids", [])
                decisions = record.get("authorization_decisions", [])
                decision_ids = [item.get("document_id") for item in decisions]
                if document_id not in retrieved and document_id not in decision_ids:
                    continue
            timestamp = _parse_timestamp(record["timestamp"])
            if start_at and timestamp < start_at:
                continue
            if end_at and timestamp > end_at:
                continue
            results.append(record)
        return results
