#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.audit import AuditService  # noqa: E402


def sample_record(request_id: str) -> dict:
    return {
        "event_type": "knowledge_query",
        "request_id": request_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "user_id": "demo-user",
        "question": "demo query",
        "authorization_decisions": [],
        "retrieved_document_ids": ["demo-doc"],
        "final_answer": "original answer",
        "decision": "answered",
        "provider": "mock",
    }


def main() -> int:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "audit.jsonl"
        audit = AuditService(path)
        audit.append(sample_record("demo-1"))
        audit.append(sample_record("demo-2"))
        before = audit.verify()

        records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        records[0]["final_answer"] = "tampered answer"
        path.write_text(
            "\n".join(json.dumps(record, sort_keys=True) for record in records) + "\n",
            encoding="utf-8",
        )
        after = audit.verify()

        print(f"BEFORE_TAMPER valid={before.valid} events={before.event_count}")
        print(f"AFTER_TAMPER valid={after.valid} error={after.error}")
        return 0 if before.valid and not after.valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
