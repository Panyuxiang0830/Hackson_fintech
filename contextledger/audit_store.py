"""Transactional query audit chain; local checkpoint, not external immutability."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from src.audit import AuditIntegrityError, AuditVerification, GENESIS_HASH, _event_hash


class AuditStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self.db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS events (sequence INTEGER PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS checkpoint (id INTEGER PRIMARY KEY CHECK(id=1),
                    event_count INTEGER NOT NULL, head_hash TEXT NOT NULL);
            """)
            db.execute("INSERT OR IGNORE INTO checkpoint VALUES (1,0,?)", (GENESIS_HASH,))

    def db(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=FULL")
        return db

    @staticmethod
    def _verify(db):
        rows = db.execute("SELECT sequence,payload FROM events ORDER BY sequence").fetchall()
        previous = GENESIS_HASH
        try:
            for index, (sequence, payload) in enumerate(rows, 1):
                item = json.loads(payload)
                if sequence != index or item["sequence"] != index or item["previous_hash"] != previous:
                    return AuditVerification(False, len(rows), previous, "audit sequence/chain mismatch")
                if item["event_hash"] != _event_hash(item):
                    return AuditVerification(False, len(rows), previous, "audit content hash mismatch")
                previous = item["event_hash"]
            checkpoint = db.execute("SELECT event_count,head_hash FROM checkpoint WHERE id=1").fetchone()
            if checkpoint != (len(rows), previous):
                return AuditVerification(False, len(rows), previous, "audit checkpoint mismatch")
        except (ValueError, KeyError, TypeError):
            return AuditVerification(False, len(rows), previous, "invalid audit event")
        return AuditVerification(True, len(rows), previous)

    def verify(self):
        with self.db() as db:
            db.execute("BEGIN")
            return self._verify(db)

    def append(self, record: dict) -> dict:
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            verified = self._verify(db)
            if not verified.valid:
                raise AuditIntegrityError(verified.error)
            event = dict(record, sequence=verified.event_count + 1, previous_hash=verified.head_hash)
            event["event_hash"] = _event_hash(event)
            db.execute("INSERT INTO events VALUES (?,?)", (event["sequence"], json.dumps(event, ensure_ascii=False)))
            db.execute("UPDATE checkpoint SET event_count=?,head_hash=? WHERE id=1", (event["sequence"], event["event_hash"]))
            return event

    def query(self, *, user_id=None, request_id=None, document_id=None, start=None, end=None, limit=100):
        from datetime import datetime

        def dt(value):
            result = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if result.tzinfo is None:
                raise ValueError("audit time must contain timezone")
            return result

        start_at, end_at = dt(start) if start else None, dt(end) if end else None
        with self.db() as db:
            db.execute("BEGIN")
            verified = self._verify(db)
            if not verified.valid:
                raise AuditIntegrityError(verified.error)
            results = []
            for (payload,) in db.execute("SELECT payload FROM events ORDER BY sequence DESC"):
                event = json.loads(payload)
                if user_id and event.get("user_id") != user_id:
                    continue
                if request_id and event.get("request_id") != request_id:
                    continue
                if document_id and document_id not in event.get("retrieved_document_ids", []):
                    continue
                timestamp = dt(event["timestamp"])
                if start_at and timestamp < start_at or end_at and timestamp > end_at:
                    continue
                results.append(event)
                if len(results) >= limit:
                    break
            return results
