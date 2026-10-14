"""Offline cases prepared for later execution; no credentials or platform calls."""
import unittest
from unittest.mock import patch

from contextledger.ingestion.source_adapters import JiraAdapter, ConfluenceAdapter, DriveAdapter, SlackAdapter, ReadOnlyHTTP, SourceError


class FakeHTTP:
    def __init__(self, respond):
        self.respond = respond

    def request(self, path, **kwargs):
        return self.respond(path, kwargs)


class SourceAdapterTests(unittest.TestCase):
    def test_jira_uses_issue_grant_not_project_permission(self):
        http = FakeHTTP(lambda path, kw: {"projectPermissions": [{"permission": "BROWSE_PROJECTS", "projects": [1], "issues": []}]})
        adapter = JiraAdapter({"principal_map": {"native-a": "alpha:a"}}, http)
        acl, raw = adapter.permissions("10")
        self.assertEqual(acl, [])
        self.assertFalse(raw[0]["allowed"])

    def test_confluence_permission_failure_is_unknown_and_empty_acl(self):
        def failure(path, kw):
            raise SourceError("upstream_http_403")
        adapter = ConfluenceAdapter({"principal_map": {"native-a": "alpha:a"}}, FakeHTTP(failure))
        doc = adapter.document("1", "Page", "secret", "https://a.atlassian.net/wiki/1", "2", None, {})
        self.assertEqual(doc.permission_state, "unknown")
        self.assertEqual(doc.acl, [])
        self.assertNotIn("secret", doc.permission_basis)

    def test_confluence_effective_permission_maps_only_verified_reader(self):
        http = FakeHTTP(lambda path, kw: {"hasPermission": kw["body"]["subject"]["identifier"] == "native-a"})
        adapter = ConfluenceAdapter({"principal_map": {"native-a": "alpha:a", "native-b": "alpha:b"}}, http)
        self.assertEqual(adapter.permissions("1")[0], ["alpha:a"])

    def test_drive_does_not_expand_group_domain_or_expired_grants(self):
        http = FakeHTTP(lambda path, kw: {"permissions": [
            {"type": "group", "emailAddress": "team@company.test", "role": "reader"},
            {"type": "domain", "role": "reader"},
            {"type": "user", "emailAddress": "a@company.test", "role": "reader"},
            {"type": "user", "emailAddress": "b@company.test", "role": "reader", "expirationTime": "2000-01-01T00:00:00Z"}]})
        adapter = DriveAdapter({"base_url": "https://www.googleapis.com/drive/v3", "principal_map": {
            "a@company.test": "alpha:a", "b@company.test": "alpha:b", "team@company.test": "alpha:team"}}, http)
        self.assertEqual(adapter.permissions("file")[0], ["alpha:a"])

    def test_slack_members_are_paginated_and_deleted_users_excluded(self):
        def response(path, kw):
            if path == "users.info":
                return {"user": {"deleted": kw["params"]["user"] == "B"}}
            if kw["params"].get("cursor"):
                return {"members": ["B"], "response_metadata": {"next_cursor": ""}}
            return {"members": ["A"], "response_metadata": {"next_cursor": "next"}}
        adapter = SlackAdapter({"base_url": "https://slack.com/api", "principal_map": {"A": "alpha:a", "B": "alpha:b"}}, FakeHTTP(response))
        self.assertEqual(adapter.permissions("C:1")[0], ["alpha:a"])

    def test_http_cannot_send_credentials_to_pagination_other_origin(self):
        with patch.dict("os.environ", {"SOURCE_TEST_TOKEN": "synthetic-token"}):
            http = ReadOnlyHTTP("https://example.atlassian.net", "SOURCE_TEST_TOKEN")
            self.addCleanup(http.close)
            with self.assertRaisesRegex(SourceError, "cross_origin"):
                http.request("https://untrusted.invalid/api")
            with self.assertRaisesRegex(SourceError, "write_not_allowed"):
                http.request("/delete", body={})
