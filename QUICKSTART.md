# Part A Quick Start

> `demo` opens the unified frontend for current acceptance. Browser login is deferred and disabled by default, but identity/permissions remain. Optional [MCP/source adapters](docs/architecture/source-and-agent-interfaces.md) coexist with the frontend. The explicitly enabled isolated demo offers one administrator and six employees; ordinary unauthenticated APIs remain locked. Commands below prepare offline Part A artifacts but do not publish Qdrant or provision demo accounts. See [demo acceptance](docs/product/demo-acceptance.md), [unified setup](docs/architecture/unified-integration.md) and [functional package map](docs/architecture/functional-packages.md). Do not continue Auth0 configuration for the current scope.

Requires Linux x86_64 (AVX2), Python 3.10, Git and a C++17/OpenMP compiler.
Run from the repository root:

```bash
bash scripts/part_a.sh setup
bash scripts/part_a.sh
```

Open <http://127.0.0.1:7860>. Setup downloads the datasets and model.
To restart, run only the second command. Re-run setup to migrate existing
stores to title/section-aware chunks within the model's 256-token limit.

For evaluation, see [Benchmark Quick Start](BENCHMARK_QUICKSTART.md).

## Add or update a document

After [unified setup](docs/architecture/unified-integration.md) publishes the
initial Qdrant snapshot, use an existing administrator. Save this request as
`runtime/document-update.json`:

```json
{
  "corpus": "orgforge",
  "doc_id": "payment-policy-demo",
  "source": "confluence",
  "title": "PaymentPolicy transfer limits",
  "text": "PaymentPolicy daily transfer limit is 50,000 CNY.",
  "acl": ["orgforge:Jax"],
  "expected_version": null,
  "source_updated_at": "2026-10-13T00:00:00Z"
}
```

Replace `ADMIN_ID` with your administrator ID and use the existing content and
security directories:

```bash
bash scripts/integration.sh --out runtime/part_a --security-dir runtime/security-demo \
  upsert --admin-id ADMIN_ID --file runtime/document-update.json
```

The command waits for `state: ready` and returns the new `version`. To modify
the document, keep its ID, set `expected_version` to that returned version,
change the text to `100,000 CNY`, and run the same command. Ask the same question
in the frontend: keyword, vector and hybrid retrieval now use the new evidence.

The web server also processes `POST /api/admin/documents` automatically. It
requires an administrator session and CSRF token; poll
`GET /api/admin/document-updates/JOB_ID` until ready. Pending or failed updates
temporarily block retrieval. Jobs survive restarts and retry up to three times;
use `retry-update --admin-id ADMIN_ID --job JOB_ID` to retry an exhausted job.
Old versions remain in the history store. Source-platform polling is a separate
connector task; these commands submit the observed change explicitly.
Legacy Part A vector caches become unavailable after an update until rebuilt;
the unified frontend uses the automatically updated Qdrant index.
