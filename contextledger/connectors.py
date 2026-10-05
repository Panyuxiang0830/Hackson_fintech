"""Load OrgForge and EnterpriseRAG-Bench into a common source record.

The two corpora are different companies (Apex Athletics and Redwood Inference).
Callers keep them apart with the corpus field.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pyarrow.parquet as pq
from huggingface_hub import hf_hub_download

from contextledger.models import SourceDoc

ORG_REPO = "aeriesec/orgforge"
ERAG_REPO = "onyx-dot-app/EnterpriseRAG-Bench"
ORG_ARTIFACT_SOURCES = ("confluence", "jira", "slack")
ERAG_SOURCES = ("confluence", "jira", "slack", "google_drive")


def hub_file(repo: str, filename: str) -> Path:
    return Path(hf_hub_download(repo, filename, repo_type="dataset"))


def parse_json_list(value) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    text = str(value).strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return [text]
    if isinstance(parsed, list):
        return [str(item) for item in parsed]
    return [str(parsed)]


def load_orgforge_questions(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def load_orgforge_snapshot(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def iter_orgforge(parquet_path: Path, limit: int | None = None) -> list[SourceDoc]:
    table = pq.read_table(
        parquet_path,
        columns=[
            "doc_id",
            "doc_type",
            "category",
            "title",
            "body",
            "day",
            "date",
            "timestamp",
            "actors",
            "dept",
            "tags",
            "artifact_ids",
            "is_incident",
            "is_external",
        ],
    )
    docs: list[SourceDoc] = []
    seen = Counter()
    for row in table.to_pylist():
        if row.get("category") != "artifact":
            continue
        source = row.get("doc_type") or ""
        if source not in ORG_ARTIFACT_SOURCES:
            continue
        if limit is not None and seen[source] >= limit:
            continue
        seen[source] += 1
        day = row.get("day")
        docs.append(
            SourceDoc(
                corpus="orgforge",
                doc_id=str(row["doc_id"]),
                source=source,
                title=(row.get("title") or "").strip(),
                text=row.get("body") or "",
                day=int(day) if day is not None else None,
                ts=row.get("timestamp") or None,
                dept=(row.get("dept") or "").strip(),
                actors=parse_json_list(row.get("actors")),
                extra={
                    "date": row.get("date"),
                    "tags": parse_json_list(row.get("tags")),
                    "artifact_ids": row.get("artifact_ids") or "",
                    "is_incident": bool(row.get("is_incident")),
                    "is_external": bool(row.get("is_external")),
                },
                raw={
                    "doc_id": row.get("doc_id"),
                    "doc_type": source,
                    "title": row.get("title"),
                    "body": row.get("body"),
                    "day": day,
                    "timestamp": row.get("timestamp"),
                    "actors": row.get("actors"),
                    "dept": row.get("dept"),
                },
            )
        )
    return docs


def _even_indices(count: int, limit: int) -> set[int]:
    if limit <= 0 or limit >= count:
        return set(range(count))
    if limit == 1:
        return {0}
    step = (count - 1) / (limit - 1)
    return {min(count - 1, int(round(i * step))) for i in range(limit)}


def iter_enterpriserag(
    parquet_path: Path,
    slack_limit: int | None,
    limit: int | None = None,
) -> list[SourceDoc]:
    """Read the four Aspire sources.

    slack_limit samples Slack threads evenly across the file. None keeps every
    Slack thread. The other three sources are read in full unless limit is set.
    """
    table = pq.read_table(parquet_path, columns=["doc_id", "source_type", "title", "content"])
    sources = table.column("source_type").to_pylist()
    slack_positions = [i for i, source in enumerate(sources) if source == "slack"]
    keep_slack = _even_indices(len(slack_positions), slack_limit if slack_limit is not None else len(slack_positions))
    slack_keep_rows = {slack_positions[i] for i in keep_slack}

    docs: list[SourceDoc] = []
    seen = Counter()
    ids = table.column("doc_id").to_pylist()
    titles = table.column("title").to_pylist()
    contents = table.column("content").to_pylist()
    for row_index, source in enumerate(sources):
        if source not in ERAG_SOURCES:
            continue
        if source == "slack" and row_index not in slack_keep_rows:
            continue
        if limit is not None and seen[source] >= limit:
            continue
        seen[source] += 1
        doc_id = str(ids[row_index])
        title = (titles[row_index] or "").strip()
        text = contents[row_index] or ""
        docs.append(
            SourceDoc(
                corpus="enterpriserag",
                doc_id=doc_id,
                source=source,
                title=title,
                text=text,
                day=None,
                ts=None,
                dept="",
                actors=[],
                extra={},
                raw={"doc_id": doc_id, "source_type": source, "title": title, "content": text},
            )
        )
    return docs
