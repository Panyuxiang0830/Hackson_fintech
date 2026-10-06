# Part A Quick Start

> Integration branch: `demo` opens the unified Part A-style frontend for current acceptance. Browser login is deferred and disabled by default, but identity/permissions remain. A future Agent tool is deferred and is not required for this release. The explicitly enabled isolated demo offers one administrator and six employees; ordinary unauthenticated APIs remain locked. The commands below prepare offline Part A artifacts but do not publish Qdrant or provision demo accounts. See [demo acceptance](docs/product/demo-acceptance.md) and [unified setup](docs/architecture/unified-integration.md); do not continue Auth0 configuration for the current scope.

Requires Linux x86_64 (AVX2), Python 3.10, Git and a C++17/OpenMP compiler.

Run from the repository root:

```bash
bash scripts/part_a.sh setup
bash scripts/part_a.sh
```

Open <http://127.0.0.1:7860>.

Setup downloads the datasets and model. To restart, run only the second command.
