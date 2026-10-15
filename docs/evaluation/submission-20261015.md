# Submission evaluation — 15 October 2026

REQ-018. The hackathon report shows five functional measurements on baseline `952881f9a2f28e193b9f76988f141d454fc13dd9`: update visibility, permissions, retrieval, single-request latency and model fees. The user cancelled concurrency/load benchmarking. Its partial records and completed burst observations remain in the raw run directory, outside the report metrics.

| Dimension | Result | Population |
|---|---|---|
| Freshness | Publication p50 74 ms, p95 137 ms; latest-version Recall 90.74% at the 100 ms query point, 100% at 250 ms | 54 controlled changes, three runs, 1,000 background documents; 10 ms publication sampling |
| Permissions | 0/486 false allows; 0/432 false denials; no observed candidate/context/evidence/audit-ID leakage | 918 service checks; 3/3 real in-flight answers blocked with HTTP 409 |
| Retrieval | EnterpriseRAG keyword/vector/hybrid Recall@10: 61.19% / 55.86% / 66.30% | Current token-aware offline snapshot; 180 fully covered questions out of 500; all 578 public questions executed in all three modes |
| Latency | p50 4.74 s, p95 12.94 s, max 15.03 s | 60 sequential English answerable HTTP requests on 17 synthetic documents; model, retrieval and retries included |
| Model fee | USD 0.01467470921 known billed fee; USD 0.00024457849 per reviewed-checker-pass answer | 89/89 completion attempts have billed cost; selected single-request cohort has 99 HTTP observations |

The fee uses 145,386 prompt tokens, 7,188 completion tokens and 121,856 reported cached prompt tokens. All 36 negative/revoked requests skip generation. The fee includes the three provider responses discarded after in-flight revocation. The entire original run, including the excluded burst observations, incurred USD 0.02034364521. Infrastructure fees are outside this measurement.

Original answer-check pass rate is 58/60; recognizing the valid phrase `Chinese Yuan (CNY)` yields 60/60. The two original failures, unchanged answers and explicit checker correction are retained. This is a defined fact/citation regression, not comprehensive semantic accuracy. The saved offline ranking refinement is independently rescored at 91.98% Recall@10 over 180 questions; its reused 160-question validation subset scores 91.40%. It has not been deployed or rerun on a GPU.

Part A applies ACL after candidate search; it does not provide candidate isolation. The permission scores above use the integrated filtered service. EnterpriseRAG coverage is 180 fully covered, 290 missing some reference evidence and 30 without references. Hybrid Recall@10 on all 470 reference-bearing questions is 30.06%. OrgForge hybrid Recall@10 is 9.77% on its 29 fully covered questions out of 78. These weaker scores are retained.

Source events and ACLs are controlled fixture truth, not real source-platform notifications or policy inheritance. Authentication uses isolated demo identities. The public questions have already been inspected. Non-streaming durations do not measure time to first token. No employee time saving or production acceptance is claimed.

## Artifacts and reproduction

- Report: `docs/submission/main.tex`; aggregate machine-readable metrics: `docs/submission/evaluation/metrics.json`.
- Raw artifacts: `/home/junyao/code/hackathon/runtime/submission-evaluation-20261015`.
- Original runner and implementation fingerprints are in each protocol and snapshot manifest. Frozen source resides in `/home/junyao/code/hackathon/runtime/revert-pr17`; model configuration is answer-v10, DeepSeek V3.2, planning disabled, existing reasoning settings.
- `freshness-sparse/repeat-*/`: source workload, immutable gold, raw/scored queries, publication observations and reports.
- `permissions/`: independent policy matrix and candidate/input/evidence/audit traces; `groups/repeat-*/`: explicit group-principal checks.
- `real-cost/`: actual HTTP answers, all provider attempts and usage/cost, original/reviewed scoring, updates, revocation and audit verification. Filter out `phase=burst` to reproduce the selected cohort.
- `retrieval/`: read-only database backup, vector/data fingerprints and full evaluation. All artifact hashes match before and after execution. The legacy index preflight failed because its historical metadata lacks the required chunk fingerprint; it scored no queries. The valid token-aware snapshot is used instead.
- `real-cost-preflight-invalid-host/`: 133 archived session-preparation failures, zero model calls; corrected authenticated HTTP preflight passes before measurement.
- `load/status.json`: user-cancelled pressure-test status. The queued complex/concurrency expansion was cancelled before provider calls.

Collectors and complete per-query records are archived with the frozen baseline in the raw run directory. The versioned metrics omit per-query retrieval observations and retain aggregate results plus the complete file's SHA-256. Reruns require the frozen baseline, a separate Qdrant collection and private model configuration; the results above are not measurements of the current frontend branch.

Baseline validation: 308 unit tests pass. Requirement synchronization passes. The live Overleaf PDF is compiled with LuaLaTeX, Linux Libertine body text, Linux Biolinum headings and Inconsolata code text; English report and demo screenshot are retained.
