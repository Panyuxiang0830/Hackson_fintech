"""Source time provenance; never infer an operation time or a missing timezone."""
from __future__ import annotations

import re
from datetime import date, datetime, timezone


def parsed_time(value):
    if not isinstance(value, str):
        return None
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            return "day", date.fromisoformat(value)
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2})?", value):
            return None
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return ("offset_timestamp" if moment.tzinfo else "local_timestamp"), moment
    except ValueError:
        return None


def source_timing(hit):
    meta = hit["metadata"]
    fields = {"ts": hit.get("ts"), "event_time": meta.get("event_time"),
              "date": meta.get("date"), "source_date": meta.get("source_date"),
              "day": hit.get("day"), "source_day": meta.get("source_day"),
              "source_timestamp": meta.get("source_timestamp"), "timestamp": meta.get("timestamp")}
    fields = {key: value for key, value in fields.items() if value is not None}
    # A native final-state snapshot has no known state transition time. Its parent
    # creation date and snapshot observation time must not fill that gap.
    candidates = [] if meta.get("record_type") == "native_state" else [
        ("ts", hit.get("ts")), ("metadata.event_time", meta.get("event_time")),
        ("metadata.source_timestamp", meta.get("source_timestamp")),
        ("metadata.timestamp", meta.get("timestamp")),
        ("metadata.date", meta.get("date")), ("metadata.source_date", meta.get("source_date"))]
    basis, value, parsed = None, None, None
    for name, candidate in candidates:
        parsed = parsed_time(candidate)
        if parsed:
            basis, value = name, candidate
            break
    warnings = []
    if value:
        # Compare literal calendar dates, without shifting either timezone. Numeric
        # day is retained verbatim; no undocumented day-to-date origin is invented.
        for name, other in fields.items():
            other_parsed = parsed_time(other)
            if other_parsed and other[:10] != value[:10]:
                warnings.append(f"Source date differs: {name}={other}; {basis}={value}. Neither field was rewritten.")
        if parsed[0] == "local_timestamp":
            warnings.append("Timezone unspecified; this value has not been converted to SGT.")
    elif any(parsed_time(candidate) is None and candidate for _, candidate in candidates):
        warnings.append("No usable source time; original time fields are retained.")
    return {"source_record_time": value, "time_basis": basis,
            "time_precision": "day" if parsed and parsed[0] == "day" else "timestamp" if parsed else "unknown",
            "time_group": parsed[0] if parsed else "unknown", "source_time_fields": fields,
            "time_warnings": warnings}


def order_events(events):
    """Sort within comparable groups only, placing unknown times last."""
    groups = {"offset_timestamp": 0, "local_timestamp": 1, "day": 2, "unknown": 3}
    def key(event):
        parsed = parsed_time(event.get("source_record_time"))
        group, moment = parsed if parsed else ("unknown", "")
        if group == "offset_timestamp":
            moment = moment.astimezone(timezone.utc)
        return groups[group], moment, event["citation_id"]
    ordered = sorted(events, key=key)
    present = list(dict.fromkeys(event["time_group"] for event in ordered))
    return ordered, {"basis": "source_record_time", "groups": present,
        "note": "Source record times order records within comparable groups; timezone-unspecified values share only the source's local clock. Different time bases and unknown times are grouped separately. Record order does not establish actual operation order or causation."}


def model_event(event):
    """Keep time evidence without repeating raw values and long UI warnings per row."""
    result = {key: event[key] for key in ("citation_id", "type", "time_group")}
    for key in ("event_time", "source_record_time", "time_basis", "historical"):
        if event.get(key) is not None and event.get(key) is not False:
            result[key] = event[key]
    fields = {key: value for key, value in event["source_time_fields"].items()
              if value != event.get("source_record_time") and value != event.get("event_time")}
    if fields:
        result["source_time_fields"] = fields
    if any(warning.startswith("Source date differs:") for warning in event["time_warnings"]):
        result["time_warnings"] = ["source_date_mismatch"]
    return result
