"""Immutable imported text revisions, published through ordinary guarded documents.

This preserves observed source text, not an inferred entity/event database. History
is never read outside FilteredIndex and always inherits the current root ACL.
"""
from dataclasses import replace
import hashlib
import json
from contextledger.storage.models import SourceDoc


class SourceRevisionStore:
    def __init__(self):
        self._revisions = {}

    def observe(self, document: SourceDoc, *, observed_at: str):
        digest = hashlib.sha256(document.text.encode()).hexdigest()
        key = (document.corpus, document.doc_id, digest)
        if key not in self._revisions:
            metadata = json.loads(json.dumps(document.extra))
            metadata.update(historical_revision=True, radar_root_doc_id=document.extra.get("radar_root_doc_id") or document.doc_id,
                            source_revision_hash=digest, observed_at=observed_at)
            self._revisions[key] = replace(document,
                doc_id=document.doc_id + "@revision-" + digest[:16],
                extra=metadata, actors=list(document.actors), raw={})
        return self._revisions[key].doc_id

    def documents(self, current):
        # A removed root never restores access to its archived versions.
        active = {(d.corpus, d.doc_id): d for d in current}
        result = []
        for (corpus, root, digest), doc in self._revisions.items():
            if (corpus, root) not in active or hashlib.sha256(active[corpus, root].text.encode()).hexdigest() == digest:
                continue
            result.append(replace(doc, extra=dict(doc.extra), actors=list(doc.actors)))
        return result
