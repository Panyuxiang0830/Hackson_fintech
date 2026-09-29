from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from .models import Document, User


LAST_DAYS_RE = re.compile(r"(?:last|past|最近|过去)\s*(\d+)\s*(?:days?|天)", re.IGNORECASE)
REQUEST_ID_RE = re.compile(r"\b[0-9a-f]{8}-[0-9a-f-]{27,}\b", re.IGNORECASE)


class AuditQueryParser:
    """Small deterministic parser for the MVP audit inquiry examples."""

    def parse(
        self,
        query: str,
        users: dict[str, User],
        documents: list[Document],
    ) -> dict[str, str | None]:
        lowered = query.lower()
        user_id = next(
            (
                user.id
                for user in users.values()
                if user.id.lower() in lowered or user.name.lower() in lowered
            ),
            None,
        )
        document_id = next(
            (document.id for document in documents if document.id.lower() in lowered),
            None,
        )
        request_match = REQUEST_ID_RE.search(query)
        days_match = LAST_DAYS_RE.search(query)
        start = None
        if days_match:
            start = (datetime.now(timezone.utc) - timedelta(days=int(days_match.group(1)))).isoformat()

        return {
            "user_id": user_id,
            "request_id": request_match.group(0) if request_match else None,
            "document_id": document_id,
            "start": start,
            "end": None,
        }
