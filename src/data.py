from __future__ import annotations

import json
from pathlib import Path

from .models import Document, User


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load_json(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_users(path: Path | None = None) -> dict[str, User]:
    source = path or PROJECT_ROOT / "data" / "users.json"
    users = [User.from_dict(item) for item in _load_json(source)]
    return {user.id: user for user in users}


def load_documents(path: Path | None = None) -> list[Document]:
    source = path or PROJECT_ROOT / "data" / "documents.json"
    return [Document.from_dict(item) for item in _load_json(source)]

