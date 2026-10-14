#!/usr/bin/env bash
set -euo pipefail
INTEGRATION_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$INTEGRATION_ROOT"
INTEGRATION_PYTHON="${INTEGRATION_PYTHON:-$INTEGRATION_ROOT/.venv/bin/python}"
exec "$INTEGRATION_PYTHON" -m contextledger.integration "$@"
