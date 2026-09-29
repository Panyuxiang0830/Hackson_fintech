from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request

from .models import Evidence, User


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?。！？])\s+", text.strip())
    return [part.strip() for part in parts if part.strip()]


class AnswerService:
    def __init__(self) -> None:
        self.provider = os.getenv("LLM_PROVIDER", "mock").lower()

    def answer(self, user: User, question: str, evidence: list[Evidence]) -> tuple[str, str]:
        if not evidence:
            return (
                "I could not find enough authorised evidence to answer this question. "
                "This may be because the information is outside your access scope.",
                "insufficient",
            )

        if self.provider == "openai_compatible":
            try:
                return self._openai_compatible(user, question, evidence), "answered"
            except (ValueError, urllib.error.URLError, TimeoutError, json.JSONDecodeError, KeyError):
                # The demo remains usable if the external model is unavailable.
                return self._mock_answer(user, evidence, degraded=True), "answered"

        return self._mock_answer(user, evidence), "answered"

    def _mock_answer(self, user: User, evidence: list[Evidence], degraded: bool = False) -> str:
        prefix = "Model endpoint unavailable; showing deterministic evidence synthesis.\n\n" if degraded else ""
        lines = [
            f"Authorised answer for **{user.name}** ({user.role}, {user.department}):",
            "",
        ]
        for index, item in enumerate(evidence, start=1):
            first_sentence = _sentences(item.document.content)[0]
            lines.append(f"- {first_sentence} **[{index}]**")
        lines.extend(
            [
                "",
                "This answer is limited to evidence authorised for the selected identity. "
                "Open the evidence panel to inspect source, freshness, and access rationale.",
            ]
        )
        return prefix + "\n".join(lines)

    def _openai_compatible(self, user: User, question: str, evidence: list[Evidence]) -> str:
        base_url = os.getenv("LLM_BASE_URL", "").rstrip("/")
        api_key = os.getenv("LLM_API_KEY", "")
        model = os.getenv("LLM_MODEL", "")
        if not base_url or not api_key or not model:
            raise ValueError("LLM endpoint configuration is incomplete")

        context = "\n\n".join(
            f"[{index}] {item.document.source} | {item.document.title} | "
            f"updated={item.document.updated_at}\n{item.document.content}"
            for index, item in enumerate(evidence, start=1)
        )
        system = (
            "You are a permission-aware enterprise knowledge assistant. Use only the supplied "
            "authorised evidence. Cite claims with [n]. If evidence is insufficient, say so. "
            "Never infer or mention documents outside the supplied evidence."
        )
        user_prompt = (
            f"Identity: {user.name}, role={user.role}, department={user.department}.\n"
            f"Question: {question}\n\nAuthorised evidence:\n{context}"
        )
        payload = json.dumps(
            {
                "model": model,
                "temperature": 0,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_prompt},
                ],
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{base_url}/chat/completions",
            data=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            body = json.load(response)
        return body["choices"][0]["message"]["content"]

