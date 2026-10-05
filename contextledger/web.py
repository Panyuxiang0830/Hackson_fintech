"""7860 unified UI with OIDC-only identity, CSRF and server-side role checks."""

from __future__ import annotations

from dataclasses import asdict
from functools import wraps
import os
from pathlib import Path
import secrets
import sqlite3
import time
from urllib.parse import urlparse

from authlib.integrations.flask_client import OAuth
from flask import Flask, g, jsonify, render_template, request, session
from qdrant_client import QdrantClient

from contextledger.audit_store import AuditStore
from contextledger.filtered_index import FilteredIndex, IndexUnavailable
from contextledger.identity_store import IdentityStore
from contextledger.source_permissions import SourcePermissionAdapter
from contextledger.store import connect
from contextledger.unified_service import PermissionChanged, UnifiedService, timestamp, validate_security_path
from src.audit import AuditIntegrityError


def create_app(db_path: Path, security_dir: Path, *, service=None, config=None):
    validate_security_path(Path(db_path).parent, Path(security_dir))
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=os.getenv("APP_SECRET_KEY") or secrets.token_hex(32),
        OIDC_ISSUER=os.getenv("OIDC_ISSUER", ""), OIDC_CLIENT_ID=os.getenv("OIDC_CLIENT_ID", ""),
        OIDC_CLIENT_SECRET=os.getenv("OIDC_CLIENT_SECRET", ""),
        PUBLIC_URL=os.getenv("APP_PUBLIC_URL", "http://127.0.0.1:7860"),
        SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.getenv("APP_PUBLIC_URL", "").startswith("https://"),
        MAX_CONTENT_LENGTH=32 * 1024,
    )
    if config:
        app.config.update(config)
    issuer = app.config["OIDC_ISSUER"]
    public_url = app.config["PUBLIC_URL"].rstrip("/")
    for url in (issuer, public_url):
        if not url:
            continue
        parsed = urlparse(url)
        if parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"}):
            raise ValueError("OIDC issuer/public URL must be HTTPS or a loopback development URL")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("OIDC issuer/public URL must not contain credentials, query or fragment")
    configured = bool(issuer and app.config["OIDC_CLIENT_ID"])
    if configured and (not (os.getenv("APP_SECRET_KEY") or config and config.get("SECRET_KEY")) or len(app.config["SECRET_KEY"]) < 32):
        raise ValueError("APP_SECRET_KEY must have at least 32 characters")
    oauth = OAuth(app)
    oidc = None
    if configured:
        oidc = oauth.register("oidc", client_id=app.config["OIDC_CLIENT_ID"],
            client_secret=app.config["OIDC_CLIENT_SECRET"],
            server_metadata_url=issuer.rstrip("/") + "/.well-known/openid-configuration",
            client_kwargs={"scope": "openid profile", "code_challenge_method": "S256",
                "token_endpoint_auth_method": "client_secret_basic" if app.config["OIDC_CLIENT_SECRET"] else "none"})
    if service is None:
        identities = IdentityStore(Path(security_dir) / "identities.sqlite")
        client = QdrantClient(url=os.getenv("QDRANT_URL", "http://127.0.0.1:6335"),
                              api_key=os.getenv("QDRANT_API_KEY") or None, timeout=60)
        service = UnifiedService(FilteredIndex(db_path, client, identities), identities,
                                 AuditStore(Path(security_dir) / "audit.sqlite"))
    app.extensions["unified_service"] = service
    app.extensions["oidc_client"] = oidc

    @app.before_request
    def protect():
        if not request.path.startswith("/api/") or request.path == "/api/session":
            return
        actor = service.identities.session_actor(session.get("sid", ""))
        if not actor:
            service.audit.append({"request_id": secrets.token_hex(16), "timestamp": timestamp(),
                                  "event_type": "unauthenticated_request", "user_id": "unauthenticated", "decision": "denied",
                                  "endpoint": request.path, "retrieved_document_ids": []})
            return jsonify(error="login_required"), 401
        g.actor = actor
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            csrf = session.get("csrf", "")
            if not csrf or not secrets.compare_digest(csrf, request.headers.get("X-CSRF-Token", "")):
                service.record(actor, "csrf_rejected", decision="denied", endpoint=request.path)
                return jsonify(error="csrf_failed"), 403
        # Never accept an arbitrary caller-chosen source identity.
        body = request.get_json(silent=True) or {}
        if "principal" in request.args or isinstance(body, dict) and any(k in body for k in ("principal", "principal_id")):
            if not request.path.startswith("/api/admin/"):
                return jsonify(error="caller_selected_identity_not_allowed"), 400

    @app.after_request
    def headers_and_delivery_check(response):
        if getattr(g, "actor", None) and response.status_code < 400:
            try:
                service.fence(g.actor, *getattr(g, "delivery", ()))
            except (PermissionError, PermissionChanged, IndexUnavailable):
                response = jsonify(error="permissions_or_snapshot_changed", retry=True)
                response.status_code = 409
        response.headers["Cache-Control"] = "no-store, private"
        response.headers["Pragma"] = "no-cache"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
        return response

    @app.errorhandler(PermissionError)
    def denied(error):
        if getattr(g, "actor", None):
            service.record(g.actor, "access_denied", decision="denied", endpoint=request.path)
        return jsonify(error="forbidden"), 403

    @app.errorhandler(PermissionChanged)
    def changed(error):
        return jsonify(error=str(error), retry=True), 409

    @app.errorhandler(IndexUnavailable)
    def unavailable(error):
        if getattr(g, "actor", None):
            service.record(g.actor, "index_unavailable", decision="blocked", endpoint=request.path)
        return jsonify(error=str(error)), 503

    @app.errorhandler(AuditIntegrityError)
    def audit_error(error):
        return jsonify(error="audit_integrity_failed; protected response blocked"), 503

    @app.errorhandler(ValueError)
    def invalid(error):
        if getattr(g, "actor", None):
            service.record(g.actor, "invalid_request", decision="denied", endpoint=request.path)
        return jsonify(error=str(error)), 400

    def role(*allowed):
        def decorate(fn):
            @wraps(fn)
            def check(*args, **kwargs):
                if g.actor.role not in allowed:
                    raise PermissionError("role required")
                return fn(*args, **kwargs)
            return check
        return decorate

    def inputs(body=None):
        args = body if body is not None else request.args
        corpus = args.get("corpus", "orgforge")
        query = args.get("q", "")
        mode = args.get("mode", "hybrid")
        if not isinstance(corpus, str) or not isinstance(query, str) or not query.strip() or len(query) > 4000:
            raise ValueError("corpus and a question of 1..4000 characters are required")
        day = args.get("as_of")
        if day not in (None, ""):
            if isinstance(day, bool):
                raise ValueError("invalid as_of")
            day = int(day)
        else:
            day = None
        return corpus, query, mode, day

    @app.get("/")
    def index_page():
        return render_template("unified.html")

    @app.get("/api/session")
    def status():
        actor = service.identities.session_actor(session.get("sid", ""))
        if actor:
            g.actor = actor
        return jsonify(oidc_configured=configured, authenticated=bool(actor),
                       user=asdict(actor) if actor else None, csrf=session.get("csrf") if actor else None,
                       login_identity=service.identities.login_identity(actor.id) if actor else None,
                       source_permissions="not_enabled", freshness="offline snapshot only")

    @app.get("/auth/login")
    def login():
        if oidc is None:
            return jsonify(error="OIDC is not configured; set issuer and client ID. No demo login is enabled."), 503
        session.clear()
        session["oidc_nonce"] = secrets.token_urlsafe(32)
        return oidc.authorize_redirect(public_url + "/auth/callback", nonce=session["oidc_nonce"])

    @app.get("/auth/callback")
    def callback():
        if oidc is None:
            return jsonify(error="OIDC not configured"), 503
        try:
            token = oidc.authorize_access_token(leeway=0)
            claims = token.get("userinfo") if token.get("id_token") else None
            if not claims or not session.get("oidc_nonce") or not secrets.compare_digest(session["oidc_nonce"], str(claims.get("nonce", ""))):
                raise ValueError("nonce mismatch")
            audience = claims.get("aud") if claims else None
            if not claims or claims.get("iss") != issuer or not claims.get("sub"):
                raise ValueError("missing verified identity")
            if app.config["OIDC_CLIENT_ID"] not in ([audience] if isinstance(audience, str) else audience or []):
                raise ValueError("wrong audience")
            expires = min(float(claims["exp"]), time.time() + 8 * 3600)
            if expires <= time.time():
                raise ValueError("expired identity")
            actor = service.identities.register(issuer, claims["sub"], claims.get("name") or claims["sub"])
            if not actor.enabled:
                raise PermissionError("account disabled")
            service.record(actor, "login")
            sid = service.identities.new_session(actor, expires)
            session.clear()  # No access/ID tokens in our application session cookie.
            session["sid"], session["csrf"] = sid, secrets.token_urlsafe(32)
        except Exception:
            session.clear()
            return jsonify(error="OIDC verification failed"), 401
        from flask import redirect
        return redirect("/")

    @app.post("/api/logout")
    def logout():
        service.identities.end_session(session.get("sid", ""))
        session.clear()
        return jsonify(ok=True)

    @app.get("/api/corpora")
    def corpora():
        found = []
        with connect(db_path) as db:
            for (corpus,) in db.execute("SELECT DISTINCT corpus FROM documents ORDER BY corpus"):
                scope = service.index.scope(g.actor, corpus)
                if scope.principals:
                    found.append({"id": corpus, "label": corpus, "scope": "Offline source ACL snapshot + current system permissions"})
        return jsonify(found)

    @app.get("/api/search")
    def search():
        corpus, query, mode, day = inputs()
        result, hits = service.search(g.actor.id, corpus, query, mode, day)
        g.delivery = (corpus, result["index_generation"], hits)
        return jsonify(result)

    @app.post("/api/ask")
    def ask():
        corpus, query, mode, day = inputs(request.get_json() or {})
        result, hits = service.ask(g.actor.id, corpus, query, mode, day)
        g.delivery = (corpus, result["index_generation"], hits)
        return jsonify(result)

    @app.get("/api/doc")
    def document():
        corpus, doc_id = request.args.get("corpus", "orgforge"), request.args.get("doc_id", "")
        if not doc_id:
            raise ValueError("doc_id required")
        result, hit = service.open(g.actor.id, corpus, doc_id)
        if hit:
            g.delivery = (corpus, result["index_generation"], [hit])
        return jsonify(result), 200 if hit else 404

    @app.get("/api/audit")
    @role("admin", "compliance")
    def audit():
        return jsonify(service.audit_query(g.actor.id, query=request.args.get("q", ""),
            **{key: request.args.get(key) for key in ("user_id", "request_id", "document_id", "start", "end")}))

    @app.get("/api/admin/users")
    @role("admin")
    def users():
        return jsonify(service.identities.users())

    @app.get("/api/admin/principals")
    @role("admin")
    def principals():
        with connect(db_path) as db:
            return jsonify([dict(r) for r in db.execute("SELECT * FROM principals ORDER BY corpus,name")])

    @app.post("/api/admin/permissions")
    @role("admin")
    def permissions():
        body = request.get_json() or {}
        target = body.get("user_id")
        if not service.identities.get(target):
            raise ValueError("unknown user")
        action = body.get("action")
        service.fence(g.actor)
        # An intent survives if a later write/audit step fails; no false success event.
        detail = {k: body.get(k) for k in ("user_id", "action", "corpus", "principal_id", "kind", "value", "enabled", "denied", "role")}
        if action == "binding":
            with connect(db_path) as db:
                if not db.execute("SELECT 1 FROM principals WHERE corpus=? AND principal_id=?", (body.get("corpus"), body.get("principal_id"))).fetchone():
                    raise ValueError("source principal does not exist in this corpus")
            service.record(g.actor, "permission_change_intent", change=detail)
            service.identities.bind(target, body["corpus"], body["principal_id"], body.get("enabled"))
        elif action == "restriction":
            service.record(g.actor, "permission_change_intent", change=detail)
            service.identities.restrict(target, body["corpus"], body["kind"], body["value"], body.get("denied"))
        elif action == "account":
            changes = {key: body[key] for key in ("role", "enabled", "department", "groups", "projects", "clearance") if key in body}
            if target == g.actor.id and (changes.get("enabled") is False or changes.get("role", "admin") != "admin"):
                raise ValueError("Use another admin to disable/demote this admin account")
            service.record(g.actor, "permission_change_intent", change=detail)
            service.identities.update(target, **changes)
        else:
            raise ValueError("unknown permission action")
        service.record(g.actor, "permission_change", change=detail)
        # Self-binding changes need an updated delivery epoch, not an accidental 409.
        if target == g.actor.id:
            g.actor = service.current(g.actor.id)
        return jsonify(ok=True, user=asdict(service.current(target)) if service.identities.get(target).enabled else {"id": target, "enabled": False})

    @app.get("/api/admin/source-permissions")
    @role("admin")
    def source_status():
        adapter = SourcePermissionAdapter()
        return jsonify([adapter.sync(source) for source in ("slack", "jira", "confluence", "google_drive")])

    return app
