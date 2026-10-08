from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .answering import AnswerService
from .audit import AuditService, AuditVerification
from .audit_query import AuditQueryParser
from .freshness import FreshnessDecision, FreshnessService
from .identity import IdentityService
from .models import AnswerResult, Document, PolicyDecision, User
from .policy import PolicyEngine
from .retrieval import Retriever


AUDIT_ROLES = {"compliance_officer", "auditor"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class KnowledgeService:
    def __init__(
        self,
        documents: list[Document],
        audit_path: Path,
        users: dict[str, User] | None = None,
        policy: PolicyEngine | None = None,
        retriever: Retriever | None = None,
        answerer: AnswerService | None = None,
        freshness: FreshnessService | None = None,
        audit_query_parser: AuditQueryParser | None = None,
    ) -> None:
        self.documents = documents
        self.identities = IdentityService(users)
        self.policy = policy or PolicyEngine()
        self.retriever = retriever or Retriever()
        self.answerer = answerer or AnswerService()
        self.freshness = freshness or FreshnessService()
        self.audit_query_parser = audit_query_parser or AuditQueryParser()
        self.audit = AuditService(audit_path)

    def list_users(self) -> dict[str, User]:
        return self.identities.list_users()

    def get_user(self, user_id: str) -> User:
        return self.identities.get(user_id)

    def list_documents(self) -> list[Document]:
        return list(self.documents)

    def _resolve_user(self, user: User | str) -> User:
        return self.identities.resolve(user)

    def ask(self, user: User | str, question: str, limit: int = 5) -> AnswerResult:
        current_user = self._resolve_user(user)
        request_id = str(uuid4())
        authorised: list[tuple[Document, PolicyDecision]] = []
        freshness_by_id: dict[str, FreshnessDecision] = {}
        authorization_decisions: list[dict[str, Any]] = []
        freshness_decisions: list[dict[str, Any]] = []
        denied_count = 0
        stale_count = 0

        for document in self.documents:
            policy_decision = self.policy.evaluate(current_user, document)
            authorization_decisions.append(
                {
                    "document_id": document.id,
                    "allowed": policy_decision.allowed,
                    "reason": policy_decision.reason,
                }
            )
            if not policy_decision.allowed:
                denied_count += 1
                continue

            freshness_decision = self.freshness.evaluate(document)
            freshness_by_id[document.id] = freshness_decision
            freshness_decisions.append(
                {
                    "document_id": document.id,
                    "status": freshness_decision.status,
                    "servable": freshness_decision.servable,
                    "reason": freshness_decision.reason,
                    "indexed_updated_at": document.updated_at,
                    "source_updated_at": document.source_updated_at,
                    "synced_at": document.synced_at,
                    "sync_lag_minutes": freshness_decision.sync_lag_minutes,
                }
            )
            if not freshness_decision.servable:
                stale_count += 1
                continue
            authorised.append((document, policy_decision))

        evidence = self.retriever.retrieve(
            question,
            authorised,
            limit=limit,
            freshness_by_id=freshness_by_id,
        )
        answer, decision, answer_provider = self.answerer.answer(current_user, question, evidence)

        authorised_ids = {document.id for document, _ in authorised}
        evidence_ids = [item.document.id for item in evidence]
        if not set(evidence_ids).issubset(authorised_ids):
            raise RuntimeError("security invariant violated: unauthorised or stale evidence reached answering")

        record = {
            "event_type": "knowledge_query",
            "request_id": request_id,
            "timestamp": _now(),
            "user_id": current_user.id,
            "department": current_user.department,
            "role": current_user.role,
            "question": question,
            "authorization_decisions": authorization_decisions,
            "freshness_decisions": freshness_decisions,
            "authorised_document_count": len(authorised),
            "denied_document_count": denied_count,
            "stale_document_count": stale_count,
            "retrieved_document_ids": evidence_ids,
            "final_answer": answer,
            "decision": decision,
            "provider": answer_provider,
        }
        sealed = self.audit.append(record)
        safe_audit_summary = {
            key: sealed[key]
            for key in (
                "event_type",
                "request_id",
                "timestamp",
                "user_id",
                "authorised_document_count",
                "denied_document_count",
                "stale_document_count",
                "retrieved_document_ids",
                "decision",
                "provider",
                "sequence",
                "previous_hash",
                "event_hash",
            )
        }
        return AnswerResult(
            request_id=request_id,
            user=current_user,
            question=question,
            answer=answer,
            evidence=tuple(evidence),
            denied_document_count=denied_count,
            stale_document_count=stale_count,
            decision=decision,
            provider=answer_provider,
            audit_record=safe_audit_summary,
        )

    def audit_integrity(self) -> AuditVerification:
        return self.audit.verify()

    def query_audit(
        self,
        requester: User | str,
        *,
        user_id: str | None = None,
        request_id: str | None = None,
        document_id: str | None = None,
        start: str | None = None,
        end: str | None = None,
        query_text: str | None = None,
    ) -> list[dict[str, Any]]:
        actor = self._resolve_user(requester)
        allowed = actor.role in AUDIT_ROLES or actor.department == "compliance"
        filters = {
            "user_id": user_id,
            "request_id": request_id,
            "document_id": document_id,
            "start": start,
            "end": end,
        }
        if not allowed:
            self.audit.append(
                {
                    "event_type": "audit_query",
                    "request_id": str(uuid4()),
                    "timestamp": _now(),
                    "user_id": actor.id,
                    "department": actor.department,
                    "role": actor.role,
                    "question": query_text or "query audit trail",
                    "query_filters": filters,
                    "retrieved_document_ids": [],
                    "authorization_decisions": [],
                    "final_answer": "denied",
                    "decision": "denied",
                    "provider": "deterministic",
                }
            )
            raise PermissionError("audit queries require a compliance or auditor role")

        results = self.audit.query(**filters)
        self.audit.append(
            {
                "event_type": "audit_query",
                "request_id": str(uuid4()),
                "timestamp": _now(),
                "user_id": actor.id,
                "department": actor.department,
                "role": actor.role,
                "question": query_text or "query audit trail",
                "query_filters": filters,
                "retrieved_document_ids": [],
                "authorization_decisions": [],
                "final_answer": f"returned {len(results)} audit events",
                "result_count": len(results),
                "decision": "allowed",
                "provider": "deterministic",
            }
        )
        return results

    def query_audit_text(self, requester: User | str, query: str) -> list[dict[str, Any]]:
        filters = self.audit_query_parser.parse(
            query,
            self.identities.list_users(),
            self.documents,
        )
        return self.query_audit(requester, query_text=query, **filters)

    def revoke_project_access(self, actor: User | str, target_user_id: str, project: str) -> User:
        requester = self._resolve_user(actor)
        allowed = requester.role in AUDIT_ROLES or requester.department == "compliance"
        if allowed:
            updated = self.identities.revoke_project(target_user_id, project)
            decision = "allowed"
        else:
            updated = self.identities.get(target_user_id)
            decision = "denied"
        self.audit.append(
            {
                "event_type": "permission_change",
                "request_id": str(uuid4()),
                "timestamp": _now(),
                "user_id": requester.id,
                "department": requester.department,
                "role": requester.role,
                "target_user_id": target_user_id,
                "project": project,
                "action": "revoke",
                "retrieved_document_ids": [],
                "authorization_decisions": [],
                "final_answer": decision,
                "decision": decision,
                "provider": "deterministic",
            }
        )
        if not allowed:
            raise PermissionError("permission changes require a compliance or auditor role")
        return updated

    def reset_identity(self, actor: User | str, target_user_id: str) -> User:
        requester = self._resolve_user(actor)
        allowed = requester.role in AUDIT_ROLES or requester.department == "compliance"
        if allowed:
            updated = self.identities.reset(target_user_id)
            decision = "allowed"
        else:
            updated = self.identities.get(target_user_id)
            decision = "denied"
        self.audit.append(
            {
                "event_type": "permission_change",
                "request_id": str(uuid4()),
                "timestamp": _now(),
                "user_id": requester.id,
                "department": requester.department,
                "role": requester.role,
                "target_user_id": target_user_id,
                "action": "reset",
                "retrieved_document_ids": [],
                "authorization_decisions": [],
                "final_answer": decision,
                "decision": decision,
                "provider": "deterministic",
            }
        )
        if not allowed:
            raise PermissionError("permission changes require a compliance or auditor role")
        return updated

    def mark_source_updated(
        self,
        actor: User | str,
        document_id: str,
        source_updated_at: str | None = None,
    ) -> Document:
        requester = self._resolve_user(actor)
        allowed = requester.role in AUDIT_ROLES or requester.department == "compliance"
        updated_document: Document | None = None
        if allowed:
            for index, document in enumerate(self.documents):
                if document.id == document_id:
                    updated_document = replace(
                        document,
                        source_updated_at=source_updated_at or _now(),
                    )
                    self.documents[index] = updated_document
                    break
            if updated_document is None:
                raise KeyError(f"unknown document: {document_id}")

        decision = "allowed" if allowed else "denied"
        self.audit.append(
            {
                "event_type": "source_change",
                "request_id": str(uuid4()),
                "timestamp": _now(),
                "user_id": requester.id,
                "department": requester.department,
                "role": requester.role,
                "document_id": document_id,
                "action": "mark_source_updated",
                "retrieved_document_ids": [],
                "authorization_decisions": [],
                "final_answer": decision,
                "decision": decision,
                "provider": "deterministic",
            }
        )
        if not allowed:
            raise PermissionError("source simulation requires a compliance or auditor role")
        return updated_document

    def sync_document(self, actor: User | str, document_id: str) -> Document:
        requester = self._resolve_user(actor)
        allowed = requester.role in AUDIT_ROLES or requester.department == "compliance"
        updated_document: Document | None = None
        if allowed:
            for index, document in enumerate(self.documents):
                if document.id == document_id:
                    updated_document = replace(
                        document,
                        updated_at=document.source_updated_at,
                        synced_at=_now(),
                    )
                    self.documents[index] = updated_document
                    break
            if updated_document is None:
                raise KeyError(f"unknown document: {document_id}")

        decision = "allowed" if allowed else "denied"
        self.audit.append(
            {
                "event_type": "source_change",
                "request_id": str(uuid4()),
                "timestamp": _now(),
                "user_id": requester.id,
                "department": requester.department,
                "role": requester.role,
                "document_id": document_id,
                "action": "sync_document",
                "retrieved_document_ids": [],
                "authorization_decisions": [],
                "final_answer": decision,
                "decision": decision,
                "provider": "deterministic",
            }
        )
        if not allowed:
            raise PermissionError("source simulation requires a compliance or auditor role")
        return updated_document
