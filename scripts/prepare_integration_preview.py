"""Copy a consistent offline snapshot without changing the deployed Part A DB."""

import argparse
from pathlib import Path
import sqlite3


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--target", type=Path, required=True)
    args = parser.parse_args()
    source, target = args.source.resolve(), args.target.resolve()
    if source == target or source in target.parents or target in source.parents:
        parser.error("source and target must be separate directories")
    if not (source / "canonical.sqlite").is_file():
        parser.error("source database missing")
    target.mkdir(parents=True, exist_ok=True)
    destination = target / "canonical.sqlite"
    if destination.exists():
        parser.error("target database exists; refusing to overwrite")
    origin = sqlite3.connect((source / "canonical.sqlite").as_uri() + "?mode=ro", uri=True)
    copied = sqlite3.connect(destination)
    try:
        origin.backup(copied)
    finally:
        origin.close()
        copied.close()
    for name in ("vectors", "raw"):
        original = source / name
        if original.exists():
            (target / name).symlink_to(original, target_is_directory=True)
    print(f"Preview snapshot ready: {destination}; raw/vector artifacts reused without copying")


if __name__ == "__main__":
    main()
