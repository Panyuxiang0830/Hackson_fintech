"""Version-aware online Recall evaluation, independent of index mechanisms."""

from __future__ import annotations

import argparse
from collections import defaultdict
import csv
from datetime import datetime, timezone
import hashlib
import html
import importlib
from importlib.metadata import PackageNotFoundError, version
import json
import math
from pathlib import Path
import platform
import tempfile
import time

from contextledger.evaluation.workload import Workload, example_workload, key

MODES = ("keyword", "vector", "hybrid")
ARMS = ("current_snapshot", "fully_synced", "stale_snapshot")


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def percentile(values, fraction):
    if not values:
        return None
    values = sorted(values)
    position = (len(values) - 1) * fraction
    lower = int(position)
    upper = math.ceil(position)
    return values[lower] + (values[upper] - values[lower]) * (position - lower)


def score_row(workload, query, result, k=8):
    """Every issued answerable query stays in Recall's denominator."""
    state, _ = workload.state(query["at_ms"])
    gold = {key(row) for row in query["gold"]}
    hits = result.get("hits", [])[:k]
    valid, doc_ids = set(), set()
    violations = defaultdict(int)
    for hit in hits:
        if any(not isinstance(hit.get(field), str) or not hit[field]
               for field in ("corpus", "doc_id", "version")):
            violations["unverified"] += 1
            continue
        try:
            identity = key(hit)
        except (KeyError, TypeError):
            violations["unverified"] += 1
            continue
        doc_ids.add(identity[:2])
        revision = workload.revisions.get(identity)
        current = state.get(identity[:2])
        if revision is None or hit.get("content_hash") != revision["content_hash"]:
            violations["unverified"] += 1
            continue
        if current is None or query["actor_id"] not in current["allowed_actors"]:
            if current is None:
                first_seen = [event["at_ms"] for event in workload.events
                              if event["op"] == "upsert" and key(event) == identity]
                violations["future" if first_seen and min(first_seen) > query["at_ms"] else "withdrawn"] += 1
            else:
                violations["unauthorized"] += 1
        elif key(current) != identity:
            first_seen = [event["at_ms"] for event in workload.events
                          if event["op"] == "upsert" and key(event) == identity]
            violations["future" if first_seen and min(first_seen) > query["at_ms"] else "stale"] += 1
        else:
            valid.add(identity)
    ok = result["status"] == "ok"
    matching = len(valid & gold) if ok else 0
    return {"query_id": query["id"], "case_id": query.get("case_id"), "arm": result["arm"],
        "mode": result["mode"], "at_ms": query["at_ms"], "age_ms": workload.age(query),
        "kind": query["kind"], "phase": workload.phase(query), "status": result["status"],
        "gold_count": len(gold), "hits_count": len(hits), "matched_count": matching,
        "recall": matching / len(gold) if gold else None,
        "doc_id_recall": len(doc_ids & {identity[:2] for identity in gold}) / len(gold) if gold and ok else (0.0 if gold else None),
        "all_evidence_hit": ok and bool(gold) and matching == len(gold),
        "correct_empty": ok and not hits if not gold else None,
        "latency_ms": result.get("latency_ms"), "e2e_latency_ms": result.get("e2e_latency_ms"),
        "release_lag_ms": result.get("release_lag_ms"),
        "violations": {label: violations[label] for label in ("stale", "future", "withdrawn", "unauthorized", "unverified")}}


def aggregate(rows):
    answerable = [row for row in rows if row["gold_count"]]
    negative = [row for row in rows if not row["gold_count"]]
    latencies = [row["latency_ms"] for row in rows if row.get("latency_ms") is not None]
    e2e = [row["e2e_latency_ms"] for row in rows if row.get("e2e_latency_ms") is not None]
    count = len(rows)
    slots = sum(row["hits_count"] for row in rows)
    return {"issued_queries": count, "answerable_queries": len(answerable), "expected_empty_queries": len(negative),
        "version_recall": sum(row["recall"] for row in answerable) / len(answerable) if answerable else None,
        "doc_id_recall": sum(row["doc_id_recall"] for row in answerable) / len(answerable) if answerable else None,
        "worst_version_recall": min((row["recall"] for row in answerable), default=None),
        "all_evidence_hit_rate": sum(row["all_evidence_hit"] for row in answerable) / len(answerable) if answerable else None,
        "correct_empty_rate": sum(row["correct_empty"] for row in negative) / len(negative) if negative else None,
        "available_rate": sum(row["status"] == "ok" for row in rows) / count if count else None,
        "missing_results": sum(row["status"] == "missing" for row in rows),
        "statuses": {status: sum(row["status"] == status for row in rows) for status in ("ok", "unavailable", "error", "timeout", "missing")},
        "evidence_slots": slots,
        "violation_rates_per_evidence_slot": {label: sum(row["violations"][label] for row in rows) / slots if slots else None
                                              for label in ("stale", "future", "withdrawn", "unauthorized", "unverified")},
        "violations": {label: sum(row["violations"][label] for row in rows)
                       for label in ("stale", "future", "withdrawn", "unauthorized", "unverified")},
        "backend_latency_ms": {"samples": len(latencies), "p50": percentile(latencies, .5),
                               "p95": percentile(latencies, .95), "p99": percentile(latencies, .99)},
        "e2e_latency_ms": {"samples": len(e2e), "p50": percentile(e2e, .5),
                           "p95": percentile(e2e, .95), "p99": percentile(e2e, .99)}}


def score_results(workload, results, *, arms, modes=MODES, k=8):
    if type(k) is not int or k < 1 or not arms or len(set(arms)) != len(arms):
        raise ValueError("invalid k or arms")
    if not modes or len(set(modes)) != len(modes) or any(mode not in MODES for mode in modes):
        raise ValueError("invalid modes")
    indexed = {}
    for result in results:
        identity = result["arm"], result["mode"], result["query_id"]
        if identity in indexed:
            raise ValueError("duplicate result for an issued query")
        if result["arm"] not in arms or result["mode"] not in modes or result["query_id"] not in workload.query_map:
            raise ValueError("result lies outside the frozen query population")
        query = workload.query_map[result["query_id"]]
        if result.get("workload_sha256") != workload.sha256 or result.get("at_ms") != query["at_ms"]:
            raise ValueError("result workload hash or query time mismatch")
        if result.get("status") not in {"ok", "unavailable", "error", "timeout", "missing"}:
            raise ValueError("unknown result status")
        if not isinstance(result.get("hits"), list) or any(not isinstance(hit, dict) for hit in result["hits"]):
            raise ValueError("hits must be a list of evidence records")
        for field in ("latency_ms", "e2e_latency_ms", "release_lag_ms"):
            value = result.get(field)
            if value is not None and (type(value) not in (int, float) or not math.isfinite(value) or value < 0):
                raise ValueError("invalid measured latency")
        indexed[identity] = result
    rows = []
    for arm in arms:
        for mode in modes:
            for query in workload.queries:
                result = indexed.get((arm, mode, query["id"]), {"arm": arm, "mode": mode, "status": "missing", "hits": []})
                rows.append(score_row(workload, query, result, k))
    summaries = []
    curves = []
    for arm in arms:
        for mode in modes:
            subset = [row for row in rows if row["arm"] == arm and row["mode"] == mode]
            for phase in ("online", "recovery", "static_undrained"):
                for kind in ("all", "chasing", "regular", "negative", "static"):
                    selected = [row for row in subset if row["phase"] == phase and (kind == "all" or row["kind"] == kind)]
                    if selected:
                        summaries.append({"arm": arm, "mode": mode, "phase": phase, "kind": kind, **aggregate(selected)})
            groups = defaultdict(list)
            for row in subset:
                if row["phase"] != "static_undrained":
                    groups[row["phase"], row["kind"], row["age_ms"]].append(row)
            for (phase, kind, age), selected in sorted(groups.items(), key=lambda item: (str(item[0][0:2]), item[0][2] or 0)):
                metrics = aggregate(selected)
                curves.append({"arm": arm, "mode": mode, "phase": phase, "kind": kind, "age_ms": age,
                    **{field: metrics[field] for field in ("issued_queries", "answerable_queries", "version_recall", "doc_id_recall", "worst_version_recall", "available_rate", "correct_empty_rate")}})
    visibility = []
    groups = defaultdict(list)
    for row in rows:
        if row["kind"] == "chasing" and row["gold_count"] and row["case_id"]:
            query = workload.query_map[row["query_id"]]
            gold_id = tuple(key(item) for item in query["gold"])
            _, changes = workload.state(query["at_ms"])
            event_ids = (query["anchor_event_id"],) if query.get("anchor_event_id") else tuple(sorted(
                changes[(query["corpus"], target)]["id"] for target in query["targets"]
                if (query["corpus"], target) in changes))
            groups[row["arm"], row["mode"], row["case_id"], gold_id, event_ids].append(row)
    for (arm, mode, case_id, _, event_ids), samples in sorted(groups.items()):
        samples.sort(key=lambda row: row["age_ms"])
        first = next((row["age_ms"] for row in samples if row["all_evidence_hit"]), None)
        consistent = next((row["age_ms"] for index, row in enumerate(samples)
                           if all(later["all_evidence_hit"] for later in samples[index:])), None)
        visibility.append({"arm": arm, "mode": mode, "case_id": case_id, "source_event_ids": list(event_ids), "probes": len(samples),
            "first_full_recall_age_ms": first, "observed_consistent_from_age_ms": consistent,
            "censored": consistent is None, "last_probe_age_ms": samples[-1]["age_ms"]})
    visibility_summaries = []
    for arm in arms:
        for mode in modes:
            samples = [row for row in visibility if row["arm"] == arm and row["mode"] == mode]
            observed = [row["observed_consistent_from_age_ms"] for row in samples if not row["censored"]]
            visibility_summaries.append({"arm": arm, "mode": mode, "changes_probed": len(samples),
                "censored_changes": sum(row["censored"] for row in samples),
                "observed_consistent_age_ms": {"samples": len(observed), "p50": percentile(observed, .5),
                                                "p95": percentile(observed, .95), "p99": percentile(observed, .99)},
                "percentiles_conditional_on_observed": True})
    return {"schema_version": 1, "status": "complete", "created_at": datetime.now(timezone.utc).isoformat(),
        "workload_sha256": workload.sha256, "workload_name": workload.data["name"],
        "provenance": workload.data.get("provenance", {}),
        "contract": {"k": k, "gold": "corpus + document ID + immutable version + content hash, fixed at scheduled query time",
            "recall_denominator": "all issued answerable queries; per-query gold count", "missing_results": "miss",
            "empty_gold": "explicit expected-empty label, scored separately", "duplicates": "consume returned slots; cannot earn repeated credit",
            "phases": "online through last source event; planned recovery probes and undrained static endpoint separate",
            "visibility": "probe-resolution observations, censored misses retained; not an exact synchronization timer"},
        "population": {"source_events": len(workload.events), "revisions": len(workload.revisions),
            "cases": len(workload.data.get("cases", [])), "queries_per_arm_mode": len(workload.queries),
            "expected_results": len(rows), "observed_results": len(indexed), "last_source_ms": workload.last_source_ms,
            "horizon_ms": workload.horizon_ms},
        "summaries": summaries, "curves": curves, "visibility": visibility,
        "visibility_summaries": visibility_summaries, "rows": rows,
        "not_measured": ["generated-answer accuracy, semantic citation support, LLM tokens and cost",
                         "native connector detection lag and production server ANN performance"]}


def write_report(out, report):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    rows = report.pop("rows")
    try:
        for name, records in (("curves.csv", report["curves"]), ("visibility.csv", report["visibility"])):
            with (out / name).open("w", encoding="utf-8", newline="") as handle:
                if records:
                    writer = csv.DictWriter(handle, fieldnames=list(records[0]))
                    writer.writeheader()
                    writer.writerows(records)
        with (out / "scored.jsonl").open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
        failures = [row for row in rows if (row["gold_count"] and not row["all_evidence_hit"]) or
                    row["correct_empty"] is False or any(row["violations"].values()) or row["status"] != "ok"]
        with (out / "failures.jsonl").open("w", encoding="utf-8") as handle:
            for row in failures:
                handle.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
        report["failed_observations"] = len(failures)
        report["artifacts"] = {name: name for name in ("results.jsonl", "scored.jsonl", "failures.jsonl", "curves.csv", "visibility.csv", "report.html")}
        write_json(out / "report.json", report)
        _html_report(out / "report.html", report)
    finally:
        report["rows"] = rows


def _html_report(path, report):
    def percent(value):
        return "—" if value is None else f"{100 * value:.2f}%"
    table = []
    for row in report["summaries"]:
        if row["kind"] not in {"chasing", "regular", "static"}:
            continue
        table.append("<tr>" + "".join("<td>" + html.escape(str(value)) + "</td>" for value in
            (row["arm"], row["mode"], row["phase"], row["kind"], row["issued_queries"],
             percent(row["version_recall"]), percent(row["doc_id_recall"]), percent(row["available_rate"]),
             row["violations"]["stale"], row["violations"]["future"])) + "</tr>")
    payload = json.dumps(report["curves"], ensure_ascii=False, allow_nan=False).replace("<", "\\u003c")
    markup = """<!doctype html><html lang="zh"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ContextLedger · 新鲜度测评</title><style>
body{margin:0;background:#f3f5f7;color:#172233;font:15px system-ui,sans-serif}main{max-width:1200px;margin:32px auto;padding:0 24px}h1{font-size:30px}.card{background:white;border:1px solid #dfe4ea;border-radius:14px;padding:24px;margin:20px 0}p{line-height:1.7}.muted{color:#566578}select{padding:8px;margin:4px 12px 4px 0}svg{width:100%;height:auto}table{border-collapse:collapse;width:100%;font-size:13px}td,th{padding:10px;text-align:left;border-bottom:1px solid #e5eaf0;white-space:nowrap}.scroll{overflow:auto}code{word-break:break-all}a{color:#1761ad}
</style><main><h1>新鲜度：在线证据 Recall</h1><p class="muted">固定事件流 · 按查询时点计分 · 文档 ID 与版本分别核对</p>
<section class="card"><p>运行范围：SCOPE</p><p>gold 锁定为文档 ID、内容版本与哈希。拒答、不可用、超时和缺失结果保留在可回答查询的分母中。空 gold 有显式拒答标签，单独计分。</p><p>在线阶段、预先安排的恢复探针、未强制同步的静态终点分别报告。本页不代表回答质量、真实来源同步或规模性能评测。</p><p class="muted">Workload SHA-256：<code>HASH</code></p><a href="report.json">完整报告</a> · <a href="curves.csv">曲线 CSV</a> · <a href="failures.jsonl">失败明细</a></section>
<section class="card"><label>检索 <select id="mode"><option>hybrid</option><option>keyword</option><option>vector</option></select></label><label>查询 <select id="kind"><option value="chasing">追问新变化</option><option value="regular">普通查询</option></select></label><label>阶段 <select id="phase"><option value="online">在线</option><option value="recovery">恢复探针</option></select></label><svg id="chart" viewBox="0 0 1000 390" role="img" aria-label="版本 Recall 随更新后时间的曲线"></svg><p class="muted">横轴：来源变化后的计划毫秒数。纵轴：版本 Recall。设定的同步延迟属于回放参数；真实后端调用耗时另列于 JSON。</p></section>
<section class="card scroll"><table><thead><tr><th>方案</th><th>模式</th><th>阶段</th><th>查询</th><th>数量</th><th>版本 Recall</th><th>ID Recall</th><th>可用率</th><th>旧版证据</th><th>未来证据</th></tr></thead><tbody>TABLE</tbody></table></section></main>
<script id="data" type="application/json">PAYLOAD</script><script>
const rows=JSON.parse(document.getElementById('data').textContent), ns='http://www.w3.org/2000/svg';
function node(tag,attrs,text){const e=document.createElementNS(ns,tag);for(const [k,v] of Object.entries(attrs))e.setAttribute(k,v);if(text!==undefined)e.textContent=text;return e;}
function draw(){const svg=document.getElementById('chart');svg.replaceChildren();const selected=rows.filter(r=>r.mode===document.getElementById('mode').value&&r.kind===document.getElementById('kind').value&&r.phase===document.getElementById('phase').value&&r.version_recall!==null);const max=Math.max(1,...selected.map(r=>r.age_ms)), colors=['#1769aa','#159277','#d77923','#9c51bc'];
for(let i=0;i<=4;i++){const y=310-i*65;svg.append(node('line',{x1:65,y1:y,x2:960,y2:y,stroke:'#e1e7ed'}));svg.append(node('text',{x:14,y:y+5,fill:'#566578'},i*25+'%'));}svg.append(node('text',{x:420,y:380,fill:'#566578'},'来源变化后 / ms'));
const arms=[...new Set(selected.map(r=>r.arm))];arms.forEach((arm,index)=>{const data=selected.filter(r=>r.arm===arm).sort((a,b)=>a.age_ms-b.age_ms),color=colors[index%colors.length],points=data.map(r=>(65+895*r.age_ms/max)+','+(310-260*r.version_recall)).join(' ');svg.append(node('polyline',{points,fill:'none',stroke:color,'stroke-width':3}));data.forEach(r=>{const dot=node('circle',{cx:65+895*r.age_ms/max,cy:310-260*r.version_recall,r:4,fill:color});dot.append(node('title',{},arm+' · '+r.age_ms+' ms · '+(100*r.version_recall).toFixed(2)+'% · n='+r.issued_queries));svg.append(dot);});svg.append(node('text',{x:65+index*280,y:25,fill:color},arm));});[0,.25,.5,.75,1].forEach(t=>svg.append(node('text',{x:65+895*t,y:340,'text-anchor':'middle',fill:'#566578'},Math.round(max*t))));if(!selected.length)svg.append(node('text',{x:360,y:180,fill:'#566578'},'此阶段没有可回答探针'));}
document.querySelectorAll('select').forEach(e=>e.addEventListener('change',draw));draw();</script></html>"""
    scope = report.get("execution", {}).get("scope", "导入观测结果的离线计分")
    for token, value in (("SCOPE", html.escape(scope)), ("HASH", html.escape(report["workload_sha256"])),
                         ("TABLE", "".join(table)), ("PAYLOAD", payload)):
        markup = markup.replace(token, value)
    Path(path).write_text(markup, encoding="utf-8")


def replay(workload, out, *, arms=ARMS, modes=MODES, sync_delay_ms=500, embedding="minilm", clock="logical", adapter=None):
    from contextledger.evaluation.replay import Encoder, SnapshotReplay
    Workload._time(sync_delay_ms)
    if any(arm not in ARMS + ("adapter",) for arm in arms) or ("adapter" in arms and not adapter):
        raise ValueError("invalid replay arm or missing adapter factory")
    if clock not in {"logical", "wall"}:
        raise ValueError("unknown clock")
    if not arms or len(set(arms)) != len(arms) or not modes or len(set(modes)) != len(modes) or any(mode not in MODES for mode in modes):
        raise ValueError("replay arms and modes must be nonempty and unique")
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    write_json(out / "workload.json", workload.data)
    setup_started = time.perf_counter()
    from contextledger.paths import PROJECT_ROOT
    code_sha256 = {name: hashlib.sha256((PROJECT_ROOT / name).read_bytes()).hexdigest()
                   for name in ("contextledger/evaluation/freshness.py",
                                "contextledger/evaluation/replay.py",
                                "contextledger/evaluation/workload.py",
                                "contextledger/retrieval/filtered_index.py",
                                "contextledger/application/service.py")}
    dependencies = {}
    for package in ("qdrant-client", "numpy", "sentence-transformers", "torch"):
        try:
            dependencies[package] = version(package)
        except PackageNotFoundError:
            dependencies[package] = None
    encoder = Encoder(workload, embedding)
    setup_ms = (time.perf_counter() - setup_started) * 1000
    results, stages = [], []
    pending = {}
    with (out / "results.jsonl").open("w", encoding="utf-8") as raw, tempfile.TemporaryDirectory(prefix="contextledger-freshness-") as temporary:
        for arm in arms:
            factory = SnapshotReplay
            if arm == "adapter":
                module, name = adapter.split(":", 1)
                factory = getattr(importlib.import_module(module), name)
            backend = factory(workload, Path(temporary) / arm, encoder)
            actions = []
            for sequence, event in enumerate(workload.events):
                if event.get("initial") or arm == "stale_snapshot":
                    continue
                delivered = event["at_ms"] + (0 if arm == "fully_synced" else event.get("delivery_delay_ms", 0))
                actions.append((delivered, 0, sequence, "receive", event))
                actions.append((delivered + (0 if arm == "fully_synced" else sync_delay_ms), 1, sequence, "publish", event))
            actions.extend((query["at_ms"], 2, sequence, "query", query) for sequence, query in enumerate(workload.queries))
            actions.sort(key=lambda action: action[:3])
            pending[arm] = sum(action[0] > workload.horizon_ms for action in actions)
            started = time.perf_counter()
            try:
                for at_ms, _, _, action, record in actions:
                    if at_ms > workload.horizon_ms:
                        continue
                    if clock == "wall":
                        remaining = started + at_ms / 1000 - time.perf_counter()
                        if remaining > 0:
                            time.sleep(remaining)
                    if action != "query":
                        before = time.perf_counter()
                        status = "ok"
                        try:
                            backend.receive(record) if action == "receive" else backend.publish()
                        except Exception as error:
                            status = type(error).__name__
                        stages.append({"arm": arm, "event_id": record["id"], "action": action, "scheduled_ms": at_ms,
                                       "status": status, "wall_duration_ms": (time.perf_counter() - before) * 1000})
                        continue
                    for mode in modes:
                        before = time.perf_counter()
                        release_lag = max(0, (before - started) * 1000 - at_ms) if clock == "wall" else None
                        try:
                            observed = backend.search(record, mode)
                        except Exception as error:
                            observed = {"status": "error", "error": type(error).__name__, "hits": []}
                        after = time.perf_counter()
                        result = {**observed, "arm": arm, "mode": mode, "query_id": record["id"], "at_ms": at_ms,
                            "workload_sha256": workload.sha256, "latency_ms": (after - before) * 1000,
                            "release_lag_ms": release_lag,
                            "e2e_latency_ms": max(0, (after - started) * 1000 - at_ms) if clock == "wall" else None}
                        results.append(result)
                        raw.write(json.dumps(result, ensure_ascii=False, allow_nan=False) + "\n")
                    raw.flush()
            finally:
                backend.close()
            print(f"freshness replay: {arm} complete", flush=True)
    report = score_results(workload, results, arms=arms, modes=modes, k=8)
    report["execution"] = {"scope": "内置方案：隔离 SQLite + Qdrant local + 现有 UnifiedService.search；预计算 Embedding 的受控回放" +
                           ("；自定义 adapter 的后端范围需另行核对" if "adapter" in arms else ""),
        "arm_backends": {arm: adapter if arm == "adapter" else "Qdrant local engine (not native server HNSW)" for arm in arms},
        "embedding": encoder.model_name,
        "embedding_setup_ms": setup_ms, "clock": clock, "configured_sync_delay_ms": sync_delay_ms,
        "source_delivery": "workload delay overrides; fully_synced reference ignores delays",
        "k": 8, "python": platform.python_version(), "platform": platform.platform(),
        "dependencies": dependencies, "implementation_sha256": code_sha256,
        "pending_actions_at_horizon": pending, "post_horizon_flush": False,
        "generation_updates": "replay driver publishes whole snapshots; not a production connector",
        "latency_scope": "actual sequential local service calls; no throughput/concurrent-load claim",
        "adapter": adapter}
    write_json(out / "stages.json", stages)
    write_report(out, report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description="Version-aware online freshness Recall framework")
    commands = parser.add_subparsers(dest="command", required=True)
    generate = commands.add_parser("generate", help="freeze a controlled 24-case workload")
    generate.add_argument("--out", type=Path, required=True)
    generate.add_argument("--orgforge-db", type=Path)
    generate.add_argument("--cases", type=int, default=24)
    run = commands.add_parser("run", help="replay against isolated unified retrieval")
    run.add_argument("--workload", type=Path)
    run.add_argument("--out", type=Path, default=Path("runtime/freshness"))
    run.add_argument("--arms", nargs="+", default=list(ARMS), choices=ARMS + ("adapter",))
    run.add_argument("--modes", nargs="+", default=list(MODES), choices=MODES)
    run.add_argument("--sync-delay-ms", type=float, default=500)
    run.add_argument("--embedding", choices=("minilm", "fixture"), default="minilm")
    run.add_argument("--clock", choices=("logical", "wall"), default="logical")
    run.add_argument("--adapter", help="MODULE:factory implementing receive/publish/search/close")
    score = commands.add_parser("score", help="score external JSONL, retaining missing queries")
    score.add_argument("--workload", type=Path, required=True)
    score.add_argument("--results", type=Path, required=True)
    score.add_argument("--out", type=Path, required=True)
    score.add_argument("--arms", nargs="+", required=True)
    score.add_argument("--modes", nargs="+", default=list(MODES), choices=MODES)
    score.add_argument("--k", type=int, default=8)
    args = parser.parse_args(argv)
    try:
        if args.command == "generate":
            workload = example_workload(args.orgforge_db, args.cases)
            write_json(args.out, workload.data)
            print(json.dumps({"workload_sha256": workload.sha256, "cases": len(workload.data["cases"]),
                              "queries": len(workload.queries)}, ensure_ascii=False))
            return 0
        write_json(args.out / "report.json", {"status": "running", "created_at": datetime.now(timezone.utc).isoformat()})
        workload = Workload.read(args.workload) if args.workload else example_workload()
        if args.command == "run":
            report = replay(workload, args.out, arms=tuple(args.arms), modes=tuple(args.modes),
                            sync_delay_ms=args.sync_delay_ms, embedding=args.embedding, clock=args.clock, adapter=args.adapter)
        else:
            records = [json.loads(line) for line in args.results.read_text(encoding="utf-8").splitlines() if line.strip()]
            report = score_results(workload, records, arms=tuple(args.arms), modes=tuple(args.modes), k=args.k)
            write_json(args.out / "workload.json", workload.data)
            destination = args.out / "results.jsonl"
            if destination.resolve() != args.results.resolve():
                destination.write_text(args.results.read_text(encoding="utf-8"), encoding="utf-8")
            write_report(args.out, report)
        print(json.dumps({"status": report["status"], "issued_results": report["population"]["expected_results"],
                          "observed_results": report["population"]["observed_results"], "report": str(args.out / "report.html")}, ensure_ascii=False))
        return 0
    except Exception as error:
        if args.command != "generate":
            write_json(args.out / "report.json", {"status": "failed", "error_type": type(error).__name__,
                                                 "created_at": datetime.now(timezone.utc).isoformat()})
        parser.exit(1, f"freshness evaluation failed: {type(error).__name__}: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
