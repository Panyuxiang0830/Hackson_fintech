"""Prepared isolated regressions; not a claim of three-client or live verification."""
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
import uuid

from contextledger.access.identity_store import IdentityStore
from contextledger.access.tool_access import ToolAccess
from contextledger.interfaces.tool_api import create_tool_app
from contextledger.application.service import PermissionChanged


class ToolInterfaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.ids = IdentityStore(self.root / "identities.sqlite")
        self.alice = self.ids.register("test", "alice", "Alice")
        self.access = ToolAccess(self.root / "tokens.sqlite", self.ids)
        self.token_id, self.token = self.access.issue(self.alice.id)
        self.calls = []
        self.hook = lambda: None
        def fence(actor, *args):
            current = self.ids.get(actor.id)
            if not current.enabled or current.epoch != actor.epoch:
                raise PermissionChanged("changed")
        def search(user_id, corpus, query, mode, **kw):
            self.calls.append((user_id, kw))
            self.hook()
            return {"hits": [], "index_generation": None, "request_id": uuid.uuid4().hex}, []
        self.service = SimpleNamespace(identities=self.ids, audit=SimpleNamespace(append=lambda row: None),
            search=search, fence=fence, record=lambda *a, **kw: None)
        self.app = create_tool_app(self.service, self.access)
        self.client = self.app.test_client()

    def post(self, body=None, token=None, operation="search"):
        return self.client.post("/api/tools/" + operation, json=body or {"corpus": "alpha", "query": "Question"},
            headers={"Authorization": "Bearer " + (token or self.token)})

    def test_token_database_contains_only_digest_not_bearer(self):
        self.assertNotIn(self.token.encode(), (self.root / "tokens.sqlite").read_bytes())
        self.assertEqual(self.access.resolve(self.token, "search").id, self.alice.id)
        with self.assertRaises(PermissionError):
            self.access.resolve(self.token, "ask")

    def test_host_route_disables_internal_planning_and_returns_empty_guidance(self):
        result = self.post()
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json["decision"], "insufficient")
        self.assertEqual(self.calls[0], (self.alice.id, {"planning": False}))
        self.assertEqual(result.headers["Cache-Control"], "no-store, private")

    def test_caller_cannot_override_identity(self):
        self.assertEqual(self.post({"corpus": "alpha", "query": "Question", "user_id": "Bob"}).status_code, 400)
        self.assertEqual(self.calls, [])

    def test_token_revoke_during_search_blocks_delivery(self):
        self.hook = lambda: self.access.revoke(self.token_id)
        self.assertEqual(self.post().status_code, 409)

    def test_permission_change_during_search_blocks_delivery(self):
        self.hook = lambda: self.ids.update(self.alice.id, enabled=False)
        self.assertEqual(self.post().status_code, 409)

    def test_browser_session_cannot_replace_tool_credential(self):
        self.client.set_cookie("session", "forged-demo-or-browser-cookie")
        response = self.client.post("/api/tools/search", json={"corpus": "alpha", "query": "Q"})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(self.calls, [])

    def test_missing_credential_and_ask_scope_fail_closed(self):
        self.assertEqual(self.client.post("/api/tools/search", json={"corpus": "alpha", "query": "Q"}).status_code, 401)
        self.assertEqual(self.post(operation="ask").status_code, 401)
        _, token = self.access.issue(self.alice.id, ["ask"])
        self.assertEqual(self.post(operation="ask", token=token).status_code, 403)
