"""Persistent app identities. Source ACL bindings are explicit operator decisions."""

from __future__ import annotations

import json
import secrets
import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

ROLES = {"member", "admin", "compliance"}
RULE_KINDS = {"corpus", "source", "project", "department", "document"}


@dataclass(frozen=True)
class Actor:
    id: str
    name: str
    role: str
    enabled: bool
    epoch: int
    department: str
    groups: tuple[str, ...]
    projects: tuple[str, ...]
    clearance: int


class IdentityStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self.db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY, issuer TEXT NOT NULL, subject TEXT NOT NULL,
                    name TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'member',
                    enabled INTEGER NOT NULL DEFAULT 1, epoch INTEGER NOT NULL DEFAULT 1,
                    department TEXT NOT NULL DEFAULT '', groups_json TEXT NOT NULL DEFAULT '[]',
                    projects_json TEXT NOT NULL DEFAULT '[]', clearance INTEGER NOT NULL DEFAULT 1,
                    UNIQUE (issuer, subject)
                );
                CREATE TABLE IF NOT EXISTS bindings (
                    user_id TEXT NOT NULL REFERENCES users(id), corpus TEXT NOT NULL,
                    principal_id TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1,
                    PRIMARY KEY (user_id, corpus, principal_id)
                );
                CREATE TABLE IF NOT EXISTS restrictions (
                    user_id TEXT NOT NULL REFERENCES users(id), corpus TEXT NOT NULL,
                    kind TEXT NOT NULL, value TEXT NOT NULL,
                    PRIMARY KEY (user_id, corpus, kind, value)
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
                    expires_at REAL NOT NULL
                );
            """)

    def db(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA foreign_keys=ON")
        return db

    @staticmethod
    def actor(row) -> Actor | None:
        if row is None:
            return None
        return Actor(row["id"], row["name"], row["role"], bool(row["enabled"]),
                     row["epoch"], row["department"], tuple(json.loads(row["groups_json"])),
                     tuple(json.loads(row["projects_json"])), row["clearance"])

    def get(self, user_id: str) -> Actor | None:
        with self.db() as db:
            return self.actor(db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone())

    def login_identity(self, user_id: str):
        with self.db() as db:
            row = db.execute("SELECT issuer,subject FROM users WHERE id=?", (user_id,)).fetchone()
            return dict(row) if row else None

    def register(self, issuer: str, subject: str, name: str) -> Actor:
        if not issuer or not subject:
            raise ValueError("issuer and subject are required")
        with self.db() as db:
            db.execute("INSERT OR IGNORE INTO users (id,issuer,subject,name) VALUES (?,?,?,?)",
                       (str(uuid.uuid4()), issuer, subject, name[:200] or subject[:200]))
            return self.actor(db.execute("SELECT * FROM users WHERE issuer=? AND subject=?",
                                         (issuer, subject)).fetchone())

    def users(self) -> list[dict]:
        with self.db() as db:
            people = []
            for row in db.execute("SELECT * FROM users ORDER BY name"):
                item = dict(row)
                item.pop("groups_json")
                item.pop("projects_json")
                item["bindings"] = [dict(r) for r in db.execute(
                    "SELECT corpus,principal_id,enabled FROM bindings WHERE user_id=?", (row["id"],))]
                item["restrictions"] = [dict(r) for r in db.execute(
                    "SELECT corpus,kind,value FROM restrictions WHERE user_id=?", (row["id"],))]
                people.append(item)
            return people

    def update(self, user_id: str, *, role=None, enabled=None, department=None,
               groups=None, projects=None, clearance=None):
        if role is not None and role not in ROLES:
            raise ValueError("invalid app role")
        if enabled is not None and type(enabled) is not bool:
            raise ValueError("enabled must be boolean")
        if clearance is not None and (type(clearance) is not int or not 0 <= clearance <= 3):
            raise ValueError("clearance must be 0..3")
        if department is not None and not isinstance(department, str):
            raise ValueError("department must be a string")
        updates = {}
        for key, value in (("role", role), ("enabled", enabled), ("department", department),
                           ("clearance", clearance)):
            if value is not None:
                updates[key] = value
        for key, value in (("groups_json", groups), ("projects_json", projects)):
            if value is not None:
                if not isinstance(value, list) or any(not isinstance(v, str) for v in value):
                    raise ValueError("groups/projects must be string lists")
                updates[key] = json.dumps(value)
        if not updates:
            raise ValueError("empty change")
        with self.db() as db:
            assignments = ",".join(f"{key}=?" for key in updates)
            changed = db.execute(f"UPDATE users SET {assignments},epoch=epoch+1 WHERE id=?",
                                 (*updates.values(), user_id)).rowcount
            if not changed:
                raise ValueError("unknown user")

    def bind(self, user_id: str, corpus: str, principal_id: str, enabled: bool):
        if type(enabled) is not bool:
            raise ValueError("enabled must be boolean")
        with self.db() as db:
            db.execute("""INSERT INTO bindings VALUES (?,?,?,?) ON CONFLICT
                (user_id,corpus,principal_id) DO UPDATE SET enabled=excluded.enabled""",
                       (user_id, corpus, principal_id, enabled))
            db.execute("UPDATE users SET epoch=epoch+1 WHERE id=?", (user_id,))

    def restrict(self, user_id: str, corpus: str, kind: str, value: str, denied: bool):
        if kind not in RULE_KINDS or not isinstance(value, str) or not value or not isinstance(corpus, str) or type(denied) is not bool:
            raise ValueError("invalid restriction")
        with self.db() as db:
            if denied:
                db.execute("INSERT OR IGNORE INTO restrictions VALUES (?,?,?,?)",
                           (user_id, corpus, kind, value))
            else:
                db.execute("DELETE FROM restrictions WHERE user_id=? AND corpus=? AND kind=? AND value=?",
                           (user_id, corpus, kind, value))
            db.execute("UPDATE users SET epoch=epoch+1 WHERE id=?", (user_id,))

    def scope(self, actor: Actor, corpus: str) -> tuple[list[str], dict[str, list[str]]]:
        with self.db() as db:
            bindings = [r[0] for r in db.execute("SELECT principal_id FROM bindings WHERE user_id=? AND corpus=? AND enabled=1",
                                               (actor.id, corpus))]
            restrictions: dict[str, list[str]] = {}
            for row in db.execute("SELECT kind,value FROM restrictions WHERE user_id=? AND corpus IN (?, '*')",
                                  (actor.id, corpus)):
                restrictions.setdefault(row[0], []).append(row[1])
            return bindings, restrictions

    def new_session(self, actor: Actor, expires_at: float) -> str:
        sid = secrets.token_urlsafe(32)
        with self.db() as db:
            db.execute("DELETE FROM sessions WHERE expires_at<=?", (time.time(),))
            db.execute("INSERT INTO sessions VALUES (?,?,?)", (sid, actor.id, expires_at))
        return sid

    def session_actor(self, sid: str) -> Actor | None:
        with self.db() as db:
            row = db.execute("SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.id=? AND s.expires_at>?",
                             (sid, time.time())).fetchone()
            actor = self.actor(row)
            return actor if actor and actor.enabled else None

    def end_session(self, sid: str):
        with self.db() as db:
            db.execute("DELETE FROM sessions WHERE id=?", (sid,))
