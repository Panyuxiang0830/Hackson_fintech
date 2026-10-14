"""Query-time evidence expansion and conservative, fact-specific source guidance."""
from __future__ import annotations

import re
import time
from contextledger.radar.protocol import (VERSION, MAX_DOCS, MAX_EVENTS, MAX_RELATIONS,
                                         MAX_ROUNDS, RadarBudget, identifiers, validate_arguments)
from contextledger.retrieval.filtered_index import IndexUnavailable


def source_guidance(hit):
    meta = hit["metadata"]
    kind = meta.get("record_type", "text")
    historical = bool(meta.get("historical_revision"))
    state = meta.get("native_status") if kind == "native_state" else None
    source = hit["source"]
    supported_fact = ("ticket_recorded_status" if source == "jira" else "code_merge_status" if source == "github" else None) if state else None
    return {"record_type": kind, "native_status": state, "historical": historical,
            "independence_group": meta.get("native_resource_id") or hit.get("doc_id"),
            "supported_fact": supported_fact if not historical else None,
            "assessment": "supported" if supported_fact and not historical else "source_reported",
            "scope": "source system record only" if supported_fact else "author's statement; requires corroboration",
            "does_not_establish": ["production_rollback", "service_recovery"],
            "event_time": meta.get("event_time"), "observed_at": meta.get("observed_at")}


def partition_claims(text):
    # A narrow, auditable conflict detector, not a general semantic truth engine.
    claims = []
    for sentence in re.split(r"[\n.!?]", text):
        if not re.search(r"partition", sentence, re.I):
            continue
        change = re.search(r"from\s+\d+\s+to\s+(\d+)", sentence, re.I) if re.search(r"partition\s+count|partitions", sentence, re.I) else None
        match = change or re.search(r"(?:partitions|partition\s+count)\s*(?:to|of|=|:|is)?\s*\(?\s*(\d+)|(\d+)\s+partitions", sentence, re.I)
        if match:
            value = next(g for g in match.groups() if g)
            claims.append({"attribute": "partition_count", "value": int(value), "quote": sentence.strip()[:400]})
    return claims


class DecisionRadarTool:
    def __init__(self, index, *, budget=None):
        self.index = index
        self.budget = budget or RadarBudget.configured()

    def execute(self, *, query, scope, generation, seeds, arguments, guard):
        guard()
        maximum = self.budget.documents
        reasons = set()
        allowed = set(identifiers(query))
        for hit in seeds:
            allowed.update(identifiers(hit["full_text"] + "\n" + hit["title"]))
        args = validate_arguments(arguments, allowed)
        # Question IDs take precedence over unrelated IDs in seeds.
        anchors = args["anchor_ids"] or identifiers(query) or sorted(allowed)[:8]
        selected = list(seeds[:maximum])
        seen = {h["doc_id"] for h in selected}
        seen_text = {h["full_text"].strip() for h in selected}
        frontier, expanded = set(anchors), set()
        truncated, rounds = len(seeds) > maximum, 0
        started = time.monotonic()
        for _ in range(MAX_ROUNDS):
            guard()
            if time.monotonic() - started > self.budget.seconds:
                truncated = True
                reasons.add("time_budget")
                break
            pending = sorted(frontier - expanded)[:16]
            if not pending:
                break
            expanded.update(pending)
            more, found_generation, limited = self.index.related(scope, pending, limit=maximum + 1)
            if found_generation != generation:
                raise IndexUnavailable("Index generation changed during Radar expansion")
            rounds += 1
            truncated |= limited
            if limited:
                reasons.add("related_scan_limit")
            for hit in more:
                # For an explicit attribute question, choose an actual source slice
                # around that attribute instead of an unrelated first page chunk.
                if re.search(r"分区|partition", query, re.I):
                    match = re.search(r"[^\n]*(?:partition count\s*\(?\d+|\d+\s+partitions)[^\n]*", hit["full_text"], re.I) or re.search(r"[^\n]*partition[^\n]*\d+[^\n]*", hit["full_text"], re.I)
                    if match:
                        start, end = max(0, match.start()-200), min(len(hit["full_text"]), match.end()+500)
                        hit = {**hit, "text": hit["full_text"][start:end], "chunk_id": None,
                               "radar_source_span": {"start": start, "end": end, "content_hash": hit["content_hash"]}}
                if hit["doc_id"] not in seen and hit["full_text"].strip() not in seen_text:
                    if len(selected) == maximum:
                        truncated = True
                        reasons.add("document_limit")
                        break
                    seen.add(hit["doc_id"])
                    seen_text.add(hit["full_text"].strip())
                    selected.append(hit)
                    frontier.update(identifiers(hit["title"] + "\n" + hit["full_text"]))
        if not anchors:
            # Names without native IDs reuse bounded authorised search; semantic
            # neighbors remain candidates, never asserted lineage.
            more, found_generation = self.index.search(scope, query, mode="hybrid", limit=maximum)
            if found_generation != generation:
                raise IndexUnavailable("Index generation changed during Radar name search")
            for hit in more:
                if hit["doc_id"] not in seen and len(selected) < maximum:
                    selected.append(hit)
                    seen.add(hit["doc_id"])
            truncated = True
        if frontier - expanded:
            reasons.add("expansion_round_limit")
        truncated |= bool(frontier - expanded)
        guard()
        events, statuses, relations, claims = [], [], [], []
        relation_keys = set()
        for citation, hit in enumerate(selected, 1):
            guidance = source_guidance(hit)
            statuses.append({"citation_id": citation, **guidance})
            excerpt = hit["text"][:400]
            events.append({"citation_id": citation, "doc_id": hit["doc_id"],
                "type": guidance["record_type"], "event_time": guidance["event_time"],
                "observed_at": guidance["observed_at"], "quote": excerpt,
                "quote_span": ({**hit["radar_source_span"], "end": hit["radar_source_span"]["start"] + len(excerpt)}
                               if "radar_source_span" in hit else {"chunk_id": hit["chunk_id"], "start": 0, "end": len(excerpt)}),
                "actor": hit["metadata"].get("actor"), "time_precision": hit["metadata"].get("time_precision", "unknown"),
                "version": hit["version"], "historical": guidance["historical"]})
            ids = identifiers(hit["title"] + "\n" + hit["text"])
            for anchor in anchors:
                if anchor in ids:
                    for target in ids:
                        key = (anchor, target)
                        if target == anchor or key in relation_keys:
                            continue
                        if len(relations) >= self.budget.relations:
                            truncated = True
                            reasons.add("relation_limit")
                            continue
                        relation_keys.add(key)
                        relations.append({"from": anchor, "to": target, "type": "explicit_mention",
                                          "citation_id": citation, "causation_established": False})
            for claim in partition_claims(hit["text"]):
                # A recurrence mention is not the subject of every attribute. Use
                # the source record's incident title or an ID in the actual claim.
                title_ids = identifiers(hit["title"])
                incident = next((i for i in title_ids if i.startswith("ENG-")), None)
                subjects = ([incident] if incident else identifiers(claim["quote"]))
                native = hit["metadata"].get("native_resource_id")
                if native:
                    subjects.append(native)
                claims.append({**claim, "citation_id": citation, "entity_ids": list(dict.fromkeys(subjects)),
                               "independence_group": guidance["independence_group"]})
        disagreements = []
        # Only attribute claims sharing an explicit entity. Differences across entities
        # or time are candidates for inspection, never automatically a contradiction.
        for anchor in anchors:
            relevant = [c for c in claims if anchor in c["entity_ids"]]
            if len({c["value"] for c in relevant}) > 1 and len({c["independence_group"] for c in relevant}) > 1:
                disagreements.append({"entity_id": anchor, "attribute": "partition_count",
                    "assessment": "requires_review", "reason": "different reported values; scope and time may differ",
                    "claims": relevant[:8], "claims_truncated": len(relevant) > 8})
        ordered = sorted(events, key=lambda e: (e["event_time"] is None, str(e["event_time"] or ""), e["citation_id"]))
        return selected, {"version": VERSION, "entity_candidates": anchors,
            "source_statuses": statuses, "event_candidates": ordered[:self.budget.events],
            "relations": relations, "disagreements": disagreements,
            "coverage": {"documents": len(selected), "rounds": rounds, "truncated": bool(truncated),
                         "limits": {"documents": maximum, "events": self.budget.events, "relations": self.budget.relations, "rounds": MAX_ROUNDS, "seconds": self.budget.seconds},
                         "truncation_reasons": sorted(reasons),
                         "complete_business_chain": False, "scope": "current authorised offline snapshot",
                         "missing": ["Bounded visible links do not cover the complete native source history."]}}
