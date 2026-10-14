"""Reserved adapter. No live provider checks are enabled in this integration."""


class SourcePermissionAdapter:
    def check(self, source: str, resource_id: str, principal_id: str) -> dict:
        return {"source": source, "resource_id": resource_id, "status": "not_enabled",
                "permission_revision": None, "checked_at": None, "cursor": None,
                "reason": "Only imported ACL snapshots and system-local restrictions are enforced."}

    def sync(self, source: str, cursor=None) -> dict:
        return {"source": source, "status": "not_enabled", "cursor": cursor,
                "checked_at": None, "permission_revision": None}
