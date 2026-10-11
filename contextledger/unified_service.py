"""One application boundary for Part A evidence, answers, ACL and query audit."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
import uuid
import re
import json

from contextledger.audit_store import AuditStore
from contextledger.filtered_index import FilteredIndex, IndexUnavailable, POLICY_VERSION
from contextledger.identity_store import Actor, IdentityStore
from contextledger.store import connect
from contextledger.search import entity_terms, contains_terms
from contextledger.llm_workflows import (AuditAnswerer, CitationReviewer, QueryPlanner,
                                        TOP_K, PLAN_VERSION, AUDIT_VERSION, review_refusal,
                                        review_feedback, revision_notice)
from src.answering import AnswerService, PROMPT_VERSION, empty_evidence_answer
from src.audit_query import AuditQueryParser
from src.audit import AuditIntegrityError
from src.models import Document, Evidence, User


class PermissionChanged(RuntimeError):
    pass


def timestamp():
    return datetime.now(timezone.utc).isoformat()


class UnifiedService:
    def __init__(self, index: FilteredIndex, identities: IdentityStore, audit: AuditStore, answer=None,
                 *, planner=None, reviewer=None, audit_answerer=None):
        self.index, self.identities, self.audit = index, identities, audit
        self.answer = answer or AnswerService()
        self.planner = planner or QueryPlanner()
        self.reviewer = reviewer or CitationReviewer()
        self.audit_answerer = audit_answerer or AuditAnswerer()
        self.identity_mode = "trusted_service"

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
            "identity_mode": self.identity_mode,
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

    def retrieve(self, actor, corpus, query, mode, day, planning=None, limit=TOP_K):
        """One bounded plan, <=5 authorised branches, one final document Top-K."""
        if planning is not None and type(planning) is not bool:
            raise ValueError("planning must be a boolean")
        if mode not in {"hybrid", "keyword", "vector"}:
            raise ValueError("unknown retrieval mode")
        scope = self.index.scope(actor, corpus, day)
        denied_all = not scope.principals or any("*" in scope.denied.get(k, [])
            for k in ("source", "project", "department", "document"))
        if denied_all:
            self.fence(actor)
            return [], None, scope, {"status": "skipped", "prompt_version": PLAN_VERSION,
                                    "attempts": 0, "branch_count": 0}
        # Pin the snapshot before planning, without reading business candidates.
        with connect(self.index.db_path) as db:
            db.execute("BEGIN")
            generation = self.index.consistent(db, corpus)["generation"]
        guard = lambda: self.fence(actor, corpus, generation)
        guard()
        plan, diagnostics = self.planner.plan(query, guard, planning)
        guard()
        if plan and plan["needs_clarification"]:
            return [], generation, scope, diagnostics | {"plan": plan, "branch_count": 0}
        branches = self.planner.branches(query, mode, plan)
        scores, selected, order = {}, {}, {}
        original_entities = entity_terms(query)
        for branch_mode, phrase in branches:
            guard()
            hits, branch_generation = self.index.search(scope, phrase, mode=branch_mode, limit=limit)
            if branch_generation != generation:
                raise IndexUnavailable("Index generation changed during retrieval planning; retry.")
            self.fence(actor, corpus, generation, hits)
            for rank, hit in enumerate(hits, 1):
                if original_entities and not any(contains_terms(hit["full_text"], [term]) for term in original_entities):
                    continue  # Generic keywords cannot substitute unrelated entities.
                key = (hit["corpus"], hit["doc_id"])
                order.setdefault(key, len(order))
                selected.setdefault(key, hit)
                scores[key] = scores.get(key, 0) + 1 / (60 + rank)
        ranked = sorted(scores, key=lambda k: (-scores[k], order[k]))[:limit]
        hits = [selected[key] for key in ranked]
        self.fence(actor, corpus, generation, hits)
        return hits, generation, scope, diagnostics | {"plan": plan, "branch_count": len(branches),
                                                       "top_k": limit, "fusion": "document RRF"}

    def search(self, user_id, corpus, query, mode="hybrid", day=None, *, planning=None):
        actor = self.current(user_id)
        hits, generation, scope, plan = self.retrieve(actor, corpus, query, mode, day, planning)
        suggestions = self.index.suggestions(scope, query) if not hits and plan["status"] != "clarification_required" else []
        self.fence(actor, corpus, generation, hits)
        event = self.record(actor, "search", question=query, hits=hits, mode=mode,
                            corpus=corpus, index_generation=generation, as_of=scope.day, query_plan=plan)
        return {"hits": [self.public_hit(hit) for hit in hits], "mode": mode,
                "request_id": event["request_id"], "permission_epoch": actor.epoch,
                "index_generation": generation, "query_suggestions": suggestions,
                "query_plan": plan, "scope": "offline ACL snapshot + system-local permissions"}, hits

    def ask(self, user_id, corpus, query, mode="hybrid", day=None, *, planning=None):
        actor = self.current(user_id)
        hits, generation, scope, plan = self.retrieve(actor, corpus, query, mode, day, planning)
        suggestions = self.index.suggestions(scope, query) if not hits and plan["status"] != "clarification_required" else []
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
        review = {"status": "not_required", "attempts": 0}
        feedback, notice = [], ""
        regeneration = {"status": "not_required", "attempts": 0}
        try:
            guard = lambda: self.fence(actor, corpus, generation, hits)
            kwargs = {"before_call": lambda: self.fence(actor, corpus, generation, hits)} if isinstance(self.answer, AnswerService) else {}
            if plan["status"] == "clarification_required":
                answer = "请确认问题中的名称、时间和具体意图后重新提问；系统不会自动更换实体或问题含义。" if re.search(r"[\u4e00-\u9fff]", query) else "Please confirm the names, time constraints and intended meaning. No entity or intent was automatically replaced."
                decision, provider = "clarification_required", "deterministic"
            elif not hits:
                answer, decision, provider = empty_evidence_answer(query), "insufficient", "deterministic"
            else:
                answer, decision, provider = self.answer.answer(user, query, evidence, **kwargs)
            diagnostics = getattr(self.answer, "last_diagnostics", {}) if hits else {"attempts": 0, "prompt_version": PROMPT_VERSION}
            diagnostics = diagnostics if isinstance(diagnostics, dict) else {}
            guard()
            if decision == "answered" and provider.startswith("openai_compatible/"):
                review = self.reviewer.review(query, answer,
                    [{"id": str(i), "content": e.document.content} for i, e in enumerate(evidence, 1)],
                    diagnostics.get("actual_model") or getattr(self.answer, "model", provider.split("/", 1)[-1]), guard,
                    generation_configured_model=getattr(self.answer, "model", provider.split("/", 1)[-1]))
                if review["status"] not in {"supported", "disabled"}:
                    feedback = review_feedback(review)
                    if isinstance(self.answer, AnswerService):
                        guard()
                        answer, decision, provider = self.answer.answer(user, query, evidence,
                            before_call=guard, revision={"previous_answer": answer[:16000], "review_feedback": feedback})
                        regeneration = self.answer.last_diagnostics | {"status": "failed"}
                        guard()
                        if decision == "answered" and provider.startswith("openai_compatible/"):
                            regeneration["status"] = "revised_not_reviewed"
                            notice = revision_notice(query)
                        elif provider.startswith("openai_compatible/"):
                            answer = empty_evidence_answer(query)
                            regeneration["status"] = "insufficient"
                    else:
                        answer, decision = review_refusal(query), "insufficient"
                else:
                    review.pop("_feedback", None)
            elif decision == "insufficient" and provider.startswith("openai_compatible/"):
                # A model can label an invented claim "insufficient". Release a
                # server-owned neutral refusal, not unchecked factual prose.
                answer = empty_evidence_answer(query)
            elif decision == "answered":
                review = {"status": "not_reviewed_mock", "attempts": 0}
            self.fence(actor, corpus, generation, hits)  # Also after a possibly slow LLM call.
        except (PermissionError, PermissionChanged, IndexUnavailable):
            self.record(actor, "answer_discarded", question=query, decision="permission_or_version_changed")
            raise
        if not hits and suggestions:
            answer += "\n你是否想查询：" + " / ".join(suggestions) + "？请确认名称后重新提问；系统未自动替换。"
        event = self.record(actor, "answer", question=query, hits=hits, answer=answer, decision=decision,
                            provider=provider, corpus=corpus, index_generation=generation, as_of=scope.day,
                            llm_diagnostics=diagnostics, query_plan=plan, citation_review=review,
                            regeneration=regeneration, answer_notice=notice)
        return {"answer": answer, "decision": decision, "provider": provider,
                "evidence": [self.public_hit(hit) | {"citation_id": i, "excerpt": hit["text"][:4000]}
                             for i, hit in enumerate(hits, 1)],
                "request_id": event["request_id"], "permission_epoch": actor.epoch,
                "query_suggestions": suggestions, "llm_diagnostics": diagnostics,
                "index_generation": generation, "query_plan": plan, "citation_review": review,
                "review_feedback": feedback, "regeneration": regeneration, "answer_notice": notice,
                "citation_validation": ("ID/scope validation only for revised answer; first review retained, no second semantic review"
                    if notice else "ID/scope/quote validation plus optional probabilistic separate-call model review; not independent proof")}, hits

    def open(self, user_id, corpus, doc_id, day=None):
        actor = self.current(user_id)
        scope = self.index.scope(actor, corpus, day)
        hit, generation = self.index.open(scope, doc_id)
        self.fence(actor, corpus, generation, [hit] if hit else [])
        self.record(actor, "document_open", hits=[hit] if hit else [], corpus=corpus,
                    decision="allowed" if hit else "unavailable", index_generation=generation)
        return ({"available": True, "doc": self.public_hit(hit, full=True),
                 "index_generation": generation} if hit else {"available": False}), hit

    def fence_audit(self, actor, guards):
        self.fence(actor)
        if self.current(actor.id).role not in {"admin", "compliance"}:
            raise PermissionError("compliance role required")
        if not self.audit.verify().valid:
            raise AuditIntegrityError("audit integrity changed during inquiry")
        for corpus, generation, hits in guards:
            self.fence(actor, corpus, generation, hits)

    def audit_query(self, actor_id, *, query="", generate=False, **filters):
        actor = self.current(actor_id)
        if actor.role not in {"admin", "compliance"}:
            raise PermissionError("compliance role required")
        if not isinstance(query, str) or len(query) > 4000 or type(generate) is not bool or (generate and not query.strip()):
            raise ValueError("audit question must contain 1..4000 characters")
        if any(k not in {"user_id", "request_id", "document_id", "start", "end", "limit"} for k in filters):
            raise ValueError("unsupported audit filter")
        if any(v is not None and (not isinstance(v, str) or len(v) > 200) for k,v in filters.items() if k != "limit"):
            raise ValueError("invalid audit filter")
        if query:
            users = {row["id"]: User(row["id"], row["name"], "", row["role"], "internal")
                     for row in self.identities.users()}
            parsed = AuditQueryParser().parse(query, users, [])
            filters = {**parsed, **{key: value for key, value in filters.items() if value}}
        maximum = filters.pop("limit", 100)
        if type(maximum) is not int or not 1 <= maximum <= 100:
            raise ValueError("audit limit must be 1..100")
        # Reading one extra item makes truncation explicit; no full-period total.
        events = self.audit.query(**filters, limit=maximum + 1)
        truncated = len(events) > maximum
        results, guards = [], []
        events = events[:maximum]
        for event in events:
            visible = bool(event.get("evidence"))
            local_guards = []
            for item in event.get("evidence", []):
                try:
                    scope = self.index.scope(actor, item["corpus"])
                    hit, generation = self.index.open(scope, item["doc_id"])
                    if not hit or hit["version"] != item["version"] or hit["content_hash"] != item.get("content_hash"):
                        visible = False
                        break
                    local_guards.append((item["corpus"], generation, [hit]))
                except IndexUnavailable:
                    visible = False
                    break
            # Whitelist projection: arbitrary extras/diagnostics may contain private
            # names or old model plans even after query/answer redaction.
            display = {k: event.get(k) for k in ("sequence", "request_id", "timestamp", "event_type",
                "user_id", "user_role", "permission_epoch", "policy_version", "decision", "identity_mode")}
            subject = self.identities.get(event.get("user_id"))
            display["user_name"] = subject.name if subject else "unknown account"
            display.update(query=str(event.get("query") or "")[:4000], answer=str(event.get("answer") or "")[:8000],
                evidence=event.get("evidence", []) if visible else [],
                retrieved_document_ids=event.get("retrieved_document_ids", []) if visible else [],
                authorization_decisions=event.get("authorization_decisions", []) if visible else [],
                returned_evidence_count=len(event.get("evidence", [])) if visible or not event.get("evidence") else None,
                redacted=not visible)
            if event.get("event_type") in {"permission_change", "permission_change_intent"}:
                change = event.get("change") or {}
                display["change"] = {k: change[k] for k in ("user_id", "action", "kind", "enabled", "denied", "role") if k in change}
            if not visible:
                for key in ("query", "answer"):
                    display[key] = "[redacted: evidence not currently authorised]" if display.get(key) else ""
            else:
                guards.extend(local_guards)
            results.append(display)
        guard = lambda: self.fence_audit(actor, guards)
        guard()
        selection = {"filters": filters, "returned_count": len(results), "truncated": truncated,
                     "limit": maximum, "not_whole_period_statistics": True}
        answer = (f"本次条件查询返回 {len(results)} 条事件。" if re.search(r"[\u4e00-\u9fff]", query) else f"This filtered selection returned {len(results)} events.")
        if results:
            answer += " " + " ".join(f"[E{e['sequence']}]" for e in results)
        else:
            answer += " 未匹配到事件不能证明从未发生访问。" if re.search(r"[\u4e00-\u9fff]", query) else " No matches do not prove access never occurred."
        provider, decision = "deterministic", "selection_only"
        diagnostics, review = {"attempts": 0, "prompt_version": AUDIT_VERSION}, {"status": "not_required", "attempts": 0}
        feedback, notice = [], ""
        regeneration = {"status": "not_required", "attempts": 0}
        event_ids = []
        if generate and results:
            # <=20 events and <=40k JSON chars. The model never receives entire logs.
            model_events, size = [], 0
            for e in results[:20]:
                projected = {k: e[k] for k in ("sequence", "timestamp", "event_type", "user_id", "user_name",
                    "user_role", "permission_epoch", "policy_version", "decision", "returned_evidence_count", "redacted")}
                projected.update(id=f"E{e['sequence']}", query=e["query"][:1000], answer=e["answer"][:1500])
                projected["evidence_ids"] = [item["doc_id"] for item in e["evidence"][:5]]
                projected["evidence_ids_truncated"] = len(e["evidence"]) > 5
                size += len(json.dumps(projected, ensure_ascii=False))
                if size > 40000:
                    break
                model_events.append(projected)
            selection.update(model_event_count=len(model_events),
                             truncated=truncated or len(model_events) < len(results))
            draft, diagnostics = self.audit_answerer.answer(query, model_events, selection, guard)
            if draft is not None:
                if draft["decision"] == "answered":
                    review = self.reviewer.review(query, draft["answer"],
                        [{"id": e["id"], "content": json.dumps(e, ensure_ascii=False)} for e in model_events],
                        diagnostics.get("actual_model") or self.audit_answerer.stage.model, guard, audit=True,
                        generation_configured_model=self.audit_answerer.stage.model, selection=selection)
                if draft["decision"] == "answered" and review["status"] in {"supported", "disabled"}:
                    review.pop("_feedback", None)
                    answer, decision = draft["answer"], draft["decision"]
                    event_ids = draft["citation_ids"]
                    provider = "openai_compatible/" + (diagnostics.get("actual_model") or self.audit_answerer.stage.model)
                elif draft["decision"] == "answered":
                    feedback = review_feedback(review)
                    revised, regeneration = self.audit_answerer.answer(query, model_events, selection, guard,
                        revision={"previous_answer": draft["answer"], "review_feedback": feedback})
                    guard()
                    if revised is not None and revised["decision"] == "answered":
                        answer, decision, event_ids = revised["answer"], revised["decision"], revised["citation_ids"]
                        provider = "openai_compatible/" + (regeneration.get("actual_model") or self.audit_answerer.stage.model)
                        regeneration["status"] = "revised_not_reviewed"
                        notice = revision_notice(query)
                    elif revised is not None:
                        regeneration["status"] = "insufficient"
            if provider == "deterministic":
                answer = ("未生成可靠的模型审计回答，以下为已脱敏的条件查询结果。\n\n" if re.search(r"[\u4e00-\u9fff]", query) else "No reliable model audit answer was produced. Showing the redacted filtered selection.\n\n") + answer
        if selection["truncated"]:
            answer += "\n\n本次仅读取部分匹配事件，不能据此统计整个时间段。" if re.search(r"[\u4e00-\u9fff]", query) else "\n\nOnly part of the matching events was read; this is not whole-period statistics."
        guard()
        # Store only the released answer, never failed drafts or reviewer excerpts.
        dependencies = {(h["corpus"], h["doc_id"]): h for _, _, hs in guards for h in hs}
        event = self.record(actor, "audit_answer" if generate else "audit_query", question=query,
            hits=list(dependencies.values()), answer=answer if generate else "", decision=decision,
            result_count=len(results), event_citation_ids=event_ids, provider=provider,
            llm_diagnostics=diagnostics, citation_review=review,
            regeneration=regeneration, answer_notice=notice)
        guard()  # After append as well as at HTTP delivery.
        return {"events": results, "integrity": asdict(self.audit.verify()), "answer": answer,
                "provider": provider, "decision": decision, "selection": selection,
                "request_id": event["request_id"], "llm_diagnostics": diagnostics, "citation_review": review,
                "review_feedback": feedback, "regeneration": regeneration, "answer_notice": notice,
                "privacy": "query/answer/evidence redacted unless current evidence access is verified",
                "_delivery_guards": guards}


def validate_security_path(content: Path, security: Path):
    content, security = content.resolve(), security.resolve()
    if content == security or content in security.parents or security in content.parents:
        raise ValueError("Security/audit state and rebuildable content must be separate non-nested directories.")
