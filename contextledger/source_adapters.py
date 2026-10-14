"""Bounded Cloud API readers. Observed permissions are snapshots, not live guarantees."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
import hashlib
import json
import os
import time
from urllib.parse import quote, urljoin, urlparse

import requests

SOURCES = {"jira", "confluence", "slack", "google_drive"}


class SourceError(RuntimeError):
    """Safe error code only: never URL, credential or raw upstream body."""


class ReadOnlyHTTP:
    def __init__(self, base_url, token_env, email_env=None):
        parsed = urlparse(base_url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("source API requires a credential-free HTTPS base URL")
        token = os.getenv(token_env, "")
        email = os.getenv(email_env, "") if email_env else None
        if not token or email_env and not email:
            raise SourceError("source_credentials_not_configured")
        self.base = base_url.rstrip("/")
        self.origin = (parsed.scheme, parsed.netloc)
        self.session = requests.Session()
        self.session.trust_env = False
        if email:
            self.session.auth = (email, token)
        else:
            self.session.headers["Authorization"] = "Bearer " + token
        self.calls, self.deadline = 0, time.monotonic() + 120

    def request(self, path, *, params=None, body=None, text=False):
        # Permission-check POSTs are read operations; all upstream mutations forbidden.
        if body is not None and not (path.endswith("/permission/check") or path == "/rest/api/3/permissions/check"):
            raise SourceError("upstream_write_not_allowed")
        url = urljoin(self.base + "/", path)
        parsed = urlparse(url)
        if (parsed.scheme, parsed.netloc) != self.origin or parsed.username or parsed.password or parsed.fragment:
            raise SourceError("cross_origin_pagination_rejected")
        self.calls += 1
        if self.calls > 500 or time.monotonic() >= self.deadline:
            raise SourceError("source_request_budget_exceeded")
        try:
            with self.session.request("POST" if body is not None else "GET", url, params=params, json=body,
                    headers={"Accept": "application/json"}, allow_redirects=False, stream=True,
                    timeout=(5, max(1, min(20, self.deadline - time.monotonic())))) as response:
                if response.status_code != 200:
                    raise SourceError("upstream_http_%d" % response.status_code)
                payload = bytearray()
                for chunk in response.iter_content(65536):
                    payload.extend(chunk)
                    if len(payload) > 2 * 1024 * 1024 or time.monotonic() >= self.deadline:
                        raise SourceError("source_response_budget_exceeded")
                if text:
                    return payload.decode("utf-8")
                result = json.loads(payload)
                if not isinstance(result, dict) or result.get("ok") is False:
                    raise SourceError("source_response_rejected")
                return result
        except (requests.RequestException, ValueError, UnicodeError):
            raise SourceError("source_transport_or_format_error") from None

    def close(self):
        self.session.close()


class _HTMLText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts, self.hidden = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden += 1
        if tag in {"p", "div", "br", "li", "tr", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style"} and self.hidden:
            self.hidden -= 1

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def plain(value):
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return value.get("text", "") + "\n".join(plain(v) for v in value.get("content", []))
    if isinstance(value, list):
        return "\n".join(plain(v) for v in value)
    return ""


@dataclass
class NativeDocument:
    resource_id: str
    title: str
    text: str
    source_url: str
    revision: str
    updated_at: str | None
    acl: list[str]
    permission_state: str
    permission_basis: str
    raw: dict

    def serializable(self):
        return asdict(self)


class SourceAdapter:
    def __init__(self, config, http=None):
        self.config = config
        mapping = config.get("principal_map", {})
        if not isinstance(mapping, dict) or not mapping or len(mapping) > 100 or any(
                not isinstance(k, str) or not k or not isinstance(v, str) or not v for k, v in mapping.items()):
            raise ValueError("explicit native-ID to existing canonical-principal map required (1..100)")
        self.mapping = mapping
        self.http = http or ReadOnlyHTTP(config["base_url"], config["token_env"], config.get("email_env"))

    def permissions(self, resource):
        raise NotImplementedError

    def document(self, resource_id, title, text, url, revision, updated, raw):
        try:
            acl, native = self.permissions(resource_id)
            state, basis = "verified_subset", "source effective permission checks for explicitly mapped identities"
        except SourceError as error:
            acl, native, state, basis = [], {"error_type": str(error)}, "unknown", "source permission check incomplete"
        raw = {**raw, "permissions": native}
        return NativeDocument(str(resource_id), title, text, url, str(revision), updated,
                              sorted(set(acl)), state, basis, raw)

    def records(self):
        raise NotImplementedError


class JiraAdapter(SourceAdapter):
    def permissions(self, issue_id):
        grants, evidence = [], []
        for account_id, principal in self.mapping.items():
            result = self.http.request("/rest/api/3/permissions/check", body={"accountId": account_id,
                "projectPermissions": [{"issues": [int(issue_id)], "permissions": ["BROWSE_PROJECTS"]}]})
            entries = result.get("projectPermissions")
            if not isinstance(entries, list):
                raise SourceError("jira_permission_format_unknown")
            permitted = any(p.get("permission") == "BROWSE_PROJECTS" and str(issue_id) in
                            [str(i) for i in p.get("issues", [])] for p in entries)
            evidence.append({"account_id": account_id, "allowed": permitted, "result": result})
            if permitted:
                grants.append(principal)
        return grants, evidence

    def records(self):
        cursor = None
        jql = self.config.get("jql")
        if not isinstance(jql, str) or not jql.strip() or len(jql) > 2000:
            raise ValueError("explicit bounded JQL scope required")
        while True:
            params = {"jql": jql, "maxResults": 100, "fields": "summary,description,status,updated,security"}
            if cursor:
                params["nextPageToken"] = cursor
            batch = self.http.request("/rest/api/3/search/jql", params=params)
            for item in batch.get("issues", []):
                fields, key = item.get("fields", {}), str(item["key"])
                # Comments may have narrower visibility than their parent issue;
                # first version does not merge comments/attachments into this ACL.
                text = plain(fields.get("description")) + "\nStatus: " + fields.get("status", {}).get("name", "unknown")
                document = self.document(item["id"], key + " " + fields.get("summary", ""), text,
                    self.config["base_url"].rstrip("/") + "/browse/" + quote(key, safe=""),
                    fields.get("updated") or hashlib.sha256(text.encode()).hexdigest(), fields.get("updated"), item)
                # BROWSE_PROJECTS alone is not proof of every issue-security
                # rule. Do not publish security-level issues in this first
                # adapter without a delegated end-user visibility check.
                if "security" not in fields or fields["security"] is not None:
                    document.acl, document.permission_state = [], "unknown"
                    document.permission_basis = "issue security requires delegated user visibility verification"
                yield document
            next_cursor = batch.get("nextPageToken")
            if not next_cursor:
                if batch.get("isLast") is False:
                    raise SourceError("jira_pagination_incomplete")
                break
            if next_cursor == cursor:
                raise SourceError("source_pagination_cycle")
            cursor = next_cursor


class ConfluenceAdapter(SourceAdapter):
    def permissions(self, page_id):
        grants, evidence = [], []
        for account_id, principal in self.mapping.items():
            result = self.http.request("/wiki/rest/api/content/" + quote(str(page_id), safe="") + "/permission/check",
                body={"subject": {"type": "user", "identifier": account_id}, "operation": "read"})
            if type(result.get("hasPermission")) is not bool:
                raise SourceError("confluence_permission_format_unknown")
            evidence.append({"account_id": account_id, "result": result})
            if result["hasPermission"]:
                grants.append(principal)
        return grants, evidence

    def records(self):
        spaces = self.config.get("space_ids", [])
        if not isinstance(spaces, list) or not spaces or len(spaces) > 20:
            raise ValueError("explicit Confluence space IDs required (1..20)")
        for space in spaces:
            path, params, seen = "/wiki/api/v2/spaces/" + quote(str(space), safe="") + "/pages", {"body-format": "storage", "limit": 100, "status": "current"}, set()
            while path:
                if path in seen:
                    raise SourceError("source_pagination_cycle")
                seen.add(path)
                batch = self.http.request(path, params=params)
                for page in batch.get("results", []):
                    parser = _HTMLText()
                    parser.feed(page.get("body", {}).get("storage", {}).get("value", ""))
                    revision = page.get("version", {})
                    url = self.config["base_url"].rstrip("/") + "/wiki/spaces/" + quote(str(space), safe="") + "/pages/" + quote(str(page["id"]), safe="")
                    yield self.document(page["id"], page.get("title", ""), "".join(parser.parts), url,
                        revision.get("number", "unknown"), revision.get("createdAt"), page)
                path, params = batch.get("_links", {}).get("next"), None


class SlackAdapter(SourceAdapter):
    def __init__(self, config, http=None):
        if config.get("base_url") != "https://slack.com/api":
            raise ValueError("Slack uses its fixed official API origin")
        super().__init__(config, http)
        self.channel_permissions = {}

    def pages(self, method, key, **params):
        cursor = None
        while True:
            batch = self.http.request(method, params=params | {"limit": 100, **({"cursor": cursor} if cursor else {})})
            yield from batch.get(key, [])
            next_cursor = batch.get("response_metadata", {}).get("next_cursor")
            if not next_cursor:
                if batch.get("has_more") is True:
                    raise SourceError("slack_pagination_incomplete")
                break
            if next_cursor == cursor:
                raise SourceError("source_pagination_cycle")
            cursor = next_cursor

    def permissions(self, resource_id):
        channel = str(resource_id).split(":", 1)[0]
        if channel not in self.channel_permissions:
            members = list(self.pages("conversations.members", "members", channel=channel))
            grants = []
            for member in members:
                if member in self.mapping:
                    user = self.http.request("users.info", params={"user": member}).get("user", {})
                    if "deleted" not in user:
                        raise SourceError("slack_user_state_unknown")
                    if user["deleted"] is False:
                        grants.append(self.mapping[member])
            # Conservative subset even for public channels: no workspace-wide grant.
            self.channel_permissions[channel] = (grants, {"channel": channel, "members": members,
                "coverage": "active mapped current members only"})
        return self.channel_permissions[channel]

    def records(self):
        channels = self.config.get("channel_ids", [])
        if not isinstance(channels, list) or not channels or len(channels) > 20:
            raise ValueError("explicit Slack channel IDs required (1..20)")
        for channel in channels:
            for message in self.pages("conversations.history", "messages", channel=channel):
                ts = message.get("ts")
                if not ts or message.get("thread_ts", ts) != ts:
                    continue
                thread = list(self.pages("conversations.replies", "messages", channel=channel, ts=ts)) if message.get("reply_count") else [message]
                text = "\n".join(str(m.get("user", "bot")) + ": " + str(m.get("text", "")) for m in thread)
                latest = max(float(m.get("edited", {}).get("ts", m.get("ts", ts))) for m in thread)
                updated = datetime.fromtimestamp(latest, timezone.utc).isoformat()
                yield self.document(str(channel) + ":" + str(ts), "Slack thread " + str(channel) + " " + str(ts), text,
                    "https://app.slack.com/archives/" + quote(str(channel), safe="") + "/p" + str(ts).replace(".", ""),
                    hashlib.sha256(text.encode()).hexdigest(), updated, {"channel": channel, "thread": thread})


class DriveAdapter(SourceAdapter):
    def __init__(self, config, http=None):
        if config.get("base_url") != "https://www.googleapis.com/drive/v3":
            raise ValueError("Drive uses its fixed official API origin")
        super().__init__(config, http)

    def permissions(self, file_id):
        entries, cursor = [], None
        while True:
            result = self.http.request("files/" + quote(str(file_id), safe="") + "/permissions", params={
                "supportsAllDrives": "true", "pageSize": 100,
                "fields": "nextPageToken,permissions(id,type,role,emailAddress,deleted,expirationTime,permissionDetails,view)",
                **({"pageToken": cursor} if cursor else {})})
            entries.extend(result.get("permissions", []))
            next_cursor = result.get("nextPageToken")
            if not next_cursor:
                break
            if next_cursor == cursor:
                raise SourceError("source_pagination_cycle")
            cursor = next_cursor
        grants = []
        for p in entries:
            # Group/domain/link grants retained in raw evidence, not expanded or
            # guessed from email suffixes. Only explicit user grants are mapped.
            if p.get("type") != "user" or p.get("deleted") or p.get("view"):
                continue
            if p.get("role") not in {"owner", "organizer", "fileOrganizer", "writer", "commenter", "reader"}:
                continue
            if p.get("expirationTime") and datetime.fromisoformat(p["expirationTime"].replace("Z", "+00:00")) <= datetime.now(timezone.utc):
                continue
            principal = self.mapping.get(p.get("id")) or self.mapping.get(p.get("emailAddress", ""))
            if principal:
                grants.append(principal)
        return grants, {"entries": entries, "coverage": "explicit user grants; no group/domain expansion"}

    def records(self):
        folder = self.config.get("folder_id")
        if not isinstance(folder, str) or not folder or any(c in folder for c in "'\\"):
            raise ValueError("explicit Drive folder ID required")
        cursor = None
        while True:
            result = self.http.request("files", params={"q": "'%s' in parents and trashed = false" % folder,
                "supportsAllDrives": "true", "includeItemsFromAllDrives": "true", "pageSize": 100,
                "fields": "nextPageToken,files(id,name,mimeType,modifiedTime,version,webViewLink)",
                **({"pageToken": cursor} if cursor else {})})
            for file in result.get("files", []):
                mime, identifier = file.get("mimeType", ""), str(file["id"])
                if mime == "application/vnd.google-apps.folder":
                    continue  # Folder scope is direct children, not implicit recursion.
                exports = {"application/vnd.google-apps.document": "text/plain", "application/vnd.google-apps.spreadsheet": "text/csv"}
                if mime in exports:
                    text = self.http.request("files/" + quote(identifier, safe="") + "/export", params={"mimeType": exports[mime]}, text=True)
                elif mime in {"text/plain", "text/markdown", "text/csv"}:
                    text = self.http.request("files/" + quote(identifier, safe=""), params={"alt": "media"}, text=True)
                else:
                    # Metadata-only record is quarantined; PDF/OCR/slide parsers
                    # are not advertised as supported by this first adapter.
                    text = ""
                yield self.document(identifier, file.get("name", identifier), text,
                    file.get("webViewLink") or "https://drive.google.com/file/d/" + quote(identifier, safe="") + "/view",
                    file.get("version", "unknown"), file.get("modifiedTime"), file)
            next_cursor = result.get("nextPageToken")
            if not next_cursor:
                break
            if next_cursor == cursor:
                raise SourceError("source_pagination_cycle")
            cursor = next_cursor


ADAPTERS = {"jira": JiraAdapter, "confluence": ConfluenceAdapter, "slack": SlackAdapter, "google_drive": DriveAdapter}


def adapter_for(config, http=None):
    if config.get("source") not in ADAPTERS or config.get("enabled") is not True:
        raise ValueError("explicitly enabled supported source required")
    if config["source"] in {"jira", "confluence"}:
        host = urlparse(config.get("base_url", "")).hostname or ""
        if not host.endswith(".atlassian.net"):
            raise ValueError("first adapter supports Atlassian Cloud tenant origins only")
    return ADAPTERS[config["source"]](config, http)
