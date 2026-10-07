import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


SHIM = f"""#!{sys.executable}
import json
import os
from pathlib import Path
import sys

args = sys.argv[1:]
with Path('calls.jsonl').open('a') as stream:
    stream.write(json.dumps(args) + '\\n')
if os.environ.get('PART_A_TEST_FAIL') in args:
    sys.exit(7)
if args[:2] == ['-m', 'venv']:
    target = Path(args[2]) / 'bin/python'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(Path(__file__).read_text())
    target.chmod(0o755)
if args == ['-m', 'contextledger', 'build']:
    path = Path('runtime/part_a/canonical.sqlite')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'new database')
    path.with_name('manifest.json').write_text('{{}}')
"""


class PartALauncherTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="part a ")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        scripts = self.root / "scripts"
        scripts.mkdir()
        self.launcher = scripts / "part_a.sh"
        shutil.copyfile(Path(__file__).resolve().parents[1] / "scripts/part_a.sh", self.launcher)
        self.fake_python(self.root / "bin/python3")
        self.environment = dict(os.environ, PATH=f"{self.root / 'bin'}:{os.environ['PATH']}")

    def fake_python(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(SHIM)
        path.chmod(0o755)

    def run_launcher(self, *args):
        return subprocess.run(
            ["bash", str(self.launcher), *args],
            cwd=self.root.parent,
            env=self.environment,
            capture_output=True,
            text=True,
        )

    def calls(self):
        return [json.loads(line) for line in (self.root / "calls.jsonl").read_text().splitlines()]

    def test_fresh_setup_creates_environment_and_prepares_data(self):
        result = self.run_launcher("setup")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.root / ".venv/bin/python").exists())
        self.assertTrue((self.root / "runtime/part_a/canonical.sqlite").exists())
        self.assertIn(["-m", "contextledger", "vectors"], self.calls())
        self.assertEqual(self.calls()[-1], ["-m", "contextledger", "check"])

    def test_existing_database_is_not_rebuilt(self):
        self.fake_python(self.root / ".venv/bin/python")
        database = self.root / "runtime/part_a/canonical.sqlite"
        database.parent.mkdir(parents=True)
        database.write_bytes(b"existing data")
        database.with_name("manifest.json").write_text("{}")
        result = self.run_launcher("setup")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(database.read_bytes(), b"existing data")
        self.assertNotIn(["-m", "contextledger", "build"], self.calls())
        self.assertLess(self.calls().index(["-m", "contextledger", "rechunk"]),
                        self.calls().index(["-m", "contextledger", "vectors"]))

    def test_interrupted_import_is_rebuilt(self):
        self.fake_python(self.root / ".venv/bin/python")
        database = self.root / "runtime/part_a/canonical.sqlite"
        database.parent.mkdir(parents=True)
        database.write_bytes(b"partial data")
        result = self.run_launcher("setup")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(database.read_bytes(), b"new database")
        self.assertTrue(database.with_name("manifest.json").exists())

    def test_failed_native_setup_stops_before_data_import(self):
        self.environment["PART_A_TEST_FAIL"] = "scripts/setup_part_a_vectors.py"
        result = self.run_launcher("setup")
        self.assertEqual(result.returncode, 7)
        self.assertFalse((self.root / "runtime/part_a").exists())
        self.assertFalse(any("contextledger" in call for call in self.calls()))

    def test_start_forwards_demo_options_without_setup(self):
        self.fake_python(self.root / ".venv/bin/python")
        result = self.run_launcher("start", "--port", "7862")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls(), [["-m", "contextledger", "demo", "--port", "7862"]])

    def test_start_without_environment_points_to_setup(self):
        result = self.run_launcher()
        self.assertEqual(result.returncode, 1)
        self.assertIn("bash scripts/part_a.sh setup", result.stderr)
        self.assertFalse((self.root / ".venv").exists())

    def test_eval_forwards_options_without_rebuilding(self):
        self.fake_python(self.root / ".venv/bin/python")
        result = self.run_launcher("eval", "--limit", "10")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls(), [["-m", "contextledger", "eval", "--limit", "10"]])

    def test_tune_forwards_the_target_without_rebuilding(self):
        self.fake_python(self.root / ".venv/bin/python")
        result = self.run_launcher("tune", "--target", ".99")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls(), [["scripts/tune_part_a_retrieval.py", "--target", ".99"]])

    def test_refine_forwards_options_without_rebuilding(self):
        self.fake_python(self.root / ".venv/bin/python")
        result = self.run_launcher("refine", "--target", ".90")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls(), [["scripts/refine_part_a_retrieval.py", "--target", ".90"]])


if __name__ == "__main__":
    unittest.main()
