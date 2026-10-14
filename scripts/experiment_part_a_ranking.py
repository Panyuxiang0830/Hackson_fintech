"""CLI entrypoint; implementation lives in contextledger.evaluation.ranking."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from contextledger.evaluation.ranking import main

if __name__ == "__main__":
    raise SystemExit(main())
