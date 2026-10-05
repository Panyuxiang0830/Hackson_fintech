#!/usr/bin/env bash
set -euo pipefail

PART_A_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PART_A_ROOT"
PART_A_PYTHON="$PART_A_ROOT/.venv/bin/python"

usage() {
    cat <<'EOF'
Usage: bash scripts/part_a.sh [setup|start] [demo options]
  setup  Install dependencies, import datasets, build indexes and check them.
  start  Start the demo (default).
EOF
}

PART_A_COMMAND="${1:-start}"
if [ "$#" -gt 0 ]; then
    shift
fi

case "$PART_A_COMMAND" in
    setup)
        if [ "$#" -gt 0 ]; then
            usage >&2
            exit 2
        fi
        if [ ! -x "$PART_A_PYTHON" ]; then
            python3 -m venv .venv
        fi
        "$PART_A_PYTHON" -m pip install --upgrade pip
        "$PART_A_PYTHON" -m pip install torch==2.6.0 --index-url https://download.pytorch.org/whl/cpu
        "$PART_A_PYTHON" -m pip install -r requirements-part-a.txt
        "$PART_A_PYTHON" scripts/setup_part_a_vectors.py
        if [ ! -f runtime/part_a/canonical.sqlite ] || [ ! -f runtime/part_a/manifest.json ]; then
            "$PART_A_PYTHON" -m contextledger build
        fi
        "$PART_A_PYTHON" -m contextledger augment
        "$PART_A_PYTHON" -m contextledger vectors
        "$PART_A_PYTHON" -m contextledger check
        echo "Setup complete. Run: bash scripts/part_a.sh"
        ;;
    start)
        if [ ! -x "$PART_A_PYTHON" ]; then
            echo "Run first: bash scripts/part_a.sh setup" >&2
            exit 1
        fi
        exec "$PART_A_PYTHON" -m contextledger demo "$@"
        ;;
    -h|--help)
        usage
        ;;
    *)
        usage >&2
        exit 2
        ;;
esac
