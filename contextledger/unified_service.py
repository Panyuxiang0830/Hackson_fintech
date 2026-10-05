"""One application boundary for Part A evidence, answers, ACL and query audit."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
import uuid

from contextledger.audit_store import AuditStore
from contextledger.filtered_index import FilteredIndex, IndexUnavailable, POLICY_VERSION
from contextledger.identity_store import Actor, IdentityStore
from contextledger.store import connect
from src.answering import AnswerService
from src.audit_query import AuditQueryParser
from src.models import Document, Evidence, User


class PermissionChanged(RuntimeError):
    pass


def timestamp():
    return datetime.now(timezone.utc).isoformat()


class UnifiedService:
    def __init__(self, index: FilteredIndex, identities: IdentityStore, audit: AuditStore, answer=None):
        self.index, self.identities, self.audit = index, identities, audit
        self.answer = answer or AnswerService()

    def current(self, user_id) -> Actor:
        actor = self.identities.get(user_id)
        if actor is None or not actor.enabled:
            raise PermissionError("account unavailable")
        return actor

    def fence(self, actor: Actor, corpus=None, generation=None, hits=()):
        current = self.current(actor.id)
        if current.epoch != actor.epoch:
            raise PermissionChanged("Permissions changed; discard this response and retry.")
        if generation:
            with connect(self.index.db_path) as db:
                db.execute("BEGIN")
                state = self.index.consistent(db, corpus)
                if generation != state["generation"]:
                    raise IndexUnavailable("Index generation changed; retry.")
            scope = self.index.scope(current, corpus)
            for hit in hits:
                opened, _ = self.index.open(scope, hit["doc_id"])
                if not opened or opened["version"] != hit["version"] or opened["content_hash"] != hit["content_hash"]:
                    raise PermissionChanged("Evidence access or version changed; discard response.")

    def record(self, actor, event_type, *, question="", hits=(), answer="", decision="allowed", **extra):
        return self.audit.append({
            "request_id": str(uuid.uuid4()), "timestamp": timestamp(), "event_type": event_type,
            "user_id": actor.id, "user_role": actor.role, "permission_epoch": actor.epoch,
            "policy_version": POLICY_VERSION, "query": question, "answer": answer, "decision": decision,
            "retrieved_document_ids": [hit["doc_id"] for hit in hits],
            "evidence": [{key: hit[key] for key in ("corpus", "doc_id", "version", "content_hash", "chunk_id")} for hit in hits],
            "authorization_decisions": [{"document_id": hit["doc_id"], "allowed": True,
                "reason": "source ACL snapshot AND current system restrictions"} for hit in hits],
            "audit_scope": "actual returned candidates; no denied titles/content or whole-corpus scan log",
            **extra,
        })

    @staticmethod
    def public_hit(hit, *, full=False):
        return {key: value for key, value in hit.items() if key not in {"full_text", "text"}} | (
            {"text": hit["full_text"]} if full else {})

    def search(self, user_id, corpus, query, mode="hybrid", day=None):
        actor = self.current(user_id)
        scope = self.index.scope(actor, corpus, day)
        hits, generation = self.index.search(scope, query, mode=mode)
        self.fence(actor, corpus, generation, hits)
        event = self.record(actor, "search", question=query, hits=hits, mode=mode,
                            corpus=corpus, index_generation=generation, as_of=scope.day)
        return {"hits": [self.public_hit(hit) for hit in hits], "mode": mode,
                "request_id": event["request_id"], "permission_epoch": actor.epoch,
                "index_generation": generation, "scope": "offline ACL snapshot + system-local permissions"}, hits

    def ask(self, user_id, corpus, query, mode="hybrid", day=None):
        actor = self.current(user_id)
        scope = self.index.scope(actor, corpus, day)
        hits, generation = self.index.search(scope, query, mode=mode, limit=5)
        self.fence(actor, corpus, generation, hits)  # Before any external model call.
        levels = ("public", "internal", "confidential", "restricted")
        user = User(actor.id, actor.name, actor.department or "source ACL snapshot", actor.role, levels[actor.clearance])
        evidence = []
        for hit in hits:
            source_time = str(hit["metadata"].get("updated_at") or hit["ts"] or "unknown (offline export)")
            document = Document(hit["doc_id"], hit["source"], hit["title"], hit["text"][:4000],
                                "unknown", source_time, source_time, hit["indexed_at"], "internal")
            evidence.append(Evidence(document, 1.0, "source ACL snapshot AND local restrictions",
                                     "consistent_with_offline_snapshot", "Live source freshness is unknown."))
        answer, decision, provider = self.answer.answer(user, query, evidence)
        try:
            self.fence(actor, corpus, generation, hits)  # Also after a possibly slow LLM call.
        except (PermissionError, PermissionChanged, IndexUnavailable):
            self.record(actor, "answer_discarded", question=query, decision="permission_or_version_changed")
            raise
        event = self.record(actor, "answer", question=query, hits=hits, answer=answer, decision=decision,
                            provider=provider, corpus=corpus, index_generation=generation, as_of=scope.day)
        return {"answer": answer, "decision": decision, "provider": provider,
                "evidence": [self.public_hit(hit) | {"citation_id": i, "excerpt": hit["text"][:4000]}
                             for i, hit in enumerate(hits, 1)],
                "request_id": event["request_id"], "permission_epoch": actor.epoch,
                "index_generation": generation,
                "citation_validation": "number and authorised scope only; not semantic entailment"}, hits

    def open(self, user_id, corpus, doc_id, day=None):
        actor = self.current(user_id)
        scope = self.index.scope(actor, corpus, day)
        hit, generation = self.index.open(scope, doc_id)
        self.fence(actor, corpus, generation, [hit] if hit else [])
        self.record(actor, "document_open", hits=[hit] if hit else [], corpus=corpus,
                    decision="allowed" if hit else "unavailable", index_generation=generation)
        return ({"available": True, "doc": self.public_hit(hit, full=True),
                 "index_generation": generation} if hit else {"available": False}), hit

    def audit_query(self, actor_id, *, query="", **filters):
        actor = self.current(actor_id)
        if actor.role not in {"admin", "compliance"}:
            raise PermissionError("compliance role required")
        if query:
            users = {row["id"]: User(row["id"], row["name"], "", row["role"], "internal")
                     for row in self.identities.users()}
            parsed = AuditQueryParser().parse(query, users, [])
            filters = {**parsed, **{key: value for key, value in filters.items() if value}}
        events = self.audit.query(**filters)
        results = []
        for event in events:
            visible = bool(event.get("evidence"))
            for item in event.get("evidence", []):
                try:
                    scope = self.index.scope(actor, item["corpus"])
                    hit, _ = self.index.open(scope, item["doc_id"])
                    if not hit or hit["version"] != item["version"]:
                        visible = False
                        break
                except IndexUnavailable:
                    visible = False
                    break
            display = dict(event)
            if not visible:
                for key in ("query", "answer"):
                    display[key] = "[redacted: evidence not currently authorised]" if display.get(key) else ""
                display["evidence"] = []
                display["retrieved_document_ids"] = []
                display["authorization_decisions"] = []
            results.append(display)
        self.fence(actor)
        self.record(actor, "audit_query", question=query, result_count=len(results))
        return {"events": results, "integrity": asdict(self.audit.verify()),
                "answer": f"Found {len(results)} events. References: " + " ".join(f"[E{e['sequence']}]" for e in results),
                "privacy": "query/answer/evidence redacted unless current evidence access is verified"}


def validate_security_path(content: Path, security: Path):
    content, security = content.resolve(), security.resolve()
    if content == security or content in security.parents or security in content.parents:
        raise ValueError("Security/audit state and rebuildable content must be separate non-nested directories.")
