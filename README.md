# ContextLedger MVP

Permission-aware enterprise knowledge assistant for the Tencent Cloud AI CAN DO IT 2026 FinTech track.

[Part A Quick Start](QUICKSTART.md)

## Unified integration

The unified service connects Part A data to filtered Qdrant/FTS retrieval, persistent system permissions, grounded answer generation and query audit. The Part A-style frontend remains the current integration and manual acceptance interface. Browser OIDC is deferred and disabled by default; identity/permissions are not removed. An Agent tool is a **deferred future idea**, not a prerequisite for this release. An explicit, loopback-only isolated demo offers one independent administrator and six employees, reusing the real services; it is **not production authentication**. Ordinary unauthenticated APIs remain locked. See [demo acceptance](docs/product/demo-acceptance.md), [integration setup](docs/architecture/unified-integration.md), and [future tool scope](docs/product/tool-entry-scope.md).

The sections below describe the original Streamlit v0 reference, not the integration's live state. Integration, Part A evaluation and compatibility fixes are delivered together through [PR #6](https://github.com/Panyuxiang0830/Hackson_fintech/pull/6). On 2026-10-08 gpushare was rebuilt with 45,565 documents and 591,294 Qdrant points; the loopback preview on 17860 passed retrieval, revocation, real-model and audit checks. The original 7860 service and old snapshot are retained. Offline reranker experiments do not automatically change frontend ranking.

## What v0 proves

The MVP demonstrates one security-critical vertical slice:

1. Select an employee identity.
2. Ask a question about the SG Batch Payments v2.3 incident.
3. Filter evidence before retrieval using deterministic access policies.
4. Produce an answer with citations from authorised evidence only.
5. Exclude known stale evidence before retrieval.
6. Write a complete, hash-chained audit event.
7. Apply live permission changes on the next query.
8. Let compliance users query the audit trail.

It uses synthetic data and runs in deterministic mock mode when no API key is configured. With a TokenHub API key it uses the benchmark-selected `glm-5.3-flash` model, validates every model citation against the authorised Top-K evidence, and falls back to deterministic synthesis when the endpoint or output is unsafe.

## Run

```bash
cd /Users/panyuxiang/Desktop/hackson
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
# Put the TokenHub key in .env; leave it empty to use mock mode.
.venv/bin/streamlit run app.py
```

## Test

```bash
cd /Users/panyuxiang/Desktop/hackson
.venv/bin/python -m pip install -r requirements-integration.txt -r requirements-part-a-test.txt
.venv/bin/python -m unittest discover -s tests -v
```

The original core tests do not require Streamlit. The unified suite also needs the integration and lightweight Part A test dependencies. Part A's parser/ACL tests run separately with `python -m pytest tests_part_a -q` using a deterministic test tokenizer, without downloading models. Real-model snapshot checks are separate and require the Part A model environment; unit tests do not prove production model quality.

Run the isolated tamper-evidence demo without touching the runtime audit log:

```bash
python3 scripts/demo_audit_tamper.py
```

## v0 reference limitations

- Synthetic data only.
- Fixed demo identities; this is not production authentication.
- Lexical retrieval rather than embeddings.
- Real model answers still use the small synthetic corpus and lexical Top-K retrieval.
- No real Confluence/Slack/Jira/Google Drive connector yet.
- No temporal-authority conflict engine yet.
- The audit head checkpoint is local; production deployment would anchor it in external immutable storage.

See `docs/product/mvp-v0.md` for MVP scope, `docs/source/` for the
Handbook baseline, and `docs/product/roadmap.md` for the implementation order.

## Project management

The Git repository is the project's single source of truth. Start from
`docs/README.md` for the document map and collaboration rules.

Remote repository: <https://github.com/Panyuxiang0830/Hackson_fintech>

After changing requirements, regenerate and validate the traceability view:

```bash
python3 scripts/project_sync.py
python3 scripts/project_sync.py --check
```

See `CONTRIBUTING.md` for the branch and pull-request workflow.
