from __future__ import annotations

import io
import json
import struct
import zipfile
from pathlib import Path

import pytest
from bson import BSON

from contextledger.demo_app import create_app
from contextledger.models import CanonicalDoc, Principal
from contextledger.remote_zip import RemoteZipReader
from contextledger.search import open_document
from contextledger.store import connect, init_db, insert_documents, insert_principals
from contextledger.supplemental import archive_records, jira_batch, privacy_batch, save_batch


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


@pytest.fixture
def privacy_export(tmp_path):
    world = "fixture"
    root = tmp_path / "export"
    slack = root / "tasks" / world / "slack"
    write_json(root / "ground_truth" / world / "characters.json", {
        "alice": {"canonical_name": "Alice", "emails": [{"value": "alice@work.test"}, {"value": "alice@home.test"}], "slack_handles": ["UA"]},
        "bob": {"canonical_name": "Bob", "emails": [{"value": "bob@work.test"}], "slack_handles": ["UB"]},
        "eve": {"canonical_name": "Eve", "emails": [{"value": "eve@external.test"}], "slack_handles": ["UE"]},
    })
    write_json(slack / "users.json", [{"id": key, "name": key, "profile": {"email": email}} for key, email in [("UA", "alice@work.test"), ("UB", "bob@work.test"), ("UE", "eve@external.test")]])
    write_json(slack / "channels.json", [])
    write_json(slack / "groups.json", [])
    write_json(slack / "dms.json", [{"id": "D0", "members": ["UA", "UB"]}])
    write_json(slack / "mpims.json", [])
    write_json(slack / "D0" / "2026-01-01.json", [
        {"ts": "1767225600.0", "user": "UA", "text": "private budget alpha"},
        {"ts": "1767225610.0", "thread_ts": "1767225600.0", "user": "UB", "text": "private reply beta"},
    ])
    drive = root / "tasks" / world / "drive"
    drive.mkdir(parents=True)
    (drive / "budget.csv").write_text("team,budget\nalpha,1234\n", encoding="utf-8")
    write_json(drive / "files.json", {"files": [{"id": "F1", "name": "budget.csv", "mimeType": "text/csv", "modifiedTime": "2026-01-01T00:00:00Z", "permissions": [{"type": "user", "role": "reader", "emailAddress": "alice@home.test"}]}]})
    return root, world


def store(tmp_path):
    out = tmp_path / "store"
    c = connect(out / "canonical.sqlite")
    init_db(c)
    c.close()
    return out


def test_export_permissions_aliases_and_thread_grouping(privacy_export, tmp_path):
    root, world = privacy_export
    batch = privacy_batch(root, world, "pinned")
    assert len(batch.records) == 2
    dm = next(record for record in batch.records if record[0].source == "slack")
    drive = next(record for record in batch.records if record[0].source == "google_drive")
    assert dm[1] == ["privacy_fixture:alice", "privacy_fixture:bob"]
    assert dm[0].extra["message_count"] == 2
    assert "private reply beta" in dm[0].text
    assert drive[1] == ["privacy_fixture:alice"]
    assert "alpha | 1234" in drive[0].text
    out = store(tmp_path)
    save_batch(out, batch)
    c = connect(out / "canonical.sqlite")
    try:
        for principal in ("privacy_fixture:eve", "privacy_fixture:outside"):
            assert open_document(c, corpus=batch.corpus, principal_id=principal, doc_id=dm[0].doc_id) is None
            assert open_document(c, corpus=batch.corpus, principal_id=principal, doc_id="F1") is None
        assert open_document(c, corpus=batch.corpus, principal_id="privacy_fixture:alice", doc_id="F1")["metadata"]["mime_type"] == "text/csv"
        assert open_document(c, corpus="other", principal_id="privacy_fixture:alice", doc_id="F1") is None
    finally:
        c.close()


def test_unresolved_group_permissions_deny(privacy_export):
    root, world = privacy_export
    path = root / "tasks" / world / "drive" / "files.json"
    data = json.loads(path.read_text())
    data["files"][0]["permissions"] = [{"type": "group", "role": "reader", "emailAddress": "staff@work.test"}]
    write_json(path, data)
    drive = next(record for record in privacy_batch(root, world, "pinned").records if record[0].source == "google_drive")
    assert drive[1] == []
    assert drive[0].extra["unresolved_permissions"]


def test_deleted_slack_account_does_not_override_drive_permission(privacy_export):
    root, world = privacy_export
    path = root / "tasks" / world / "slack" / "users.json"
    users = json.loads(path.read_text())
    users[0]["deleted"] = True
    write_json(path, users)
    records = privacy_batch(root, world, "pinned").records
    dm = next(record for record in records if record[0].source == "slack")
    drive = next(record for record in records if record[0].source == "google_drive")
    assert "privacy_fixture:alice" not in dm[1]
    assert "privacy_fixture:alice" in drive[1]


def test_repeat_import_preserves_other_corpora_and_indexes(privacy_export, tmp_path):
    root, world = privacy_export
    out = store(tmp_path)
    batch = privacy_batch(root, world, "pinned")
    save_batch(out, batch)
    original = out / "vectors" / "orgforge" / "ivf.index"
    original.parent.mkdir(parents=True)
    original.write_bytes(b"original index")
    new = out / "vectors" / batch.corpus / "ivf.index"
    new.parent.mkdir(parents=True)
    new.write_bytes(b"supplemental index")
    save_batch(out, privacy_batch(root, world, "pinned"))
    assert new.read_bytes() == b"supplemental index"
    path = root / "tasks" / world / "drive" / "budget.csv"
    path.write_text("team,budget\nalpha,9999\n")
    save_batch(out, privacy_batch(root, world, "pinned"))
    assert not new.exists()
    assert original.read_bytes() == b"original index"
    c = connect(out / "canonical.sqlite")
    try:
        assert c.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 2
        assert c.execute("SELECT COUNT(*) FROM docs_fts WHERE docs_fts MATCH '1234'").fetchone()[0] == 0
        assert c.execute("SELECT COUNT(*) FROM docs_fts WHERE docs_fts MATCH '9999'").fetchone()[0] == 1
    finally:
        c.close()


def test_jira_native_comments_changes_and_links():
    issue = {"key": "TEST-1", "fields": {"summary": "Outage", "project": {"key": "TEST"}, "status": {"name": "Resolved"}, "comments": [{"body": "Fix deployed", "created": "2026-01-02", "author": {"name": "anon"}}], "issuelinks": [{"outwardIssue": {"key": "TEST-2"}}]}, "changelog": {"histories": [{"created": "2026-01-02", "items": [{"field": "status", "fromString": "Open", "toString": "Resolved"}]}]}}
    batch = jira_batch("JiraReposAnon.Jira", [issue], {"dataset": "Public Jira", "revision": "fixed", "url": "https://zenodo.org/records/15719919", "synthetic": False})
    doc = batch.records[0][0]
    assert "Fix deployed" in doc.text
    assert "Open -> Resolved" in doc.text
    assert doc.extra["comment_count"] == doc.extra["change_count"] == 1
    assert doc.extra["issue_links"][0]["outwardIssue"]["key"] == "TEST-2"
    assert doc.extra["native_private_acl_available"] is False


def archive_bytes():
    term = b"\xff" * 4
    return struct.pack("<I", 0x8199E26D) + BSON.encode({"version": "0.1"}) + BSON.encode({"db": "db", "collection": "one"}) + term + BSON.encode({"db": "db", "collection": "one"}) + BSON.encode({"key": "ONE-1"}) + term + BSON.encode({"db": "db", "collection": "two"}) + BSON.encode({"key": "TWO-1"}) + term


def test_archive_parser_keeps_namespaces_and_rejects_truncation():
    data = archive_bytes()
    assert list(archive_records(io.BytesIO(data))) == [("db.one", {"key": "ONE-1"}), ("db.two", {"key": "TWO-1"})]
    with pytest.raises(ValueError, match="truncated"):
        list(archive_records(io.BytesIO(data[:-4])))


def test_range_reader_with_zip64_and_rejected_full_response(monkeypatch):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        with archive.open("record.txt", "w", force_zip64=True) as record:
            record.write(b"independent fixture")
    payload = buffer.getvalue()
    class Response:
        def __init__(self, start, end):
            self.status_code = 206
            self.headers = {"Content-Range": f"bytes {start}-{end}/{len(payload)}"}
            self.content = payload[start : end + 1]
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
    def fetch(url, *, headers, **kwargs):
        start, end = map(int, headers["Range"].split("=")[1].split("-"))
        return Response(start, end)
    reader = RemoteZipReader("https://example.test/archive", len(payload), block_size=19)
    monkeypatch.setattr(reader.session, "get", fetch)
    with zipfile.ZipFile(reader) as archive:
        assert archive.read("record.txt") == b"independent fixture"
    reader.close()
    reader = RemoteZipReader("https://example.test/archive", len(payload))
    response = Response(0, len(payload) - 1)
    response.status_code = 200
    monkeypatch.setattr(reader.session, "get", lambda *args, **kwargs: response)
    with pytest.raises(RuntimeError, match="byte range"):
        reader.read(4)
    reader.close()


def test_public_routes_default_day_and_hide_candidate_metadata(tmp_path):
    out = store(tmp_path)
    c = connect(out / "canonical.sqlite")
    principal = Principal("orgforge", "orgforge:Jordan", "Jordan", "employee", "Engineering", 0, 11)
    doc = CanonicalDoc("orgforge", "hidden", "confluence", "incident", "incident", 1, None, "", [], [principal.principal_id], "fixture", "1", "x", {}, [])
    with c:
        insert_principals(c, [principal], {})
        insert_documents(c, [doc], [])
    c.close()
    client = create_app(out / "canonical.sqlite").test_client()
    result = client.get("/api/search?corpus=orgforge&principal=orgforge:Jordan&q=incident&mode=keyword")
    assert result.status_code == 200
    assert result.json == {"hits": [], "mode": "keyword"}
    assert client.get("/api/search?corpus=orgforge&principal=orgforge:Jordan&q=incident&mode=keyword&as_of=8").json["hits"]
    assert client.get("/api/doc?corpus=orgforge&principal=orgforge:Jordan&doc_id=hidden").status_code == 404
    assert client.get("/api/search?as_of=invalid&mode=keyword").status_code == 400
