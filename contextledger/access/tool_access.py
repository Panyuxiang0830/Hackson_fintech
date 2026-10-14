"""Operator-issued personal tool tokens; hashes only, never model-chosen identity."""
from __future__ import annotations

import hashlib
import secrets
import sqlite3
import time
import uuid
from pathlib import Path

CAPABILITIES = frozenset({"search", "fetch", "ask", "audit"})


class ToolAccess:
    def __init__(self, path: Path, identities):
        self.path, self.identities = Path(path), identities
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.path.is_symlink():
            raise ValueError("token database must not be a symlink")
        with self.db() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS tool_tokens (
                id TEXT PRIMARY KEY, digest TEXT UNIQUE NOT NULL, user_id TEXT NOT NULL,
                capabilities TEXT NOT NULL, expires_at REAL NOT NULL, revoked INTEGER NOT NULL DEFAULT 0)""")
        self.path.chmod(0o600)

    def db(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        return db

    def issue(self, user_id, capabilities=("search", "fetch"), days=30):
        actor = self.identities.get(user_id)
        if not actor or not actor.enabled:
            raise ValueError("enabled existing user required")
        if not capabilities or set(capabilities) - CAPABILITIES:
            raise ValueError("invalid tool capabilities")
        if type(days) is not int or not 1 <= days <= 90:
            raise ValueError("token lifetime must be 1..90 days")
        token_id, secret = uuid.uuid4().hex, secrets.token_urlsafe(32)
        token = "clt_" + token_id + "." + secret
        with self.db() as db:
            db.execute("INSERT INTO tool_tokens VALUES (?,?,?,?,?,0)",
                (token_id, hashlib.sha256(token.encode()).hexdigest(), user_id,
                 ",".join(sorted(set(capabilities))), time.time() + days * 86400))
        return token_id, token  # Returned once, only to the trusted local operator.

    def revoke(self, token_id):
        with self.db() as db:
            db.execute("UPDATE tool_tokens SET revoked=1 WHERE id=?", (token_id,))

    def resolve(self, token, capability):
        if capability not in CAPABILITIES or not isinstance(token, str) or not 40 <= len(token) <= 200:
            raise PermissionError("tool credential required")
        digest = hashlib.sha256(token.encode()).hexdigest()
        with self.db() as db:
            row = db.execute("SELECT * FROM tool_tokens WHERE digest=?", (digest,)).fetchone()
        if not row or row["revoked"] or row["expires_at"] <= time.time() or capability not in row["capabilities"].split(","):
            raise PermissionError("tool credential unavailable")
        actor = self.identities.get(row["user_id"])
        if not actor or not actor.enabled:
            raise PermissionError("tool account unavailable")
        return actor
