"""Operator smoke test of actual Part A data and the running Qdrant backend.

Temporary test identities are isolated from the deployed login/permissions DB.
This is a smoke test, NOT the full REQ-018 quality/scale benchmark.
"""

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qdrant_client import QdrantClient
from contextledger.audit_store import AuditStore
from contextledger.filtered_index import FilteredIndex
from contextledger.identity_store import IdentityStore
from contextledger.unified_service import UnifiedService
from src.answering import AnswerService


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--corpus", default="orgforge")
    parser.add_argument("--principal", default="orgforge:Jax")
    parser.add_argument("--query", default="TitanDB")
    args = parser.parse_args()
    client = QdrantClient(url=os.getenv("QDRANT_URL", "http://127.0.0.1:6335"), timeout=120)
    with tempfile.TemporaryDirectory(prefix="contextledger-verify-") as temporary:
        identities = IdentityStore(Path(temporary) / "identities.sqlite")
        actor = identities.register("https://isolated-test-issuer.invalid", "test-subject", "Isolated smoke test")
        identities.bind(actor.id, args.corpus, args.principal, True)
        answer = AnswerService()
        answer.provider = "mock"
        index = FilteredIndex(args.out / "canonical.sqlite", client, identities)
        audit = AuditStore(Path(temporary) / "audit.sqlite")
        service = UnifiedService(index, identities, audit, answer)
        report = {"modes": {}, "uses_real_qdrant": True, "uses_real_embedding": True,
                  "login_provider_test": "separate OIDC protocol tests; no production provider configured"}
        for mode in ("keyword", "vector", "hybrid"):
            result, _ = service.search(actor.id, args.corpus, args.query, mode)
            if not result["hits"]:
                raise AssertionError(f"No visible evidence for configured smoke case: {mode}")
            report["modes"][mode] = len(result["hits"])
        answered, _ = service.ask(actor.id, args.corpus, args.query)
        assert answered["provider"] == "mock" and answered["evidence"]
        opened_id = answered["evidence"][0]["doc_id"]
        assert service.open(actor.id, args.corpus, opened_id)[0]["available"]
        identities.bind(actor.id, args.corpus, args.principal, False)
        for mode in ("keyword", "vector", "hybrid"):
            assert service.search(actor.id, args.corpus, args.query, mode)[0]["hits"] == []
        assert not service.open(actor.id, args.corpus, opened_id)[0]["available"]
        assert service.ask(actor.id, args.corpus, args.query)[0]["decision"] == "insufficient"
        report.update(revocation_passed=True, answer_citations=len(answered["evidence"]), audit_valid=audit.verify().valid)
        print(json.dumps(report, ensure_ascii=False, indent=2))
    client.close()


if __name__ == "__main__":
    main()
