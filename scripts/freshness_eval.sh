#!/usr/bin/env bash
set -euo pipefail
FRESHNESS_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$FRESHNESS_ROOT"
FRESHNESS_PYTHON="${FRESHNESS_PYTHON:-$FRESHNESS_ROOT/.venv/bin/python}"
exec "$FRESHNESS_PYTHON" -m contextledger.evaluation.freshness "$@"
