"""Legacy UI check hook; opt-in live reads use source_adapters/source_sync.

This hook does not perform network calls or advertise a source as synced.
"""
import time


class SourcePermissionAdapter:
    def __init__(self, identities=None):
        self.identities = identities

    def check(self, source: str, resource_id: str, principal_id: str) -> dict:
        return {"source": source, "resource_id": resource_id, "status": "not_enabled",
                "permission_revision": None, "checked_at": None, "cursor": None,
                "reason": "Only imported ACL snapshots and system-local restrictions are enforced."}

    def sync(self, source: str, cursor=None) -> dict:
        if self.identities is not None:
            with self.identities.db() as db:
                if db.execute("SELECT 1 FROM sqlite_master WHERE name='live_source_guards'").fetchone():
                    rows = [dict(r) for r in db.execute("SELECT corpus,state,expires_at FROM live_source_guards WHERE source=?", (source,))]
                    if rows:
                        valid = all(r["state"] == "ready" and r["expires_at"] > time.time() for r in rows)
                        return {"source": source, "status": "snapshot_ready" if valid else "snapshot_unavailable",
                            "snapshots": rows, "cursor": None, "checked_at": None, "permission_revision": None,
                            "real_time_revocation": False, "reason": "Observed bounded source permission snapshots; not live platform revocation."}
        return {"source": source, "status": "not_enabled", "cursor": cursor,
                "checked_at": None, "permission_revision": None}
