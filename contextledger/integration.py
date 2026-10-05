"""Integration CLI. Does not rebuild or download Part A data implicitly."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from qdrant_client import QdrantClient

from contextledger.filtered_index import migrate
from contextledger.identity_store import IdentityStore
from contextledger.unified_service import validate_security_path


def main(argv=None):
    load_dotenv()
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
    user = commands.add_parser("user", help="operator-only account bootstrap by exact issuer/sub")
    user.add_argument("--issuer", required=True)
    user.add_argument("--subject", required=True)
    user.add_argument("--name", required=True)
    user.add_argument("--role", choices=["member", "admin", "compliance"], default="member")
    user.add_argument("--bind", action="append", default=[], metavar="CORPUS=PRINCIPAL_ID")
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
    elif args.command == "user":
        from contextledger.store import connect
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
        from contextledger.web import create_app
        app = create_app(db_path, args.security_dir)
        app.run(host=args.host, port=args.port, debug=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
