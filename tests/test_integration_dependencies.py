"""Keep the Flask OAuth HTTP transport declared in the standalone installer."""

from pathlib import Path
import re
import unittest


class IntegrationDependencyTests(unittest.TestCase):
    def test_oauth_requests_transport_is_an_explicit_dependency(self):
        manifest = (Path(__file__).resolve().parents[1] / "requirements-integration.txt").read_text(
            encoding="utf-8"
        )
        names = {
            re.split(r"[<>=!~\s\[]", line.strip(), maxsplit=1)[0].lower()
            for line in manifest.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }
        self.assertIn("authlib", names)
        self.assertIn("requests", names, "Authlib's Flask client imports the Requests transport")


if __name__ == "__main__":
    unittest.main()
