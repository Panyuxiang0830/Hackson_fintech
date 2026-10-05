"""Build the pinned RaBitQ bindings for this Python interpreter."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

REVISION = "5ea4df06b8dc5de3889f16084f93544f55c77212"
SOURCE = f"git+https://github.com/VectorDB-NTU/RaBitQ-Library.git@{REVISION}"
ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=Path, default=ROOT / "runtime" / "rabitq-dist")
    args = parser.parse_args()
    target = args.target.resolve()
    target.mkdir(parents=True, exist_ok=True)
    environment = dict(os.environ)
    environment.setdefault("CMAKE_BUILD_PARALLEL_LEVEL", "2")
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "--upgrade", "--no-deps", "--target", str(target), SOURCE],
        env=environment,
        check=True,
    )
    subprocess.run(
        [sys.executable, "-c", "import sys; sys.path.insert(0, sys.argv[1]); from rabitqlib import IvfIndex; index = IvfIndex(384, 32, 1, 8, 'ip'); print('RaBitQ IVF bindings ready')", str(target)],
        check=True,
    )
    (target / "source.json").write_text(json.dumps({"repository": "https://github.com/VectorDB-NTU/RaBitQ-Library", "revision": REVISION, "python": sys.version}, indent=2) + "\n")


if __name__ == "__main__":
    main()
