"""Explicit, isolated demonstration identities. This is NOT authentication.

Only an operator can initialize a fresh security directory. Reopening a roster
never restores bindings, roles, account status, or local denials changed in the UI.
"""

from __future__ import annotations

import json
from pathlib import Path

from contextledger.audit_store import AuditStore
from contextledger.identity_store import IdentityStore
from contextledger.store import connect
from contextledger.unified_service import timestamp, validate_security_path

DEMO_ISSUER = "urn:contextledger:isolated-demo"
MARKER = "demo-roster.json"
LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}


def require_loopback_bind(host: str):
    # Do not resolve arbitrary hostnames or trust a reverse-proxy header.
    if host not in {"127.0.0.1", "::1"}:
        raise ValueError("Demo mode must bind explicitly to 127.0.0.1 or ::1")


def load_roster(db_path: Path, security_dir: Path, identities: IdentityStore) -> dict:
    directory = Path(security_dir)
    try:
        roster = json.loads((directory / MARKER).read_text(encoding="utf-8"))
        accounts = roster["accounts"]
        ids = {item["id"] for item in accounts}
        valid = (roster["schema_version"] == 1 and roster["demo_mode"] is True
                 and roster["canonical_path"] == str(Path(db_path).resolve())
                 and len(accounts) == 7 and len(ids) == 7
                 and sum(item["subject"] == "administrator" for item in accounts) == 1)
        people = identities.users()
        valid = valid and {item["id"] for item in people} == ids
        by_id = {item["id"]: item for item in people}
        valid = valid and all(by_id[item["id"]]["issuer"] == DEMO_ISSUER
                              and by_id[item["id"]]["subject"] == item["subject"] for item in accounts)
        valid = valid and identities.path.resolve() == (directory / "identities.sqlite").resolve()
        if directory.is_symlink() or not valid:
            raise ValueError("not an isolated demo roster")
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise ValueError("Demo mode requires a separately initialized, intact demo security directory") from error
    return roster


def initialize_demo(db_path: Path, security_dir: Path, bindings: list[tuple[str, str]]) -> dict:
    db_path, security_dir = Path(db_path), Path(security_dir)
    validate_security_path(db_path.parent, security_dir)
    if len(bindings) != 6 or len(set(bindings)) != 6:
        raise ValueError("Exactly six distinct CORPUS=PRINCIPAL_ID bindings are required")
    sources = []
    with connect(db_path) as db:
        for corpus, principal in bindings:
            row = db.execute("SELECT * FROM principals WHERE corpus=? AND principal_id=?",
                             (corpus, principal)).fetchone()
            if row is None or (corpus == "orgforge" and (
                    row["active_from"] is not None and row["active_from"] > 60
                    or row["active_until"] is not None and row["active_until"] < 60)):
                raise ValueError("Demo employee binding must refer to an existing currently active source identity")
            sources.append({"corpus": corpus, "principal_id": principal,
                            "name": row["name"], "department": row["dept"]})
    requested = [{"corpus": corpus, "principal_id": principal} for corpus, principal in bindings]
    marker = security_dir / MARKER
    if marker.exists():
        identities = IdentityStore(security_dir / "identities.sqlite")
        roster = load_roster(db_path, security_dir, identities)
        if roster["initial_bindings"] != requested:
            raise ValueError("Existing demo roster differs; use a new empty demo directory")
        return roster  # Never re-enable revoked permissions on initialization/restart.
    if security_dir.is_symlink() or (security_dir.exists() and any(security_dir.iterdir())):
        raise ValueError("Refusing to initialize demo identities in an existing security directory")
    security_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
    identities = IdentityStore(security_dir / "identities.sqlite")
    administrator = identities.register(DEMO_ISSUER, "administrator", "ContextLedger 管理员")
    identities.update(administrator.id, role="admin")
    accounts = [{"id": administrator.id, "subject": "administrator", "source": None}]
    for index, source in enumerate(sources, 1):
        subject = f"employee-{index:02d}"
        employee = identities.register(DEMO_ISSUER, subject, f"{source['name']}（演示员工）")
        identities.update(employee.id, department=source["department"])
        identities.bind(employee.id, source["corpus"], source["principal_id"], True)
        accounts.append({"id": employee.id, "subject": subject, "source": source})
    AuditStore(security_dir / "audit.sqlite").append({
        "event_type": "demo_provisioned", "user_id": "operator", "timestamp": timestamp(),
        "identity_mode": "isolated_demo", "decision": "allowed", "account_count": 7,
        "initial_bindings": requested, "retrieved_document_ids": [],
    })
    roster = {"schema_version": 1, "demo_mode": True, "canonical_path": str(db_path.resolve()),
              "initial_bindings": requested, "accounts": accounts}
    with marker.open("x", encoding="utf-8") as file:
        json.dump(roster, file, ensure_ascii=False, indent=2)
    return roster
