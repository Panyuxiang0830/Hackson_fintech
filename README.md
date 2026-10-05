# ContextLedger MVP

Permission-aware enterprise knowledge assistant for the Tencent Cloud AI CAN DO IT 2026 FinTech track.

## Quick Start: Part A

在仓库根目录执行。环境：Linux x86_64、Python 3.10、支持 AVX2 的 CPU；需要 Git、C++17 编译器和 OpenMP。

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install torch==2.6.0 --index-url https://download.pytorch.org/whl/cpu
.venv/bin/python -m pip install -r requirements-part-a.txt
.venv/bin/python scripts/setup_part_a_vectors.py

.venv/bin/python -m contextledger build --out runtime/part_a
.venv/bin/python -m contextledger augment --out runtime/part_a
.venv/bin/python -m contextledger vectors --out runtime/part_a
.venv/bin/python -m contextledger check --out runtime/part_a
.venv/bin/python -m contextledger demo --out runtime/part_a --port 7860
```

打开 <http://127.0.0.1:7860>。首次运行会下载数据和模型；后续启动只需执行最后一条命令。详细说明见 [Part A](docs/product/part-a.md)。

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

It uses synthetic data and runs in deterministic mock mode by default. A real OpenAI-compatible model can be connected later through environment variables.

## Run

```bash
cd /Users/panyuxiang/Desktop/hackson
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
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

The limitations below describe the original `src/` / Streamlit MVP. The separate
Part A module adds offline datasets and vector retrieval; see the next section.

- Synthetic data only.
- Fixed demo identities; this is not production authentication.
- Lexical retrieval rather than embeddings.
- Mock answer synthesis by default.
- No real Confluence/Slack/Jira/Google Drive connector yet.
- No temporal-authority conflict engine yet.
- The audit head checkpoint is local; production deployment would anchor it in external immutable storage.

## Part A: datasets and vector retrieval

`contextledger/` adds an independent Flask demo on port 7860, offline imports
for EnterpriseRAG, OrgForge, PrivacyBench Slack/Drive, and a Public Jira sample,
plus SQLite FTS5 and 384-dimensional, 8-bit RaBitQ IVF indexes per corpus.

See [Part A setup, dataset scope, and verification](docs/product/part-a.md) for
the install/build/check/demo commands. Runtime datasets and indexes are rebuilt
locally. This demo performs ACL checks after candidate retrieval and on document
open; production integration still needs the pre-retrieval authorization boundary
required by REQ-002. The existing Streamlit answer/audit path remains independent.

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
