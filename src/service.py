from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .answering import AnswerService
from .audit import AuditService
from .models import AnswerResult, Document, User
from .policy import PolicyEngine
from .retrieval import Retriever


class KnowledgeService:
    def __init__(
        self,
        documents: list[Document],
        audit_path: Path,
        policy: PolicyEngine | None = None,
        retriever: Retriever | None = None,
        answerer: AnswerService | None = None,
    ) -> None:
        self.documents = documents
        self.policy = policy or PolicyEngine()
        self.retriever = retriever or Retriever()
        self.answerer = answerer or AnswerService()
        self.audit = AuditService(audit_path)

    def ask(self, user: User, question: str, limit: int = 5) -> AnswerResult:
        request_id = str(uuid4())
        authorised, denied_count = self.policy.filter_documents(user, self.documents)
        evidence = self.retriever.retrieve(question, authorised, limit=limit)
        answer, decision = self.answerer.answer(user, question, evidence)

        authorised_ids = {document.id for document, _ in authorised}
        evidence_ids = [item.document.id for item in evidence]
        if not set(evidence_ids).issubset(authorised_ids):
            raise RuntimeError("security invariant violated: unauthorised evidence reached answering")

        record = {
            "request_id": request_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "user_id": user.id,
            "department": user.department,
            "role": user.role,
            "question": question,
            "authorised_document_count": len(authorised),
            "denied_document_count": denied_count,
            "retrieved_document_ids": evidence_ids,
            "decision": decision,
            "provider": self.answerer.provider,
        }
        self.audit.append(record)
        return AnswerResult(
            request_id=request_id,
            user=user,
            question=question,
            answer=answer,
            evidence=tuple(evidence),
            denied_document_count=denied_count,
            decision=decision,
            provider=self.answerer.provider,
            audit_record=record,
        )

