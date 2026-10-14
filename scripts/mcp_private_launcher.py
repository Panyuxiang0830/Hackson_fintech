"""CLI entrypoint; implementation lives in contextledger.interfaces.private_launcher."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from contextledger.interfaces.private_launcher import main

if __name__ == "__main__":
    raise SystemExit(main())
