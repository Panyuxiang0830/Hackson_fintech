from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .models import Document


@dataclass(frozen=True)
class FreshnessDecision:
    servable: bool
    status: str
    reason: str
    sync_lag_minutes: float | None


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class FreshnessService:
    """Prevents a known older indexed version from entering retrieval."""

    def __init__(self, target_window_minutes: int = 60) -> None:
        self.target_window_minutes = target_window_minutes

    def evaluate(self, document: Document) -> FreshnessDecision:
        try:
            indexed_version = _parse_timestamp(document.updated_at)
            source_version = _parse_timestamp(document.source_updated_at)
            synced_at = _parse_timestamp(document.synced_at)
        except ValueError:
            return FreshnessDecision(False, "unknown", "invalid freshness timestamp", None)

        if source_version > indexed_version:
            return FreshnessDecision(
                False,
                "stale",
                "latest known source version is newer than the indexed content",
                None,
            )

        lag_minutes = max(0.0, (synced_at - source_version).total_seconds() / 60)
        if lag_minutes > self.target_window_minutes:
            return FreshnessDecision(
                True,
                "delayed",
                f"content is current but ingestion exceeded the {self.target_window_minutes}-minute target",
                round(lag_minutes, 2),
            )

        return FreshnessDecision(
            True,
            "current",
            f"indexed version matches the source within the {self.target_window_minutes}-minute target",
            round(lag_minutes, 2),
        )
