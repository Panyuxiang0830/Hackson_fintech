"""Integration CLI. Does not rebuild or download Part A data implicitly."""

from __future__ import annotations

import argparse
import json
import math
import os
import time
from pathlib import Path

from dotenv import load_dotenv
from qdrant_client import QdrantClient

from contextledger.retrieval.filtered_index import migrate
from contextledger.access.identity_store import IdentityStore
from contextledger.application.service import validate_security_path


def main(argv=None):
    load_dotenv(os.getenv("CONTEXTLEDGER_ENV_FILE") or None)
    parser = argparse.ArgumentParser(description="ContextLedger unified integration")
    parser.add_argument("--out", type=Path, default=Path("runtime/part_a"))
    parser.add_argument("--security-dir", type=Path, default=Path(os.getenv("SECURITY_DIR", "runtime/security")))
    commands = parser.add_subparsers(dest="command", required=True)
    index = commands.add_parser("index", help="publish a filterable Qdrant snapshot")
    index.add_argument("--reuse-part-a-embeddings", action="store_true")
    index.add_argument("--batch-size", type=int, default=128)
    serve = commands.add_parser("serve")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=7860)
    serve.add_argument("--demo", action="store_true", help="explicit isolated loopback-only demo, not production authentication")
    demo = commands.add_parser("demo-init", help="initialize an empty isolated demo security directory")
    demo.add_argument("--bind", action="append", required=True, metavar="CORPUS=PRINCIPAL_ID")
    user = commands.add_parser("user", help="operator-only account bootstrap by exact issuer/sub")
    user.add_argument("--issuer", required=True)
    user.add_argument("--subject", required=True)
    user.add_argument("--name", required=True)
    user.add_argument("--role", choices=["member", "admin", "compliance"], default="member")
    user.add_argument("--bind", action="append", default=[], metavar="CORPUS=PRINCIPAL_ID")
    upsert = commands.add_parser("upsert", help="submit a document and wait for automatic index publication")
    upsert.add_argument("--file", type=Path, required=True)
    upsert.add_argument("--admin-id", required=True)
    upsert.add_argument("--timeout", type=float, default=120)
    status = commands.add_parser("update-status", help="inspect a durable document update")
    status.add_argument("--job", required=True)
    status.add_argument("--admin-id", required=True)
    retry = commands.add_parser("retry-update", help="retry a failed update and wait for publication")
    retry.add_argument("--job", required=True)
    retry.add_argument("--admin-id", required=True)
    worker = commands.add_parser("updates-worker", help="recover and process persistent update jobs")
    worker.add_argument("--once", action="store_true")
    args = parser.parse_args(argv)
    validate_security_path(args.out, args.security_dir)
    db_path = args.out / "canonical.sqlite"
    if not db_path.is_file():
        parser.error(f"Missing canonical database: {db_path}; import Part A first")
    if args.command == "index":
        if args.batch_size < 1 or args.batch_size > 1024:
            parser.error("batch size must be 1..1024")
        client = QdrantClient(url=os.getenv("QDRANT_URL", "http://127.0.0.1:6335"),
                              api_key=os.getenv("QDRANT_API_KEY") or None, timeout=120)
        print(json.dumps(migrate(db_path, client, batch_size=args.batch_size,
                                reuse_embeddings=args.reuse_part_a_embeddings), indent=2))
    elif args.command in {"upsert", "update-status", "retry-update", "updates-worker"}:
        from contextledger.audit.store import AuditStore
        from contextledger.storage.document_updates import DocumentUpdates
        from contextledger.retrieval.filtered_index import FilteredIndex
        if args.command == "upsert" and (not math.isfinite(args.timeout) or args.timeout <= 0 or args.timeout > 3600):
            parser.error("timeout must be between 0 and 3600 seconds")
        identities = IdentityStore(args.security_dir / "identities.sqlite")
        client = QdrantClient(url=os.getenv("QDRANT_URL", "http://127.0.0.1:6335"),
                              api_key=os.getenv("QDRANT_API_KEY") or None, timeout=120)
        updates = DocumentUpdates(FilteredIndex(db_path, client, identities), identities,
            AuditStore(args.security_dir / "audit.sqlite"), autostart=args.command in {"upsert", "retry-update"})
        try:
            if args.command == "updates-worker":
                if args.once:
                    updates.process_one()
                else:
                    updates.start()
                    while True:
                        time.sleep(1)
                return 0
            if args.command == "update-status":
                result = updates.status(args.admin_id, args.job)
            else:
                job = (updates.submit(args.admin_id, json.loads(args.file.read_text(encoding="utf-8")))
                       if args.command == "upsert" else updates.retry(args.admin_id, args.job))
                updates.start()
                result = updates.wait(args.admin_id, job["id"], getattr(args, "timeout", 120))
            print(json.dumps(result, ensure_ascii=False))
            return 0 if result["state"] == "ready" else 1
        finally:
            updates.close()
    elif args.command == "demo-init":
        from contextledger.access.demo_identity import initialize_demo
        try:
            bindings = [tuple(binding.split("=", 1)) for binding in args.bind]
            if any(len(binding) != 2 for binding in bindings):
                raise ValueError("Use CORPUS=PRINCIPAL_ID")
            roster = initialize_demo(db_path, args.security_dir, bindings)
        except ValueError as error:
            parser.error(str(error))
        print(json.dumps({"demo_mode": True, "accounts": len(roster["accounts"]),
                          "security_dir": str(args.security_dir), "permissions_reset": False}, ensure_ascii=False))
    elif args.command == "user":
        from contextledger.storage.store import connect
        identities = IdentityStore(args.security_dir / "identities.sqlite")
        bindings = []
        with connect(db_path) as db:
            for binding in args.bind:
                corpus, principal = binding.split("=", 1)
                if not db.execute("SELECT 1 FROM principals WHERE corpus=? AND principal_id=?", (corpus, principal)).fetchone():
                    parser.error("binding does not match a source principal")
                bindings.append((corpus, principal))
        actor = identities.register(args.issuer, args.subject, args.name)
        identities.update(actor.id, role=args.role)
        for corpus, principal in bindings:
            identities.bind(actor.id, corpus, principal, True)
        print(json.dumps({"id": actor.id, "role": args.role, "bindings": bindings}, ensure_ascii=False))
    else:
        from contextledger.interfaces.web import create_app
        from contextledger.access.demo_identity import require_loopback_bind
        demo_mode = args.demo or os.getenv("DEMO_MODE", "false").lower() in {"1", "true", "yes"}
        if demo_mode:
            require_loopback_bind(args.host)
        app = create_app(db_path, args.security_dir, config={"DEMO_MODE": demo_mode})
        app.run(host=args.host, port=args.port, debug=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
