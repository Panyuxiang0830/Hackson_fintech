"""Parser/ACL fixtures run without model downloads; real models have a separate smoke test."""

import re

import pytest


class FixtureTokenizer:
    is_fast = True

    def __call__(self, text, **kwargs):
        offsets = [(match.start(), match.end()) for match in re.finditer(r"\S", text)]
        return {"input_ids": list(range(len(offsets))), "offset_mapping": offsets}

    def encode(self, text, add_special_tokens=True, **kwargs):
        return list(range(len(re.findall(r"\S", text)) + (2 if add_special_tokens else 0)))

    def num_special_tokens_to_add(self, pair=False):
        return 2


@pytest.fixture(autouse=True)
def offline_chunk_tokenizer(monkeypatch):
    tokenizer = FixtureTokenizer()
    monkeypatch.setattr("contextledger.processors.chunk_tokenizer", lambda: tokenizer)
