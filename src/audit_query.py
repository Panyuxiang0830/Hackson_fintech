from __future__ import annotations

import re
from calendar import monthrange
from datetime import datetime, timedelta, timezone

from .models import Document, User


RELATIVE_TIME_RE = re.compile(
    r"(?:last|past|最近|过去|近)\s*(?P<number>[0-9]{1,5}|[零〇一二两三四五六七八九十百]{1,5}|a|an)"
    r"\s*(?:个\s*)?(?P<unit>days?\b|weeks?\b|months?\b|天|周|星期|月)", re.IGNORECASE)
TIME_HINT_RE = re.compile(
    r"(?:last|past|最近|过去|近)\s*[^，。？?\n]*(?:days?\b|weeks?\b|months?\b|hours?\b|years?\b|天|周|星期|月|季度|小时|分钟|年)"
    r"|今天|昨天|前天|上周|本周|这周|上个?月|本月|今年|去年|today\b|yesterday\b|\d{4}[-/]\d{1,2}[-/]\d{1,2}",
    re.IGNORECASE)


def _quantity(text: str) -> int:
    if text.isascii() and text.isdigit():
        return int(text)
    if text.lower() in {"a", "an"}:
        return 1
    digits = {ch: n for n, ch in enumerate("零一二三四五六七八九")}
    digits.update({"〇": 0, "两": 2})
    if len(text) == 1 and text in digits:
        return digits[text]
    if re.fullmatch(r"[一二两三四五六七八九]?十[一二三四五六七八九]?", text):
        before, after = text.split("十")
        return (digits[before] if before else 1) * 10 + (digits[after] if after else 0)
    if text in {"一百", "百"}:
        return 100
    raise ValueError("Unsupported audit time quantity; use an explicit number.")


def time_bounds(query: str, now: datetime) -> tuple[str | None, str | None]:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Audit reference time must contain a timezone.")
    now = now.astimezone(timezone.utc)
    matches = list(RELATIVE_TIME_RE.finditer(query))
    calendar_days = re.findall(r"今天|昨天|\btoday\b|\byesterday\b", query, re.IGNORECASE)
    if len(matches) + len(calendar_days) > 1:
        raise ValueError("Multiple audit time conditions; provide one explicit range.")
    if matches:
        match = matches[0]
        # Reject another unsupported time constraint instead of ignoring it.
        remainder = query[:match.start()] + query[match.end():]
        if TIME_HINT_RE.search(remainder):
            raise ValueError("Unsupported audit time condition; provide explicit start/end.")
        count = _quantity(match['number'])
        unit = match['unit'].lower()
        try:
            if unit in {"月", "month", "months"}:
                if not 1 <= count <= 120:
                    raise ValueError("Audit month quantity must be between 1 and 120.")
                month_index = now.year * 12 + now.month - 1 - count
                year, month_zero = divmod(month_index, 12)
                month = month_zero + 1
                start = now.replace(year=year, month=month,
                                    day=min(now.day, monthrange(year, month)[1]))
            else:
                days = count * (7 if unit in {"周", "星期", "week", "weeks"} else 1)
                if not 1 <= days <= 3650:
                    raise ValueError("Audit time quantity must span 1 to 3650 days.")
                start = now - timedelta(days=days)
        except OverflowError as error:
            raise ValueError("Audit time range is outside supported dates.") from error
        return start.isoformat(), now.isoformat()
    if calendar_days:
        term = calendar_days[0].lower()
        remainder = re.sub(r"今天|昨天|\btoday\b|\byesterday\b", "", query, flags=re.IGNORECASE)
        if TIME_HINT_RE.search(remainder):
            raise ValueError("Unsupported audit time condition; provide explicit start/end.")
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        if term in {"昨天", "yesterday"}:
            return (midnight - timedelta(days=1)).isoformat(), (midnight - timedelta(microseconds=1)).isoformat()
        return midnight.isoformat(), now.isoformat()
    if TIME_HINT_RE.search(query):
        raise ValueError("Unsupported audit time condition; use past N days/weeks/months or explicit start/end.")
    return None, None


REQUEST_ID_RE = re.compile(r"\b[0-9a-f]{8}-[0-9a-f-]{27,}\b", re.IGNORECASE)


class AuditQueryParser:
    """Small deterministic parser for the MVP audit inquiry examples."""

    def parse(
        self,
        query: str,
        users: dict[str, User],
        documents: list[Document],
        *, now: datetime | None = None, parse_time: bool = True,
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
        start, end = (None, None)
        if parse_time:
            start, end = time_bounds(query, now if now is not None else datetime.now(timezone.utc))

        return {
            "user_id": user_id,
            "request_id": request_match.group(0) if request_match else None,
            "document_id": document_id,
            "start": start,
            "end": end,
        }
