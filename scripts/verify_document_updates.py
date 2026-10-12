"""Isolated HTTP/CLI smoke with real MiniLM and a Qdrant server; no live LLM."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["CUDA_VISIBLE_DEVICES"] = ""
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["LLM_PROVIDER"] = "mock"
os.environ["LLM_API_KEY"] = ""

import requests
from qdrant_client import QdrantClient, models as qm
from werkzeug.serving import WSGIRequestHandler, make_server

from contextledger.filtered_index import migrate
from contextledger.identity_store import IdentityStore
from contextledger.models import CanonicalDoc, Chunk, Principal
from contextledger.store import connect, content_hash, init_db, insert_documents, insert_principals
from contextledger.web import create_app


class QuietHandler(WSGIRequestHandler):
    def log_request(self, *args, **kwargs):
        pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--qdrant-url", required=True)
    parser.add_argument("--report", type=Path, default=ROOT / "runtime/freshness/automatic-update-chain/report.json")
    args = parser.parse_args()
    os.environ["QDRANT_URL"] = args.qdrant_url
    os.environ["LLM_PLANNER_ENABLED"] = "false"
    client = QdrantClient(url=args.qdrant_url, timeout=60)
    collection = None
    server = None
    app = None
    report = {"scope": "isolated synthetic documents, real HTTP and CLI, MiniLM CPU, native Qdrant server",
        "real_model_validation": "skipped_by_user", "answer_provider": "mock", "steps": [],
        "qdrant_version": requests.get(args.qdrant_url + "/", timeout=5).json()["version"],
        "implementation_sha256": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in
            ("contextledger/document_updates.py", "contextledger/index_lock.py", "contextledger/filtered_index.py", "contextledger/web.py", "contextledger/integration.py", "contextledger/vectors.py")}}
    try:
        with tempfile.TemporaryDirectory(prefix="contextledger-updates-http-") as temporary:
            directory = Path(temporary)
            db_path = directory / "content/canonical.sqlite"
            security = directory / "security"
            identities = IdentityStore(security / "identities.sqlite")
            admin = identities.register("isolated-update-test", "admin", "Administrator")
            identities.update(admin.id, role="admin")
            alice = identities.register("isolated-update-test", "alice", "Alice")
            identities.bind(alice.id, "update_smoke", "update_smoke:alice", True)
            with connect(db_path) as db:
                init_db(db)
                insert_principals(db, [Principal("update_smoke", "update_smoke:alice", "Alice", "engineer", "eng")], {})
                text = "SeedPolicy is an unrelated reference document."
                seed = CanonicalDoc("update_smoke", "seed", "confluence", "SeedPolicy", text,
                    None, None, "eng", [], ["update_smoke:alice"], "synthetic ACL", "seed-v1", content_hash(text), {}, ["seed-0"])
                insert_documents(db, [seed], [Chunk("seed-0", seed.corpus, seed.doc_id, 0, text)])
                db.commit()
            initial = migrate(db_path, client)
            collection = initial["collection"]
            app = create_app(db_path, security, config={"TESTING": True, "SECRET_KEY": "isolated-update-smoke-" * 3,
                "DEMO_MODE": False, "BROWSER_LOGIN_ENABLED": False})
            server = make_server("127.0.0.1", 0, app, threaded=True, request_handler=QuietHandler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            url = f"http://127.0.0.1:{server.server_port}"
            def session(actor):
                result = requests.Session()
                sid = identities.new_session(identities.get(actor.id), time.time() + 600)
                cookie = app.session_interface.get_signing_serializer(app).dumps({"sid": sid, "csrf": "smoke"})
                result.cookies.set("session", cookie)
                result.headers["X-CSRF-Token"] = "smoke"
                return result
            operator, employee = session(admin), session(alice)
            manager = app.extensions["document_updates"]
            version = None
            previous_vector = None
            def body(amount, expected):
                return {"corpus": "update_smoke", "doc_id": "payment-policy", "source": "confluence",
                    "title": "PaymentPolicy transfer limits", "text": f"PaymentPolicy daily transfer limit is {amount} CNY. This approved limit applies to each customer. Internal route: {'legacyroute' if amount == '50,000' else 'currentroute'}.",
                    "acl": ["update_smoke:alice"], "expected_version": expected,
                    "source_updated_at": "2026-10-13T00:00:00Z"}
            def ready(job_id):
                deadline = time.monotonic() + 60
                while time.monotonic() < deadline:
                    response = operator.get(url + "/api/admin/document-updates/" + job_id, timeout=10)
                    response.raise_for_status()
                    job = response.json()["job"]
                    if job["state"] == "ready":
                        return job
                    if job["state"] == "failed" and job["attempts"] >= 3:
                        raise AssertionError(job)
                    time.sleep(.05)
                raise AssertionError("update did not publish within the smoke deadline")
            for operation, amount in (("HTTP add", "50,000"), ("HTTP modify", "100,000"), ("CLI modify", "150,000"), ("process recovery", "200,000")):
                started = time.monotonic()
                document = body(amount, version)
                if operation == "CLI modify":
                    path = directory / "update.json"
                    path.write_text(json.dumps(document))
                    command = [sys.executable, "-m", "contextledger.integration", "--out", str(db_path.parent),
                        "--security-dir", str(security), "upsert", "--file", str(path), "--admin-id", admin.id]
                    result = subprocess.run(command, cwd=ROOT, env=os.environ.copy(), capture_output=True, text=True, timeout=90)
                    assert result.returncode == 0, "CLI update failed"
                    job = json.loads(result.stdout.strip().splitlines()[-1])
                else:
                    if operation == "process recovery":
                        manager.close()
                        manager.autostart = False
                    response = operator.post(url + "/api/admin/documents", json=document, timeout=10)
                    assert response.status_code == 202, response.text
                    job = response.json()["job"]
                    if operation == "process recovery":
                        result = subprocess.run([sys.executable, "-m", "contextledger.integration", "--out", str(db_path.parent),
                            "--security-dir", str(security), "updates-worker", "--once"], cwd=ROOT, env=os.environ.copy(),
                            capture_output=True, text=True, timeout=90)
                        assert result.returncode == 0, "worker recovery failed"
                job = ready(job["id"])
                version = job["version"]
                step = {"operation": operation, "amount_cny": amount, "version": version,
                        "publication_ms": (time.monotonic() - started) * 1000, "modes": {}}
                for mode in ("keyword", "vector", "hybrid"):
                    response = employee.post(url + "/api/ask", json={"corpus": "update_smoke", "q": "PaymentPolicy",
                        "mode": mode, "planning": False}, timeout=30)
                    assert response.status_code == 200, response.text
                    answer = response.json()
                    assert answer["decision"] == "answered" and answer["provider"] == "mock", answer
                    assert amount in answer["answer"] and {e["version"] for e in answer["evidence"]} == {version}, answer
                    step["modes"][mode] = {"answer": answer["answer"], "request_id": answer["request_id"]}
                match = qm.Filter(must=[qm.FieldCondition(key="corpus", match=qm.MatchValue(value="update_smoke")),
                    qm.FieldCondition(key="doc_id", match=qm.MatchValue(value="payment-policy"))])
                points, _ = client.scroll(collection, scroll_filter=match, limit=100, with_vectors=True)
                assert points and all(p.payload["version"] == version for p in points)
                vector = points[0].vector
                assert len(vector) == 384 and (previous_vector is None or vector != previous_vector)
                previous_vector = vector
                step["vector_sha256"] = hashlib.sha256(json.dumps(vector).encode()).hexdigest()
                report["steps"].append(step)
                print(f"{operation}: {amount} CNY; all retrieval modes and answers passed", flush=True)
            response = operator.post(url + "/api/admin/documents", json=body("300,000", None), timeout=10)
            assert response.status_code == 409
            assert requests.post(url + "/api/ask", json={"q": "PaymentPolicy"}, timeout=5).status_code == 401
            with connect(db_path) as db:
                assert db.execute("SELECT COUNT(*) FROM docs_fts WHERE doc_id='payment-policy'").fetchone()[0] == 1
                assert db.execute("SELECT COUNT(*) FROM docs_fts WHERE docs_fts MATCH 'legacyroute'").fetchone()[0] == 0
                report["retained_versions"] = db.execute("SELECT COUNT(*) FROM cl_document_history WHERE doc_id='payment-policy'").fetchone()[0]
                assert report["retained_versions"] == 4
            report["audit_valid"] = app.extensions["unified_service"].audit.verify().valid
            assert report["audit_valid"]
            report["status"] = "passed"
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
            print(json.dumps({"status": "passed", "report": str(args.report), "retained_versions": 4}))
    finally:
        if app:
            app.extensions["document_updates"].close()
        if server:
            server.shutdown()
            server.server_close()
        if collection:
            client.delete_collection(collection)
        client.close()


if __name__ == "__main__":
    main()
