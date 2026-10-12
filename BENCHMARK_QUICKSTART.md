# Benchmark Quick Start

## Retrieval

After [Part A setup](QUICKSTART.md), run from the repository root:

```bash
bash scripts/part_a.sh eval
```

Report: `runtime/part_a/evaluation.json`.

Fast check:

```bash
bash scripts/part_a.sh eval --modes keyword --limit 20 --ann-queries 0
```

Use `--out PATH` for an existing store or `--report PATH.json` for a separate
report. The corpus and indexes are read-only.

Reports include fixed-reference document Recall@K, all-evidence rate, coverage,
retrieval latency, ANN agreement and synthetic ACL/time checks. Scoring uses
one fixed ranking (`--retrieval-depth 20`); cutoffs must not exceed its depth.

This is a retrieval regression without BGE/Qwen refinement or model answers.
Extractive checks are diagnostics. Generated-answer quality, actual API cost,
live freshness and deployed end-to-end performance remain unmeasured.
Final acceptance requires frozen settings, unseen questions and the deployed
answering pipeline, including permission revocation and integrated audit.
The 90% recall target is a team target, not the hackathon judging score.

## Freshness

After Part A setup, run from the repository root. MiniLM uses the locally
cached model; no model download occurs during replay.

```bash
bash scripts/freshness_eval.sh generate --out runtime/freshness/workload.json
bash scripts/freshness_eval.sh run \
  --workload runtime/freshness/workload.json \
  --embedding minilm --out runtime/freshness/run
```

Open `runtime/freshness/run/report.html` in a browser. The same directory
contains `report.json`, `curves.csv`, `visibility.csv` and `failures.jsonl`.
For a fast smoke check, replace `--embedding minilm` with `--embedding fixture`
(deterministic token hashes, for checking the harness only).

The 24 controlled change cases run in temporary SQLite/Qdrant stores.
Reports separate version Recall@8 from document-ID Recall and keep missing or
failed retrievals in the denominator. The default 500 ms publication delay is
a replay parameter, not a measured connector delay.

To score the saved observations again:

```bash
bash scripts/freshness_eval.sh score \
  --workload runtime/freshness/run/workload.json \
  --results runtime/freshness/run/results.jsonl \
  --arms current_snapshot fully_synced stale_snapshot \
  --out runtime/freshness/rescored
```
