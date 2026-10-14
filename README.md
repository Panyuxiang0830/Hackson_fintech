# ContextLedger

Permission-aware enterprise knowledge assistant for the Tencent Cloud AI CAN DO IT 2026 FinTech track.

## Current capabilities

The unified service connects source data, canonical SQLite storage and filtered Qdrant/FTS retrieval to persistent system permissions, cited answers and query audit. The frontend remains an acceptance/demo interface. Browser OIDC is deferred and disabled by default; identities and permission checks are not removed.

- Offline import, source-aware parsing, chunking and canonical storage.
- ACL-first hybrid retrieval, optional bounded question planning and final-delivery rechecks.
- Cited answers, optional internal Decision Radar, and safe zero-evidence responses.
- Administrator revocation and persistent document updates, version history and checked index publication.
- Transactional hash-chained audit, redacted compliance queries and optional model explanations.
- Opt-in read-only Jira, Slack, Confluence and Google Drive adapters; private search/fetch MCP tools for host agents.

Host-model answers are the tool default; internal GLM/OpenAI-compatible generation is separately opt-in. Generation defaults remain `glm-5.3-flash`, low reasoning for ordinary calls and high only for post-Radar synthesis. Citation-scope checks are not claim-by-claim factual verification. Failed/unsafe model output is not presented as a successful answer.

An explicitly enabled, loopback-only demo provides one independent administrator and six employees. It is not production authentication; ordinary unauthenticated APIs remain locked. Source ACL mappings are verified subsets, not complete enterprise permission synchronization.

## Run

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
bash scripts/integration.sh --help
```

Use [Part A Quick Start](QUICKSTART.md) for offline data/model setup, [unified setup](docs/architecture/unified-integration.md) for Qdrant publication, and [demo acceptance](docs/product/demo-acceptance.md) for isolated demo accounts. MCP/source configuration is in [source/Agent interfaces](docs/architecture/source-and-agent-interfaces.md). These commands do not provision production identities.

The functional-package refactor preserves existing CLI arguments and database/index formats. It does not require an index rebuild. The retired Streamlit `app.py` and two old JSON sample files were removed; runtime datasets, identity/audit stores and server state are untouched.

## Code map

Business code lives in `contextledger/`, grouped into `application`, `access`, `ingestion`, `storage`, `retrieval`, `answering`, `radar`, `audit`, `interfaces` and `evaluation`. `scripts/` contains thin CLI entries and standalone operations/project tools; `tests/` mirrors functional areas; `fixtures/` retains fixed business cases. See [module map and migration](docs/architecture/functional-packages.md).

## Test

```bash
.venv/bin/python -m pip install -r requirements-integration.txt -r requirements-part-a-test.txt -r requirements-tools.txt
.venv/bin/python scripts/project_sync.py --check
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m pytest tests -q
node --check contextledger/interfaces/static/unified.js
```

All tests are under `tests/`. Shared core tests construct small records. Part A's test tokenizer is scoped to `tests/ingestion/part_a/`, without model downloads. Pytest includes the unittest cases plus eight parser/ACL tests; counts are not additive.

Run the tamper demonstration against a temporary database (not runtime audit state):

```bash
.venv/bin/python scripts/demo_audit_tamper.py
```

## Verification boundaries

Local regressions include native in-memory Qdrant, permissions, updates, audit and actual stdio MCP handshake. They do not prove live four-platform ACL completeness, enterprise identity integration, real-source timing, unseen-case answer quality or production performance. Offline RaBitQ remains available for Part A; unified serving uses filtered Qdrant. Model citation review remains cancelled; the audit checkpoint is local, not externally immutable.

Historical v0 specifications remain in [mvp-v0](docs/product/mvp-v0.md); current status is recorded in `project/requirements.json`, not historical deployment notes. Official sources are under `docs/source/`.

## Project management

The Git repository is the single source of truth. See [document map](docs/README.md) and [contribution workflow](CONTRIBUTING.md). Remote: <https://github.com/Panyuxiang0830/Hackson_fintech>.

After changing requirements:

```bash
python3 scripts/project_sync.py
python3 scripts/project_sync.py --check
```
