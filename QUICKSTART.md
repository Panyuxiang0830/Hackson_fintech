# Part A Quick Start

> Integration branch: `demo` now opens the authenticated unified UI. The commands below prepare offline Part A artifacts but do not configure OIDC or publish Qdrant. Follow [unified setup and acceptance](docs/architecture/unified-integration.md) before querying; there is no arbitrary demo-identity login.

Requires Linux x86_64 (AVX2), Python 3.10, Git and a C++17/OpenMP compiler.

Run from the repository root:

```bash
bash scripts/part_a.sh setup
bash scripts/part_a.sh
```

Open <http://127.0.0.1:7860>.

Setup downloads the datasets and model. To restart, run only the second command.
