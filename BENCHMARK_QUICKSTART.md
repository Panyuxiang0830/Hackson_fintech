# Benchmark Quick Start

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
