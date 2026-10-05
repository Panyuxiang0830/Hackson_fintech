"""Local Part A demo: identity, as-of day, and ACL-filtered search."""

from __future__ import annotations

import json
from pathlib import Path

from flask import Flask, jsonify, render_template, request

from contextledger.search import MODES, open_document, search
from contextledger.store import connect

PRESETS = [
    {
        "id": "jax-titandb",
        "label": "Jax reads TitanDB",
        "corpus": "orgforge",
        "principal": "orgforge:Jax",
        "as_of": 60,
        "q": "TitanDB",
        "mode": "hybrid",
    },
    {
        "id": "vince-titandb",
        "label": "Vince misses the wiki",
        "corpus": "orgforge",
        "principal": "orgforge:Vince",
        "as_of": 60,
        "q": "TitanDB",
        "mode": "hybrid",
    },
    {
        "id": "jax-semantic",
        "label": "Jax, no keyword",
        "corpus": "orgforge",
        "principal": "orgforge:Jax",
        "as_of": 60,
        "q": "database storing athlete wearable telemetry",
        "mode": "vector",
    },
    {
        "id": "vince-semantic",
        "label": "Vince, same words",
        "corpus": "orgforge",
        "principal": "orgforge:Vince",
        "as_of": 60,
        "q": "database storing athlete wearable telemetry",
        "mode": "vector",
    },
    {
        "id": "liam-dm",
        "label": "Liam opens his DM",
        "corpus": "orgforge",
        "principal": "orgforge:Liam",
        "as_of": 60,
        "q": "hamnet",
        "mode": "hybrid",
    },
    {
        "id": "dave-dm",
        "label": "HR cannot open that DM",
        "corpus": "orgforge",
        "principal": "orgforge:Dave",
        "as_of": 60,
        "q": "hamnet",
        "mode": "hybrid",
    },
    {
        "id": "liam-power",
        "label": "Liam, field power",
        "corpus": "orgforge",
        "principal": "orgforge:Liam",
        "as_of": 60,
        "q": "backup power pack for the field radios",
        "mode": "vector",
    },
    {
        "id": "dave-power",
        "label": "HR, same field power",
        "corpus": "orgforge",
        "principal": "orgforge:Dave",
        "as_of": 60,
        "q": "backup power pack for the field radios",
        "mode": "vector",
    },
    {
        "id": "jordan-in",
        "label": "Jordan on day 8",
        "corpus": "orgforge",
        "principal": "orgforge:Jordan",
        "as_of": 8,
        "q": "incident",
        "mode": "hybrid",
    },
    {
        "id": "jordan-out",
        "label": "Jordan after he left",
        "corpus": "orgforge",
        "principal": "orgforge:Jordan",
        "as_of": 40,
        "q": "incident",
        "mode": "hybrid",
    },
    {
        "id": "engineer-runbook",
        "label": "Redwood engineer",
        "corpus": "enterpriserag",
        "principal": "enterpriserag:engineer",
        "as_of": 60,
        "q": "runbook",
        "mode": "hybrid",
    },
    {
        "id": "contractor-runbook",
        "label": "Contractor misses Confluence",
        "corpus": "enterpriserag",
        "principal": "enterpriserag:contractor",
        "as_of": 60,
        "q": "runbook",
        "mode": "hybrid",
    },
]


def create_app(db_path: Path) -> Flask:
    app = Flask(__name__, template_folder=str(Path(__file__).parent / "templates"))
    app.config["DB_PATH"] = db_path

    def db():
        return connect(app.config["DB_PATH"])

    @app.get("/")
    def index():
        connection = db()
        try:
            corpora = [{"id": row[0], "label": {"orgforge": "Apex Athletics (OrgForge)", "enterpriserag": "Redwood Inference (EnterpriseRAG)"}.get(row[0], row[0]), "scope": "Offline dataset"} for row in connection.execute("SELECT DISTINCT corpus FROM documents ORDER BY corpus")]
            if connection.execute("SELECT 1 FROM sqlite_master WHERE name='datasets'").fetchone():
                metadata = {row[0]: (row[1], json.loads(row[2])) for row in connection.execute("SELECT corpus,label,metadata_json FROM datasets")}
                for corpus in corpora:
                    if corpus["id"] in metadata:
                        label, info = metadata[corpus["id"]]
                        corpus.update(label=label, scope=info["scope"])
            presets = list(PRESETS)
            for corpus in corpora:
                if corpus["id"] in {"orgforge", "enterpriserag"}:
                    continue
                for source in ("google_drive", "jira", "slack"):
                    row = connection.execute("SELECT doc_id,title,acl_json,text FROM documents WHERE corpus=? AND source=? ORDER BY doc_id LIMIT 1", (corpus["id"], source)).fetchone()
                    if row is None or not json.loads(row["acl_json"]):
                        continue
                    principal = json.loads(row["acl_json"])[0]
                    query = row["doc_id"] if source == "jira" else row["title"] if source == "google_drive" else " ".join(row["text"].split()[-8:])
                    presets.append({"id": f"{corpus['id']}-{source}", "label": f"{corpus['id'].removeprefix('privacy_').removeprefix('publicjira_')} · {source}", "corpus": corpus["id"], "principal": principal, "as_of": 60, "q": query, "mode": "hybrid"})
                outsider = connection.execute("SELECT principal_id FROM principals WHERE corpus=? AND role='outsider' LIMIT 1", (corpus["id"],)).fetchone()
                if outsider:
                    presets.append({"id": f"{corpus['id']}-outside", "label": f"{corpus['id'].removeprefix('privacy_')} · outside", "corpus": corpus["id"], "principal": outsider[0], "as_of": 60, "q": "project", "mode": "hybrid"})
        finally:
            connection.close()
        return render_template("part_a.html", presets=presets, corpora=corpora)

    def as_of(corpus):
        if corpus != "orgforge":
            return None
        raw = request.args.get("as_of", "60") or "60"
        try:
            day = int(raw)
        except ValueError:
            raise ValueError("as_of must be a day between 0 and 60")
        if not 0 <= day <= 60:
            raise ValueError("as_of must be a day between 0 and 60")
        return day

    @app.get("/api/principals")
    def principals():
        corpus = request.args.get("corpus", "orgforge")
        connection = db()
        try:
            rows = connection.execute(
                """
                SELECT principal_id, name, role, dept, active_from, active_until
                FROM principals
                WHERE corpus = ?
                ORDER BY role, name
                """,
                (corpus,),
            ).fetchall()
        finally:
            connection.close()
        people = []
        for row in rows:
            if row["role"] == "employee" and not row["dept"]:
                continue
            people.append(
                {
                    "id": row["principal_id"],
                    "name": row["name"],
                    "role": row["role"],
                    "dept": row["dept"],
                    "active_from": row["active_from"],
                    "active_until": row["active_until"],
                }
            )
        return jsonify(people)

    @app.get("/api/search")
    def search_route():
        corpus = request.args.get("corpus", "orgforge")
        principal = request.args.get("principal", "")
        query = request.args.get("q", "")
        mode = request.args.get("mode", "hybrid")
        if mode not in MODES:
            return jsonify({"error": "unknown retrieval mode"}), 400
        try:
            day = as_of(corpus)
        except ValueError as error:
            return jsonify({"error": str(error)}), 400
        connection = db()
        try:
            result = search(
                connection,
                corpus=corpus,
                query=query,
                principal_id=principal,
                as_of_day=day,
                limit=8,
                mode=mode,
            )
        finally:
            connection.close()
        return jsonify({key: value for key, value in result.items() if key not in {"withheld", "scanned"}})

    @app.get("/api/doc")
    def doc():
        corpus = request.args.get("corpus", "orgforge")
        principal = request.args.get("principal", "")
        doc_id = request.args.get("doc_id", "")
        try:
            day = as_of(corpus)
        except ValueError as error:
            return jsonify({"error": str(error)}), 400
        connection = db()
        try:
            opened = open_document(
                connection,
                corpus=corpus,
                doc_id=doc_id,
                principal_id=principal,
                as_of_day=day,
            )
        finally:
            connection.close()
        if opened is None:
            return jsonify({"available": False}), 404
        return jsonify({"available": True, "doc": opened})

    return app


def serve(db_path: Path, host: str = "127.0.0.1", port: int = 7860) -> None:
    # The old create_app remains an offline ACL diagnostic for dataset tests.
    # The public launcher always uses the unified, authenticated boundary.
    import os
    from dotenv import load_dotenv
    from contextledger.web import create_app as unified_app

    load_dotenv()
    security_dir = Path(os.getenv("SECURITY_DIR", "runtime/security"))
    app = unified_app(db_path, security_dir)
    app.run(host=host, port=port, debug=False)
