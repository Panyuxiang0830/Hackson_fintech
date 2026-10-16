"""One application boundary for Part A evidence, answers, ACL and query audit."""

from __future__ import annotations

from dataclasses import asdict
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
import uuid
import re
import json

from contextledger.radar.tool import DecisionRadarTool
from contextledger.radar.protocol import identifiers
from contextledger.radar.resolution import NameSearchPlanner
from contextledger.audit.store import AuditStore
from contextledger.retrieval.filtered_index import FilteredIndex, IndexUnavailable, POLICY_VERSION
from contextledger.access.identity_store import Actor, IdentityStore
from contextledger.storage.store import connect
from contextledger.retrieval.search import entity_terms, contains_terms
from contextledger.answering.workflows import AuditAnswerer, QueryPlanner, TOP_K, PLAN_VERSION, AUDIT_VERSION
from contextledger.answering.service import AnswerService, PROMPT_VERSION, empty_evidence_answer
from contextledger.audit.query import AuditQueryParser
from contextledger.audit.chain import AuditIntegrityError
from contextledger.answering.models import Document, Evidence, User


class PermissionChanged(RuntimeError):
    pass


# The tool gateway installs an immutable request-local credential guard. It is
# never stored on the shared service instance or supplied by model arguments.
ACCESS_GUARD = ContextVar("contextledger_access_guard", default=None)


def timestamp():
    return datetime.now(timezone.utc).isoformat()


class UnifiedService:
    def __init__(self, index: FilteredIndex, identities: IdentityStore, audit: AuditStore, answer=None,
                 *, planner=None, audit_answerer=None, name_planner=None):
        self.index, self.identities, self.audit = index, identities, audit
        self.answer = answer or AnswerService()
        self.planner = planner or QueryPlanner()
        self.audit_answerer = audit_answerer or AuditAnswerer()
        self.name_planner = name_planner or NameSearchPlanner()
        self.identity_mode = "trusted_service"

    def current(self, user_id) -> Actor:
        actor = self.identities.get(user_id)
        if actor is None or not actor.enabled:
            raise PermissionError("account unavailable")
        return actor

    def fence(self, actor: Actor, corpus=None, generation=None, hits=()):
        guard = ACCESS_GUARD.get()
        if guard is not None:
            guard()
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
            "user_id": actor.id, "actor_name": actor.name, "user_role": actor.role, "permission_epoch": actor.epoch,
            "policy_version": POLICY_VERSION, "query": question, "answer": answer, "decision": decision,
            "identity_mode": self.identity_mode,
            "retrieved_document_ids": [hit["doc_id"] for hit in hits],
            "evidence": [{key: hit[key] for key in ("corpus", "doc_id", "version", "content_hash", "chunk_id", "title", "source") if key in hit} | {"project": hit.get("metadata", {}).get("project", "")} for hit in hits],
            "authorization_decisions": [{"document_id": hit["doc_id"], "allowed": True,
                "reason": "source ACL snapshot AND current system restrictions"} for hit in hits],
            "audit_scope": "actual returned candidates; no denied titles/content or whole-corpus scan log",
            **extra,
        })

    @staticmethod
    def public_hit(hit, *, full=False):
        return {key: value for key, value in hit.items() if key not in {"full_text", "text"}} | (
            {"text": hit["full_text"]} if full else {})

    def retrieve(self, actor, corpus, query, mode, day, planning=None, limit=TOP_K, *, resolve_names=False):
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
        discovery_clarification = bool(resolve_names and plan and plan["needs_clarification"]
            and not identifiers(query)
            and all(name.lower() in query.lower() for name in plan["entity_candidates"]))
        if plan and plan["needs_clarification"] and not discovery_clarification:
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
        name_diagnostics = {"status": "skipped", "attempts": 0}
        # Extend the ask path after PR7's unchanged plan/branches. Unknown explicit
        # Latin names without any lexical seed retain the existing safe refusal.
        if resolve_names and planning is not False and not identifiers(query) and (scores or not original_entities):
            name_plan, name_diagnostics = self.name_planner.plan(query, guard)
            if name_plan:
                name_diagnostics = name_diagnostics | {"plan": name_plan, "identity": "unconfirmed retrieval candidates"}
                for phrase in name_plan["search_phrases"]:
                    guard()
                    candidates, candidate_generation = self.index.search(scope, phrase,
                        mode=mode, limit=12, required_terms=name_plan["required_names"])
                    if candidate_generation != generation:
                        raise IndexUnavailable("Index changed during name discovery")
                    self.fence(actor, corpus, generation, candidates)
                    for rank, hit in enumerate(candidates, 1):
                        key = (hit["corpus"], hit["doc_id"])
                        order.setdefault(key, len(order))
                        selected.setdefault(key, hit)
                        scores[key] = scores.get(key, 0) + 1 / (60 + rank)
        ranked = sorted(scores, key=lambda k: (-scores[k], order[k]))[:limit]
        hits = [selected[key] for key in ranked]
        if discovery_clarification:
            # Search the supplied names before demanding an ID from the user.
            # Only resolve within a single explicitly identified incident family
            # in the authorised seed titles; other interpretations stay pending.
            families = {identifier for hit in hits for identifier in identifiers(hit["title"])
                        if identifier.startswith("ENG-")}
            if len(families) == 1:
                diagnostics = diagnostics | {"status": "resolved_candidate", "name_resolution": {
                    "entity_candidates": sorted(families), "basis": "authorised seed titles",
                    "global_identity_confirmed": False, "original_planner_status": "clarification_required"}}
                plan = {**plan, "needs_clarification": False}
        self.fence(actor, corpus, generation, hits)
        return hits, generation, scope, diagnostics | {"plan": plan, "branch_count": len(branches),
                                                       "top_k": limit, "fusion": "document RRF",
                                                       "name_search": name_diagnostics}

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

    def ask(self, user_id, corpus, query, mode="hybrid", day=None, *, planning=None, output_language=None):
        if output_language not in (None, "en"):
            raise ValueError("unsupported output_language")
        actor = self.current(user_id)
        hits, generation, scope, plan = self.retrieve(actor, corpus, query, mode, day, planning, resolve_names=True)
        suggestions = self.index.suggestions(scope, query) if not hits and plan["status"] != "clarification_required" else []
        self.fence(actor, corpus, generation, hits)  # Before any external model call.
        levels = ("public", "internal", "confidential", "restricted")
        user = User(actor.id, actor.name, actor.department or "source ACL snapshot", actor.role, levels[actor.clearance])
        radar = None
        radar_presentation = None
        evidence = []
        def build_evidence(total_budget=12000):
            evidence.clear()
            budget = total_budget // max(1, len(hits))
            for hit in hits:
                source_time = str(hit["metadata"].get("updated_at") or hit["ts"] or "unknown (offline export)")
                document = Document(hit["doc_id"], hit["source"], hit["title"], hit["text"][:min(4000, budget)],
                                    "unknown", source_time, source_time, hit["indexed_at"], "internal",
                                    status="historical" if hit["metadata"].get("historical_revision") else "active")
                evidence.append(Evidence(document, 1.0, "source ACL snapshot AND local restrictions",
                                         "consistent_with_offline_snapshot", "Live source freshness is unknown."))
        build_evidence()
        def run_radar(arguments):
            nonlocal radar
            selected, report = DecisionRadarTool(self.index).execute(query=query, scope=scope,
                generation=generation, seeds=hits, arguments=arguments, guard=guard)
            hits[:] = selected
            build_evidence(24000)
            report["coverage"]["evidence_excerpts_truncated"] = any(len(h["text"]) > len(e.document.content) for h, e in zip(hits, evidence))
            radar = report
            # Quotes are already in the unified evidence registry. Avoid duplicating
            # them in the model tool payload; the public timeline retains its spans.
            from contextledger.radar.timing import model_event
            model_report = {**report,
                "event_candidates": [model_event(event) for event in report["event_candidates"]],
                "source_statuses": [{k: v for k, v in item.items() if k in {"citation_id", "native_status", "historical", "supported_fact"}}
                                    for item in report["source_statuses"] if item["record_type"] == "native_state"]}
            return model_report
        try:
            guard = lambda: self.fence(actor, corpus, generation, hits)
            kwargs = {"before_call": guard, "tool_handler": run_radar} if isinstance(self.answer, AnswerService) else {}
            if isinstance(self.answer, AnswerService) and output_language:
                kwargs["output_language"] = output_language
            if plan["status"] == "clarification_required":
                answer = "请确认问题中的名称、时间和具体意图后重新提问；系统不会自动更换实体或问题含义。" if output_language != "en" and re.search(r"[\u4e00-\u9fff]", query) else "Please confirm the names, time constraints and intended meaning. No entity or intent was automatically replaced."
                decision, provider = "clarification_required", "deterministic"
            elif not hits:
                answer, decision, provider = empty_evidence_answer(query, output_language), "insufficient", "deterministic"
            else:
                answer, decision, provider = self.answer.answer(user, query, evidence, **kwargs)
            diagnostics = getattr(self.answer, "last_diagnostics", {}) if hits else {"attempts": 0, "prompt_version": PROMPT_VERSION}
            diagnostics = diagnostics if isinstance(diagnostics, dict) else {}
            if radar:
                radar_presentation = getattr(self.answer, "last_radar_presentation", None)
                if radar_presentation is None and (
                    decision == "insufficient" or radar.get("disagreements")
                    or any((radar.get("coverage") or {}).get(key) for key in
                           ("truncated", "evidence_excerpts_truncated", "model_input_truncated"))
                ):
                    available_ids = set(range(1, len(evidence) + 1))
                    needs = []
                    refs = []
                    for conflict in (radar.get("disagreements") or [])[:5]:
                        conflict_refs = list(dict.fromkeys(
                            claim.get("citation_id") for claim in conflict.get("claims", [])
                            if type(claim.get("citation_id")) is int and claim["citation_id"] in available_ids
                        ))
                        refs.extend(conflict_refs)
                        needs.append({
                            "item": f"Review the differing {conflict.get('attribute', 'reported')} values for {conflict.get('entity_id', 'this item')} and confirm their time and scope.",
                            "citation_ids": conflict_refs,
                        })
                    incomplete = any((radar.get("coverage") or {}).get(key) for key in
                                     ("truncated", "evidence_excerpts_truncated", "model_input_truncated"))
                    if incomplete:
                        needs.append({"item": "Review the records omitted by the bounded evidence selection.", "citation_ids": []})
                    if not needs:
                        needs.append({"item": "Find authorised evidence that establishes the requested business outcome.", "citation_ids": []})
                    radar_presentation = {
                        "status": "pending_confirmation",
                        "headline": "Conflicting reports need review." if radar.get("disagreements") else "The available evidence does not confirm this outcome.",
                        "explanation": "The authorised records do not yet establish a confirmed business outcome.",
                        "citation_ids": list(dict.fromkeys(refs)),
                        "needs_confirmation": needs[:5],
                    }
            guard()
            if decision == "insufficient" and provider.startswith("openai_compatible/"):
                # A model can label an invented claim "insufficient". Release a
                # server-owned neutral refusal, not unchecked factual prose.
                answer = empty_evidence_answer(query, output_language)
                if radar:
                    answer += ("\n\n本次已读取的授权记录尚未支持可靠结论；可展开时间线核对来源说法、未知时间和待确认分歧。" if output_language != "en" and re.search(r"[\u4e00-\u9fff]", query) else "\n\nThe authorised selection does not support a reliable conclusion; inspect the timeline for source reports, unknown times and unresolved differences.")
            self.fence(actor, corpus, generation, hits)  # Also after a possibly slow LLM call.
        except (PermissionError, PermissionChanged, IndexUnavailable):
            self.record(actor, "answer_discarded", question=query, decision="permission_or_version_changed")
            raise
        if not hits and suggestions:
            answer += ("\nDid you mean: " + " / ".join(suggestions) + "? Confirm the name and ask again; no entity was replaced." if output_language == "en" or not re.search(r"[\u4e00-\u9fff]", query) else "\n你是否想查询：" + " / ".join(suggestions) + "？请确认名称后重新提问；系统未自动替换。")
        event = self.record(actor, "answer", question=query, hits=hits, answer=answer, decision=decision,
                            provider=provider, corpus=corpus, index_generation=generation, as_of=scope.day,
                            llm_diagnostics=diagnostics, query_plan=plan,
                            radar_summary=radar["coverage"] if radar else None,
                            **({"radar_presentation": radar_presentation} if radar_presentation else {}))
        result = {"answer": answer, "decision": decision, "provider": provider,
                "evidence": [self.public_hit(hit) | {"citation_id": i, "excerpt": hit["text"][:4000]}
                             for i, hit in enumerate(hits, 1)],
                "request_id": event["request_id"], "permission_epoch": actor.epoch,
                "query_suggestions": suggestions, "llm_diagnostics": diagnostics,
                "index_generation": generation, "query_plan": plan,
                "radar": radar,
                "citation_validation": "citation IDs and authorised scope only; no model semantic review"}
        if radar_presentation:
            result["radar_presentation"] = radar_presentation
        return result, hits

    def open(self, user_id, corpus, doc_id, day=None):
        actor = self.current(user_id)
        scope = self.index.scope(actor, corpus, day)
        hit, generation = self.index.open(scope, doc_id)
        self.fence(actor, corpus, generation, [hit] if hit else [])
        event = self.record(actor, "document_open", hits=[hit] if hit else [], corpus=corpus,
                    decision="allowed" if hit else "unavailable", index_generation=generation,
                    requested_document_id=doc_id, unavailable_reason=None if hit else "not_found_or_not_authorised")
        return ({"available": True, "doc": self.public_hit(hit, full=True),
                 "index_generation": generation, "request_id": event["request_id"]} if hit else {"available": False}), hit

    def fence_audit(self, actor, guards):
        self.fence(actor)
        if self.current(actor.id).role not in {"admin", "compliance"}:
            raise PermissionError("compliance role required")
        if not self.audit.verify().valid:
            raise AuditIntegrityError("audit integrity changed during inquiry")
        for corpus, generation, hits in guards:
            self.fence(actor, corpus, generation, hits)

    def audit_console(self, actor_id, *, query="", generate=False, **filters):
        from contextledger.audit.console import select, question_filters, SGT
        actor=self.current(actor_id)
        if actor.role!='admin':
            raise PermissionError('administrator audit access required')
        if type(generate) is not bool or not isinstance(query,str) or len(query)>4000 or (generate and not query.strip()):
            raise ValueError('invalid audit question')
        self.fence_audit(actor, [])
        if query:
            projects=[]
            with self.identities.db() as db:
                projects=[{'id':r[0],'name':r[1]} for r in db.execute('SELECT id,name FROM project_catalog')]
            parsed=question_filters(query,self.identities,projects,parse_time=generate or not (filters.get("start") or filters.get("end")))
            # Explicit console filters win; a natural-language time overrides
            # the AI box's default range and is always shown in the result.
            filters={**parsed,**{k:v for k,v in filters.items() if v not in (None,'')}}
            if generate:
                for k in ('start','end'):
                    if k in parsed:filters[k]=parsed[k]
            elif set(parsed)=={'category'} and not re.search(r'谁|何时|查询|访问|权限|更新|越权|\b(who|when|today|yesterday|last|past)\b',query,re.I):
                filters['keyword']=query
        data=select(self.audit,self.index.db_path,self.identities,filters)
        sample=data.pop('_model_events')
        selection=data['selection']
        selection.update(statistics=data['statistics'],query_citation='Q1')
        chinese=bool(re.search(r"[\u4e00-\u9fff]",query))
        selection['response_language']='Chinese' if chinese else 'English'
        selection['time_range_sgt']={k:datetime.fromisoformat(v.replace('Z','+00:00')).astimezone(SGT).isoformat() for k,v in selection['filters'].items() if k in {'start','end'}}
        answer=(f"本次完整筛选共 {data['total_count']} 条审计事件。[Q1]" if chinese else f"{data['total_count']} matching audit events in this range. [Q1]")
        provider,decision='deterministic','selection_only'
        diagnostics={'attempts':0,'prompt_version':AUDIT_VERSION}
        cited=[]
        guard=lambda:self.fence_audit(actor, [])
        if generate and sample:
            model_events=[];size=0
            for event in sample:
                projection={k:event.get(k) for k in ('sequence','timestamp','event_type','category','user_id','user_name','target_user_id','target_user_name','decision','outcome','permission_epoch','operation_id','change','doc_id','job_id','before_version','before_version_status','version','source','title','corpus','error_type','endpoint','requested_document_id','unavailable_reason','authorization_decisions')}
                projection.update(id=f"E{event['sequence']}",timestamp_sgt=datetime.fromisoformat(event['timestamp'].replace('Z','+00:00')).astimezone(SGT).isoformat(),query=str(event.get('query') or '')[:1500],answer=str(event.get('answer') or '')[:2200],evidence=event.get('evidence',[])[:8],resources=event.get('resources',[])[:8])
                size+=len(json.dumps(projection,ensure_ascii=False))
                if size>40000:break
                model_events.append(projection)
            selection.update(model_event_count=len(model_events),truncated=len(model_events)<data['total_count'],
                             detail_scope='representative latest events per category; statistics cover all matches')
            model_selection={**selection,'page_returned_count':len(data['events']),'returned_count':len(model_events)}
            draft,diagnostics=self.audit_answerer.answer(query,model_events,model_selection,guard)
            if draft is not None:
                answer,decision=draft['answer'],draft['decision'];cited=draft['citation_ids']
                provider='openai_compatible/'+(diagnostics.get('actual_model') or self.audit_answerer.stage.model)
            else:
                answer='AI interpretation unavailable. The matching records and exact counts remain available.\n\n'+answer
        elif generate:
            answer=('所选范围没有匹配的审计记录，不能证明相关行为从未发生。[Q1]' if chinese else 'No matching audit records were found in the displayed range. This does not establish that an action never occurred. [Q1]')
        if generate and selection.get('truncated'):
            answer+=('\n\n明细仅展示部分事件；统计数量来自完整筛选结果。' if chinese else '\n\nEvent details are a partial selection; counts cover all matching records.')
        guard()
        recorded=self.record(actor,'audit_answer' if generate else 'audit_query',question=query,
            answer=answer if generate else '',decision=decision,provider=provider,
            result_count=data['total_count'],audit_filters=selection['filters'],event_citation_ids=cited,
            llm_diagnostics=diagnostics,statistics=data['statistics'])
        guard()
        data.update(answer=answer,provider=provider,decision=decision,request_id=recorded['request_id'],
                    llm_diagnostics=diagnostics,privacy='administrator full recorded audit view',_delivery_guards=[])
        return data

    def audit_query(self, actor_id, *, query="", generate=False, **filters):
        actor = self.current(actor_id)
        if actor.role not in {"admin", "compliance"}:
            raise PermissionError("compliance role required")
        if actor.role == "admin":
            if filters.get("user_id"):
                filters["actor"] = filters.pop("user_id")
            else:
                filters.pop("user_id", None)
            return self.audit_console(actor_id, query=query, generate=generate, **filters)
        if not isinstance(query, str) or len(query) > 4000 or type(generate) is not bool or (generate and not query.strip()):
            raise ValueError("audit question must contain 1..4000 characters")
        if any(k not in {"user_id", "request_id", "document_id", "start", "end", "limit"} for k in filters):
            raise ValueError("unsupported audit filter")
        if any(v is not None and (not isinstance(v, str) or len(v) > 200) for k,v in filters.items() if k != "limit"):
            raise ValueError("invalid audit filter")
        if query:
            users = {row["id"]: User(row["id"], row["name"], "", row["role"], "internal")
                     for row in self.identities.users()}
            parsed = AuditQueryParser().parse(query, users, [],
                parse_time=not bool(filters.get("start") or filters.get("end")))
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
            evidence_visibility = "visible" if visible else "not_recorded"
            local_guards = []
            for item in event.get("evidence", []):
                try:
                    scope = self.index.scope(actor, item["corpus"])
                    hit, generation = self.index.open(scope, item["doc_id"])
                    if not hit:
                        evidence_visibility = "current_access_unavailable"
                        visible = False
                        break
                    if hit["version"] != item["version"] or hit["content_hash"] != item.get("content_hash"):
                        evidence_visibility = "version_mismatch"
                        visible = False
                        break
                    local_guards.append((item["corpus"], generation, [hit]))
                except IndexUnavailable:
                    evidence_visibility = "index_unavailable"
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
                radar_presentation=event.get("radar_presentation") if visible else None,
                retrieved_document_ids=event.get("retrieved_document_ids", []) if visible else [],
                authorization_decisions=event.get("authorization_decisions", []) if visible else [],
                returned_evidence_count=len(event.get("evidence", [])) if visible or not event.get("evidence") else None,
                redacted=not visible, evidence_visibility=evidence_visibility)
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
        diagnostics = {"attempts": 0, "prompt_version": AUDIT_VERSION}
        event_ids = []
        if generate and results:
            # <=20 events and <=40k JSON chars. The model never receives entire logs.
            model_events, size = [], 0
            for e in results[:20]:
                projected = {k: e[k] for k in ("sequence", "timestamp", "event_type", "user_id", "user_name",
                    "user_role", "permission_epoch", "policy_version", "decision", "returned_evidence_count", "redacted", "evidence_visibility")}
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
            if draft is not None and draft["decision"] == "answered":
                answer, decision = draft["answer"], draft["decision"]
                event_ids = draft["citation_ids"]
                provider = "openai_compatible/" + (diagnostics.get("actual_model") or self.audit_answerer.stage.model)
            if provider == "deterministic":
                answer = ("未生成可靠的模型审计回答，以下为已脱敏的条件查询结果。\n\n" if re.search(r"[\u4e00-\u9fff]", query) else "No reliable model audit answer was produced. Showing the redacted filtered selection.\n\n") + answer
        if selection["truncated"]:
            answer += "\n\n本次仅读取部分匹配事件，不能据此统计整个时间段。" if re.search(r"[\u4e00-\u9fff]", query) else "\n\nOnly part of the matching events was read; this is not whole-period statistics."
        guard()
        # Store only the released answer, never failed model output.
        dependencies = {(h["corpus"], h["doc_id"]): h for _, _, hs in guards for h in hs}
        event = self.record(actor, "audit_answer" if generate else "audit_query", question=query,
            hits=list(dependencies.values()), answer=answer if generate else "", decision=decision,
            result_count=len(results), event_citation_ids=event_ids, provider=provider,
            llm_diagnostics=diagnostics)
        guard()  # After append as well as at HTTP delivery.
        return {"events": results, "integrity": asdict(self.audit.verify()), "answer": answer,
                "provider": provider, "decision": decision, "selection": selection,
                "request_id": event["request_id"], "llm_diagnostics": diagnostics,
                "privacy": "query/answer/evidence redacted unless current evidence access is verified",
                "_delivery_guards": guards}


def validate_security_path(content: Path, security: Path):
    content, security = content.resolve(), security.resolve()
    if content == security or content in security.parents or security in content.parents:
        raise ValueError("Security/audit state and rebuildable content must be separate non-nested directories.")
