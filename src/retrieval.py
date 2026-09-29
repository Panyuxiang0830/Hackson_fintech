from __future__ import annotations

import math
import re

from .models import Document, Evidence, PolicyDecision


WORD_RE = re.compile(r"[a-zA-Z0-9_.-]+|[\u4e00-\u9fff]+")

SYNONYMS = {
    "上线": {"release", "released", "deployment", "deployed", "live", "上线", "发布"},
    "事故": {"incident", "failure", "failures", "事故", "故障", "失败"},
    "原因": {"cause", "root", "reason", "原因", "根因"},
    "恢复": {"recover", "recovered", "recovery", "normal", "恢复", "正常"},
    "客户": {"customer", "customers", "communication", "客户", "沟通"},
    "批准": {"approve", "approved", "approval", "批准", "审批"},
}


def tokenise(text: str) -> set[str]:
    lowered = text.lower()
    tokens = set(WORD_RE.findall(lowered))
    expanded = set(tokens)
    for keyword, related in SYNONYMS.items():
        if keyword in lowered or any(term in lowered for term in related):
            expanded.update(related)
    return expanded


class Retriever:
    def retrieve(
        self,
        question: str,
        authorised_documents: list[tuple[Document, PolicyDecision]],
        limit: int = 5,
    ) -> list[Evidence]:
        query_tokens = tokenise(question)
        scored: list[Evidence] = []

        for document, access_decision in authorised_documents:
            title_tokens = tokenise(document.title)
            content_tokens = tokenise(document.content)
            title_overlap = len(query_tokens & title_tokens)
            content_overlap = len(query_tokens & content_tokens)
            status_bonus = 0.4 if document.status in {"approved", "released", "recovered", "resolved"} else 0.0
            source_bonus = 0.5 if document.source == "release_registry" else 0.0
            score = 2.0 * title_overlap + content_overlap + status_bonus + source_bonus
            score /= math.sqrt(max(1, len(content_tokens)))
            if score > 0:
                scored.append(Evidence(document, round(score, 4), access_decision.reason))

        scored.sort(key=lambda item: (item.score, item.document.updated_at), reverse=True)
        return scored[:limit]

