from contextledger.paths import PROJECT_ROOT
"""Keep the Flask OAuth HTTP transport declared in the standalone installer."""

from pathlib import Path
import re
import unittest


class IntegrationDependencyTests(unittest.TestCase):
    def test_oauth_requests_transport_is_an_explicit_dependency(self):
        manifest = (PROJECT_ROOT / "requirements-integration.txt").read_text(
            encoding="utf-8"
        )
        names = {
            re.split(r"[<>=!~\s\[]", line.strip(), maxsplit=1)[0].lower()
            for line in manifest.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }
        self.assertIn("authlib", names)
        self.assertIn("requests", names, "Authlib's Flask client imports the Requests transport")

    def test_ci_installs_both_integration_and_part_a_test_dependencies(self):
        root = PROJECT_ROOT
        workflow = (root / ".github/workflows/ci.yml").read_text()
        self.assertIn("-r requirements-integration.txt -r requirements-part-a-test.txt", workflow)
        self.assertIn("-r requirements-tools.txt", workflow)
        self.assertIn("python3 -m pytest tests -q", workflow)
        lightweight = (root / "requirements-part-a-test.txt").read_text()
        self.assertIn("huggingface-hub", lightweight)
        self.assertIn("pyarrow", lightweight)


if __name__ == "__main__":
    unittest.main()
