# ContextLedger MVP

Permission-aware enterprise knowledge assistant for the Tencent Cloud AI CAN DO IT 2026 FinTech track.

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
python3 -m unittest discover -s tests -v
```

The core tests use only Python's standard library, so they do not require Streamlit.

Run the isolated tamper-evidence demo without touching the runtime audit log:

```bash
python3 scripts/demo_audit_tamper.py
```

## Current limitations

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
