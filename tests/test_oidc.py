"""Regression for explicitly enabled, deferred optional browser login.

Real discovery/token/JWKS/signature flow against an isolated test-only issuer.

This fixture is NOT a login option shipped to the application or a real provider.
"""

import base64
import hashlib
import secrets
import threading
import time
import unittest
from urllib.parse import parse_qs, urlencode, urlparse

from flask import Flask, jsonify, request
from joserfc import jwt
from joserfc.jwk import RSAKey
from werkzeug.serving import WSGIRequestHandler, make_server

from tests import test_integration as fixtures
from contextledger.web import create_app


class QuietHandler(WSGIRequestHandler):
    def log_request(self, *args, **kwargs):
        pass


class OIDCTests(unittest.TestCase):
    def setUp(self):
        # Reuse setup only, not inherited test methods, for deterministic corpus fixtures.
        self.fixture = fixtures.IntegrationTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.keys = RSAKey.generate_key(2048, parameters={"kid": "test-key"})
        self.other_key = RSAKey.generate_key(2048, parameters={"kid": "test-key"})
        self.codes = {}
        self.break_claim = None
        issuer_app = Flask("isolated-oidc-test-provider")

        @issuer_app.get("/.well-known/openid-configuration")
        def discovery():
            return jsonify(issuer=self.issuer, authorization_endpoint=self.issuer + "/authorize",
                           token_endpoint=self.issuer + "/token", jwks_uri=self.issuer + "/jwks",
                           response_types_supported=["code"], subject_types_supported=["public"],
                           id_token_signing_alg_values_supported=["RS256"], code_challenge_methods_supported=["S256"])

        @issuer_app.get("/jwks")
        def jwks():
            return jsonify(keys=[self.keys.as_dict(private=False)])

        @issuer_app.post("/token")
        def token():
            code = self.codes.pop(request.form.get("code"), None)
            if code is None:
                return jsonify(error="invalid_grant"), 400
            verifier = request.form.get("code_verifier", "")
            challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
            if challenge != code["challenge"]:
                return jsonify(error="invalid_grant"), 400
            claims = {"iss": self.issuer, "sub": "verified-subject", "aud": "contextledger-test-client",
                      "iat": int(time.time()), "exp": int(time.time()) + 600, "nonce": code["nonce"], "name": "Verified Person"}
            key = self.keys
            if self.break_claim == "signature":
                key = self.other_key
            elif self.break_claim == "expired":
                claims["iat"], claims["exp"] = int(time.time()) - 1200, int(time.time()) - 600
            elif self.break_claim == "nonce":
                claims["nonce"] = "wrong-nonce"
                claims["nonce_supported"] = False  # Also test the explicit app nonce gate.
            elif self.break_claim == "audience":
                claims["aud"] = "different-client"
            elif self.break_claim == "issuer":
                claims["iss"] = "https://different-issuer.example"
            encoded = jwt.encode({"alg": "RS256", "kid": "test-key"}, claims, key)
            return jsonify(access_token="fixture-access-token", token_type="Bearer", expires_in=600, id_token=encoded)

        self.server = make_server("127.0.0.1", 0, issuer_app, threaded=True, request_handler=QuietHandler)
        self.issuer = f"http://127.0.0.1:{self.server.server_port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.app = create_app(self.fixture.db_path, self.fixture.security, service=self.fixture.service,
                             config={"TESTING": True, "SECRET_KEY": "oidc-test-secret-" * 4, "BROWSER_LOGIN_ENABLED": True,
                                     "OIDC_ISSUER": self.issuer, "OIDC_CLIENT_ID": "contextledger-test-client",
                                     "OIDC_CLIENT_SECRET": "", "PUBLIC_URL": "http://127.0.0.1:7860"})
        self.client = self.app.test_client()

    def flow(self, wrong_state=False):
        login = self.client.get("/auth/login")
        self.assertEqual(login.status_code, 302)
        params = parse_qs(urlparse(login.location).query)
        self.assertEqual(params["code_challenge_method"], ["S256"])
        code = secrets.token_urlsafe(16)
        self.codes[code] = {"nonce": params["nonce"][0], "challenge": params["code_challenge"][0]}
        return self.client.get("/auth/callback?" + urlencode({"state": "wrong-state" if wrong_state else params["state"][0], "code": code}))

    def test_verified_login_defaults_to_unbound_member_and_stable_identity(self):
        response = self.flow()
        self.assertEqual(response.status_code, 302, response.json)
        actor = self.client.get("/api/session").json["user"]
        self.assertEqual(actor["role"], "member")
        self.assertEqual(self.client.get("/api/corpora").json, [])
        self.assertEqual(self.client.get("/api/admin/users").status_code, 403)
        with self.client.session_transaction() as session:
            self.assertNotIn("access_token", session)
            self.assertNotIn("id_token", session)
            self.assertIn("sid", session)
        self.flow()
        self.assertEqual(self.client.get("/api/session").json["user"]["id"], actor["id"])

    def test_wrong_signature_expiry_audience_issuer_nonce_and_state_are_rejected(self):
        for broken in ("signature", "expired", "audience", "issuer", "nonce"):
            with self.subTest(broken=broken):
                self.break_claim = broken
                response = self.flow()
                self.assertEqual(response.status_code, 401)
                self.assertFalse(self.client.get("/api/session").json["authenticated"])
        self.break_claim = None
        self.assertEqual(self.flow(wrong_state=True).status_code, 401)


if __name__ == "__main__":
    unittest.main()
