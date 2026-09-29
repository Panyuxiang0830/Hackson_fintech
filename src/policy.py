from __future__ import annotations

from .models import CLASSIFICATION_LEVELS, Document, PolicyDecision, User


class PolicyEngine:
    """Deterministic, deny-by-default policy checks used before retrieval."""

    def evaluate(self, user: User, document: Document) -> PolicyDecision:
        if user.clearance not in CLASSIFICATION_LEVELS:
            return PolicyDecision(False, "unknown user clearance")
        if document.classification not in CLASSIFICATION_LEVELS:
            return PolicyDecision(False, "unknown document classification")

        if CLASSIFICATION_LEVELS[user.clearance] < CLASSIFICATION_LEVELS[document.classification]:
            return PolicyDecision(False, "clearance below document classification")

        if document.project and document.project not in user.projects:
            return PolicyDecision(False, "user is not assigned to the document project")

        if document.allowed_departments and user.department not in document.allowed_departments:
            return PolicyDecision(False, "department is not allowed")

        if document.allowed_roles and user.role not in document.allowed_roles:
            return PolicyDecision(False, "role is not allowed")

        return PolicyDecision(
            True,
            f"allowed by clearance={user.clearance}, department={user.department}, "
            f"role={user.role}, project={document.project or 'global'}",
        )

    def filter_documents(
        self, user: User, documents: list[Document]
    ) -> tuple[list[tuple[Document, PolicyDecision]], int]:
        allowed: list[tuple[Document, PolicyDecision]] = []
        denied_count = 0
        for document in documents:
            decision = self.evaluate(user, document)
            if decision.allowed:
                allowed.append((document, decision))
            else:
                denied_count += 1
        return allowed, denied_count

