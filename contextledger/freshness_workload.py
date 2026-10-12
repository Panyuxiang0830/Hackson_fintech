"""Independent source truth and fixed, versioned freshness workloads."""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from pathlib import Path


def digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def key(record):
    return record["corpus"], record["doc_id"], record["version"]


def reference(revision):
    return {field: revision[field] for field in ("corpus", "doc_id", "version", "content_hash")}


class Workload:
    def __init__(self, data):
        self.data = data
        if data.get("schema_version") != 1:
            raise ValueError("unsupported freshness workload schema")
        self.revisions = {}
        for revision in data["revisions"]:
            identity = key(revision)
            if identity in self.revisions:
                raise ValueError("duplicate immutable revision")
            for field in ("corpus", "doc_id", "version", "title", "text", "source"):
                if not isinstance(revision[field], str) or not revision[field]:
                    raise ValueError("revision fields must be nonempty strings")
            if revision.get("content_hash") != digest(revision["text"]):
                raise ValueError("revision content hash mismatch")
            self.revisions[identity] = revision
        self.actors = {actor["id"]: actor for actor in data["actors"]}
        if len(self.actors) != len(data["actors"]) or not self.actors or any(
                not isinstance(alias, str) or not alias for alias in self.actors):
            raise ValueError("duplicate or empty actors")
        for revision in self.revisions.values():
            acl = revision["allowed_actors"]
            if not isinstance(acl, list) or any(actor not in self.actors for actor in acl):
                raise ValueError("revision ACL must reference workload actors")
        self.events = data["events"]
        self.queries = data["queries"]
        if not self.events or not self.queries:
            raise ValueError("events and queries must be nonempty")
        self._ids(self.events, "events")
        self._ids(self.queries, "queries")
        previous = -1
        for event in self.events:
            self._time(event["at_ms"])
            if event["at_ms"] < previous:
                raise ValueError("source events must be chronologically ordered")
            previous = event["at_ms"]
            if event.get("initial") and event["at_ms"] != 0:
                raise ValueError("initial state must precede the offered stream at time zero")
            if event["op"] not in {"upsert", "delete", "withdraw"}:
                raise ValueError("unsupported source event")
            if event["op"] == "upsert" and key(event) not in self.revisions:
                raise ValueError("event references an unknown revision")
            if event["op"] != "upsert" and not any(
                    identity[:2] == (event["corpus"], event["doc_id"]) for identity in self.revisions):
                raise ValueError("deletion references an unknown resource")
            self._time(event.get("delivery_delay_ms", 0))
        offered = [event["at_ms"] for event in self.events if not event.get("initial")]
        if not offered:
            raise ValueError("freshness workload must issue at least one source change")
        self.last_source_ms = max(offered)
        self.horizon_ms = data["horizon_ms"]
        self._time(self.horizon_ms)
        if self.horizon_ms < max(previous, max(query["at_ms"] for query in self.queries)):
            raise ValueError("workload horizon does not cover issued events/queries")
        self.query_map = {query["id"]: query for query in self.queries}
        self.event_map = {event["id"]: event for event in self.events}
        for query in self.queries:
            self._time(query["at_ms"])
            if query["actor_id"] not in self.actors or query["kind"] not in {"chasing", "regular", "negative", "static"}:
                raise ValueError("invalid query actor or kind")
            if not isinstance(query["query"], str) or not query["query"].strip():
                raise ValueError("query must be nonempty")
            if not query.get("targets") or len(set(query["targets"])) != len(query["targets"]):
                raise ValueError("query targets must be nonempty and unique")
            expected = self.gold(query)
            if query.get("gold") != expected:
                raise ValueError(f"gold differs from independent source truth: {query['id']}")
            if query.get("expect_empty") is not (not expected):
                raise ValueError("empty gold requires an explicit expect_empty label")
            anchor = query.get("anchor_event_id")
            if anchor and (anchor not in self.event_map or self.event_map[anchor]["at_ms"] > query["at_ms"]):
                raise ValueError("query age anchor must be an already-issued source event")
        self.sha256 = digest(json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":")))

    @staticmethod
    def _ids(records, name):
        ids = [record["id"] for record in records]
        if any(not isinstance(value, str) or not value for value in ids) or len(set(ids)) != len(ids):
            raise ValueError(f"duplicate or empty {name} ids")

    @staticmethod
    def _time(value):
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            raise ValueError("times must be finite nonnegative milliseconds")

    def state(self, at_ms):
        state, changes = {}, {}
        for event in self.events:
            if event["at_ms"] > at_ms:
                break
            resource = event["corpus"], event["doc_id"]
            state[resource] = self.revisions[key(event)] if event["op"] == "upsert" else None
            changes[resource] = event
        return state, changes

    def gold(self, query):
        state, _ = self.state(query["at_ms"])
        result = []
        for doc_id in query["targets"]:
            revision = state.get((query["corpus"], doc_id))
            if revision and query["actor_id"] in revision["allowed_actors"]:
                result.append(reference(revision))
        return sorted(result, key=key)

    def phase(self, query):
        if query["kind"] == "static":
            return "static_undrained"
        return "online" if query["at_ms"] <= self.last_source_ms else "recovery"

    def age(self, query):
        if query.get("anchor_event_id"):
            return query["at_ms"] - self.event_map[query["anchor_event_id"]]["at_ms"]
        _, changes = self.state(query["at_ms"])
        times = [changes[(query["corpus"], doc)]["at_ms"] for doc in query["targets"]
                 if (query["corpus"], doc) in changes]
        return query["at_ms"] - max(times) if times else None

    @classmethod
    def read(cls, path):
        return cls(json.loads(Path(path).read_text(encoding="utf-8")))


def example_workload(source_db=None, cases=24):
    """Controlled edits have explicit truth; optional OrgForge text is background."""
    if type(cases) is not int or not 1 <= cases <= 120:
        raise ValueError("cases must be 1..120")
    backgrounds = []
    provenance = {"type": "synthetic_enterprise_consistency_suite", "native_orgforge_answers": False}
    if source_db:
        uri = Path(source_db).resolve().as_uri() + "?mode=ro"
        with sqlite3.connect(uri, uri=True) as db:
            backgrounds = db.execute("SELECT doc_id,source,title,text FROM documents WHERE corpus='orgforge' ORDER BY source,doc_id LIMIT ?", (cases,)).fetchall()
        if not backgrounds:
            raise ValueError("source database contains no OrgForge documents")
        provenance.update(type="orgforge_context_with_controlled_counterfactual_edits",
                          source_documents=[row[0] for row in backgrounds],
                          background_sha256=digest(json.dumps(backgrounds, ensure_ascii=False)))
    data = {"schema_version": 1, "name": "enterprise-freshness-v1", "provenance": provenance,
            "actors": [{"id": "alice"}, {"id": "bob"}, {"id": "outside"}],
            "revisions": [], "events": [], "queries": [], "cases": []}
    corpus = "freshness_eval"

    def revision(doc_id, version, status, source, background=""):
        token = doc_id.replace("-", "")
        text = f"{token} current operational status: {status}.\nControlled freshness replay evidence, version {version}."
        if background:
            text += "\n\nOffline source context (controlled edit above is synthetic):\n" + background[:1600]
        record = {"corpus": corpus, "doc_id": doc_id, "version": version, "title": token + " status record",
                  "source": source, "text": text, "content_hash": digest(text), "allowed_actors": ["alice", "bob"]}
        data["revisions"].append(record)
        return record

    def event(identity, at_ms, doc, op="upsert", version=None, **extra):
        record = {"id": identity, "at_ms": at_ms, "corpus": corpus, "doc_id": doc["doc_id"], "op": op, **extra}
        if op == "upsert":
            record["version"] = version or doc["version"]
        data["events"].append(record)
        return record

    stable = revision("SteadyLedger", "v1", "approved", "confluence")
    event("initial-stable", 0, stable, initial=True)
    kinds = ("add", "update", "delete", "withdraw", "rollback", "late_delivery")
    for number in range(cases):
        case_id = f"case-{number + 1:02d}"
        doc_id = f"FreshLedger{number + 1:02d}"
        kind = kinds[number % len(kinds)]
        source = ("confluence", "jira", "slack", "google_drive")[number % 4]
        background = backgrounds[number % len(backgrounds)][3] if backgrounds else ""
        first = revision(doc_id, "v1", "pending approval", source, background)
        second = revision(doc_id, "v2", "approved for rollout", source, background)
        third = revision(doc_id, "v3", "rollout paused", source, background) if kind == "late_delivery" else None
        at_ms = 100 + number * 2000
        data["cases"].append({"id": case_id, "kind": kind, "source": source, "doc_id": doc_id})
        if kind != "add":
            event("initial-" + case_id, 0, second if kind == "rollback" else first, initial=True)
        if kind in {"delete", "withdraw"}:
            event("change-" + case_id, at_ms, first, op=kind)
        elif kind == "rollback":
            event("change-" + case_id, at_ms, first)
        elif kind == "late_delivery":
            event("late-" + case_id, at_ms, second, delivery_delay_ms=700)
            event("change-" + case_id, at_ms + 100, third)
            at_ms += 100
        else:
            event("change-" + case_id, at_ms, second)
        for age in (0, 100, 499, 500, 1000, 1500):
            for label, target in (("chasing", doc_id), ("regular", stable["doc_id"])):
                data["queries"].append({"id": f"{case_id}-{label}-{age}", "case_id": case_id,
                    "anchor_event_id": "change-" + case_id,
                    "at_ms": at_ms + age, "actor_id": "alice", "corpus": corpus, "kind": label,
                    "query": target.replace("-", "") + " current operational status", "targets": [target]})
        data["queries"].append({"id": case_id + "-outside", "case_id": case_id, "at_ms": at_ms + 1000,
            "actor_id": "outside", "corpus": corpus, "kind": "negative",
            "query": doc_id + " current operational status", "targets": [doc_id]})
    data["events"].sort(key=lambda record: record["at_ms"])
    final_at = max(record["at_ms"] for record in data["events"])
    for case in data["cases"]:
        data["queries"].append({"id": case["id"] + "-static", "case_id": case["id"], "at_ms": final_at,
            "actor_id": "alice", "corpus": corpus, "kind": "static", "query": case["doc_id"] + " current operational status",
            "targets": [case["doc_id"]]})
    data["queries"].sort(key=lambda record: (record["at_ms"], record["id"]))
    # Freeze gold using source events, before any serving adapter exists.
    source = object.__new__(Workload)
    source.events = data["events"]
    source.revisions = {key(record): record for record in data["revisions"]}
    for query in data["queries"]:
        query["gold"] = source.gold(query)
        query["expect_empty"] = not query["gold"]
    data["horizon_ms"] = max(record["at_ms"] for record in data["queries"])
    return Workload(data)
