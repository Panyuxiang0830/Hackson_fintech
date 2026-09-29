from __future__ import annotations

from dataclasses import replace
from threading import RLock

from .models import User


class IdentityService:
    """Mutable demo identity store resolved at request time."""

    def __init__(self, users: dict[str, User] | None = None) -> None:
        self._baseline = dict(users or {})
        self._users = dict(users or {})
        self._lock = RLock()

    def list_users(self) -> dict[str, User]:
        with self._lock:
            return dict(self._users)

    def get(self, user_id: str) -> User:
        with self._lock:
            try:
                return self._users[user_id]
            except KeyError as error:
                raise KeyError(f"unknown user: {user_id}") from error

    def resolve(self, user: User | str) -> User:
        user_id = user if isinstance(user, str) else user.id
        with self._lock:
            if user_id in self._users:
                return self._users[user_id]
        if isinstance(user, User):
            return user
        raise KeyError(f"unknown user: {user_id}")

    def revoke_project(self, user_id: str, project: str) -> User:
        with self._lock:
            user = self.get(user_id)
            projects = tuple(item for item in user.projects if item != project)
            updated = replace(user, projects=projects)
            self._users[user_id] = updated
            return updated

    def reset(self, user_id: str) -> User:
        with self._lock:
            try:
                restored = self._baseline[user_id]
            except KeyError as error:
                raise KeyError(f"unknown user: {user_id}") from error
            self._users[user_id] = restored
            return restored

