"""Real permission/audit services behind explicit demo sessions, TESTING=False."""

from pathlib import Path
import unittest
from unittest.mock import patch

from tests import test_integration as fixtures
from contextledger.audit_store import AuditStore
from contextledger.demo_identity import DEMO_ISSUER, initialize_demo, require_loopback_bind
from contextledger.filtered_index import FilteredIndex
from contextledger.identity_store import IdentityStore
from contextledger.models import Principal
from contextledger.store import connect, insert_principals
from contextledger.unified_service import UnifiedService
from contextledger.web import create_app


class DemoIdentityTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.IntegrationTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.directory = self.fixture.root / "security-demo"
        self.db_path = self.fixture.db_path
        with connect(self.db_path) as db:
            insert_principals(db, [Principal("alpha", f"alpha:{name}", name, "engineer", "eng")
                                  for name in ("c", "d", "e")], {})
            db.commit()
        self.bindings = [("alpha", "alpha:a"), ("alpha", "alpha:b"), ("beta", "beta:a"),
                         ("alpha", "alpha:c"), ("alpha", "alpha:d"), ("alpha", "alpha:e")]
        self.roster = initialize_demo(self.db_path, self.directory, self.bindings)
        self.ids = IdentityStore(self.directory / "identities.sqlite")
        self.audit = AuditStore(self.directory / "audit.sqlite")
        index = FilteredIndex(self.db_path, self.fixture.qdrant, self.ids, embed=lambda query: [1.0, 0.0])
        self.service = UnifiedService(index, self.ids, self.audit, self.fixture.service.answer)
        self.url = "http://127.0.0.1:17860"
        self.config = {"TESTING": False, "SECRET_KEY": "demo-test-secret-" * 4,
                       "DEMO_MODE": True, "BROWSER_LOGIN_ENABLED": False, "PUBLIC_URL": self.url}
        self.app = create_app(self.db_path, self.directory, service=self.service, config=self.config)
        self.client = self.app.test_client()
        self.admin = self.roster["accounts"][0]["id"]
        self.alice = self.roster["accounts"][1]["id"]
        self.bob = self.roster["accounts"][2]["id"]

    def get(self, path, client=None, **kwargs):
        return (client or self.client).get(path, base_url=self.url, **kwargs)

    def post(self, path, body, client=None, **kwargs):
        client = client or self.client
        status = self.get("/api/session", client).json
        return client.post(path, json=body, base_url=self.url,
                           headers={"Origin": self.url, "X-CSRF-Token": status["csrf"]}, **kwargs)

    def select(self, actor, client=None):
        response = self.post("/api/demo/select", {"user_id": actor}, client)
        self.assertEqual(response.status_code, 200, response.json)

    def test_roster_has_independent_admin_and_six_members_without_oidc(self):
        people = self.get("/api/demo/accounts").json
        self.assertEqual(len(people), 7)
        self.assertEqual(people[0]["name"], "ContextLedger 管理员")
        self.assertEqual([item["role"] for item in people], ["admin"] + ["member"] * 6)
        self.assertEqual(self.ids.scope(self.ids.get(self.admin), "alpha")[0], [])
        self.assertFalse(self.app.testing)
        status = self.get("/api/session").json
        self.assertEqual(status["identity_mode"], "isolated_demo")
        self.assertFalse(status["identity_verified"])
        self.assertEqual(self.get("/auth/login").status_code, 404)
        self.assertIn("非真实登录", self.get("/").get_data(as_text=True))
        self.select(self.admin)
        self.assertEqual(len(self.get("/api/admin/users").json), 7)
        self.assertEqual(self.get("/api/corpora").json, [])

    def test_loopback_host_origin_and_csrf_gates(self):
        self.assertEqual(self.get("/", environ_overrides={"REMOTE_ADDR": "10.0.0.1"}).status_code, 403)
        self.assertEqual(self.client.get("/", base_url="http://evil.example:17860").status_code, 403)
        self.assertEqual(self.get("/", headers={"X-Forwarded-For": "127.0.0.1"},
                                  environ_overrides={"REMOTE_ADDR": "10.0.0.1"}).status_code, 403)
        status = self.get("/api/session").json
        for headers in ({"Origin": "http://evil.example", "X-CSRF-Token": status["csrf"]},
                        {"Origin": self.url}, {"X-CSRF-Token": status["csrf"]}):
            response = self.client.post("/api/demo/select", base_url=self.url,
                                        json={"user_id": self.admin}, headers=headers)
            self.assertEqual(response.status_code, 403)
        with self.assertRaises(ValueError):
            require_loopback_bind("0.0.0.0")

    def test_fixed_roster_rejects_arbitrary_users_and_role_injection(self):
        self.assertEqual(self.post("/api/demo/select", {"user_id": self.fixture.admin.id}).status_code, 403)
        self.assertEqual(self.post("/api/demo/select", {"user_id": self.alice, "role": "admin"}).status_code, 400)
        self.select(self.alice)
        self.assertEqual(self.get("/api/admin/users").status_code, 403)
        self.assertEqual(self.get("/api/audit").status_code, 403)
        self.assertEqual(self.get("/api/search?corpus=alpha&q=TitanDB&principal=alpha:b").status_code, 400)

    def test_search_answer_audit_and_admin_revocation_share_real_services(self):
        self.select(self.alice)
        first = self.get("/api/search?corpus=alpha&q=TitanDB").json
        self.assertEqual({hit["doc_id"] for hit in first["hits"]}, {"doc-0", "doc-1"})
        answer = self.post("/api/ask", {"corpus": "alpha", "q": "TitanDB"}).json
        self.assertEqual(answer["provider"], "mock")
        self.select(self.admin)
        audited = self.get("/api/audit?request_id=" + answer["request_id"]).json
        self.assertEqual(len(audited["events"]), 1)
        self.assertEqual(audited["events"][0]["identity_mode"], "isolated_demo")
        self.assertTrue(audited["integrity"]["valid"])
        self.assertIn("redacted", audited["events"][0]["answer"])
        denied = self.post("/api/admin/permissions", {"user_id": self.alice, "action": "restriction",
                "corpus": "alpha", "kind": "source", "value": "jira", "denied": True})
        self.assertEqual(denied.status_code, 200)
        self.select(self.alice)
        self.assertEqual([hit["doc_id"] for hit in self.get("/api/search?corpus=alpha&q=TitanDB").json["hits"]], ["doc-0"])
        self.assertEqual(self.get("/api/doc?corpus=alpha&doc_id=doc-1").status_code, 404)
        self.select(self.bob)
        self.assertEqual([hit["doc_id"] for hit in self.get("/api/search?corpus=alpha&q=TitanDB").json["hits"]], ["doc-2"])
        self.assertTrue(self.audit.verify().valid)

    def test_disabled_employee_cannot_select_or_reuse_session(self):
        other = self.app.test_client()
        self.select(self.alice, other)
        self.select(self.admin)
        self.assertEqual(self.post("/api/admin/permissions", {"action": "account", "user_id": self.alice, "enabled": False}).status_code, 200)
        self.assertEqual(self.get("/api/search?corpus=alpha&q=TitanDB", other).status_code, 401)
        self.assertEqual(self.post("/api/demo/select", {"user_id": self.alice}).status_code, 403)
        people = self.get("/api/demo/accounts").json
        self.assertFalse(next(person for person in people if person["id"] == self.alice)["enabled"])

    def test_reinitialization_and_restart_preserve_revocation_and_state(self):
        self.ids.bind(self.alice, "alpha", "alpha:a", False)
        self.ids.restrict(self.bob, "alpha", "source", "slack", True)
        initial_count = self.audit.verify().event_count
        reopened = initialize_demo(self.db_path, self.directory, self.bindings)
        self.assertEqual(reopened, self.roster)
        self.assertEqual(self.audit.verify().event_count, initial_count)
        restarted = create_app(self.db_path, self.directory, service=self.service, config=self.config).test_client()
        self.select(self.alice, restarted)
        self.assertEqual(self.get("/api/search?corpus=alpha&q=TitanDB", restarted).json["hits"], [])
        self.assertEqual(self.ids.scope(self.ids.get(self.bob), "alpha")[1], {"source": ["slack"]})

    def test_default_mode_never_activates_demo_endpoint_or_old_demo_session(self):
        ordinary = create_app(self.db_path, self.directory, service=self.service,
                             config={**self.config, "DEMO_MODE": False}).test_client()
        sid = self.ids.new_session(self.ids.get(self.admin), 9999999999)
        with ordinary.session_transaction() as session:
            session["sid"] = sid
        self.assertEqual(self.get("/api/demo/accounts", ordinary).status_code, 404)
        self.assertEqual(self.get("/api/admin/users", ordinary).status_code, 401)
        self.assertNotIn('id="demoidentity"', self.get("/", ordinary).get_data(as_text=True))

    def test_demo_refuses_production_security_state_public_url_and_oidc(self):
        with self.assertRaises(ValueError):
            initialize_demo(self.db_path, self.fixture.security, self.bindings)
        for config in ({**self.config, "PUBLIC_URL": "http://example.com"},
                       {**self.config, "BROWSER_LOGIN_ENABLED": True}):
            with self.assertRaises(ValueError):
                create_app(self.db_path, self.directory, service=self.service, config=config)
        with self.assertRaises(ValueError):
            create_app(self.db_path, self.fixture.security, service=self.fixture.service, config=self.config)


if __name__ == "__main__":
    unittest.main()
