"""Serialize publishers sharing a canonical database on a local filesystem."""

from contextlib import contextmanager
import fcntl
from pathlib import Path


@contextmanager
def index_lock(db_path, *, blocking=True):
    path = Path(db_path).resolve().parent / ".canonical-index.lock"
    with path.open("a") as handle:
        flags = fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB)
        fcntl.flock(handle, flags)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)
