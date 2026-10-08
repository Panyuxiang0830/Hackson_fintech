"""Rebuild snapshots do not share mutable vector artifacts with Part A."""

from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from scripts.prepare_integration_preview import main


class PreparePreviewTests(unittest.TestCase):
    def test_fresh_vectors_keeps_original_artifacts_and_copies_database(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, target = root / "source", root / "target"
            source.mkdir()
            (source / "raw").mkdir()
            (source / "vectors").mkdir()
            (source / "vectors/meta.json").write_text('{"sentinel":true}')
            with sqlite3.connect(source / "canonical.sqlite") as db:
                db.execute("CREATE TABLE example (value TEXT)")
                db.execute("INSERT INTO example VALUES ('original')")
            with patch("sys.argv", ["prepare", "--source", str(source), "--target", str(target), "--fresh-vectors"]):
                main()
            self.assertFalse((target / "vectors").exists())
            self.assertTrue((target / "raw").is_symlink())
            with sqlite3.connect(target / "canonical.sqlite") as db:
                db.execute("UPDATE example SET value='copy-only'")
            with sqlite3.connect(source / "canonical.sqlite") as db:
                self.assertEqual(db.execute("SELECT value FROM example").fetchone()[0], "original")
            self.assertEqual((source / "vectors/meta.json").read_text(), '{"sentinel":true}')

    def test_existing_target_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, target = root / "source", root / "target"
            for folder in (source, target):
                folder.mkdir()
                with sqlite3.connect(folder / "canonical.sqlite") as db:
                    db.execute("CREATE TABLE example (value TEXT)")
            with patch("sys.argv", ["prepare", "--source", str(source), "--target", str(target), "--fresh-vectors"]):
                with self.assertRaises(SystemExit):
                    main()


if __name__ == "__main__":
    unittest.main()
