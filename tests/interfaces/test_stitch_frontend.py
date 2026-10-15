"""Independent imported UI ships only local assets and preserves its source ledger."""
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "contextledger/interfaces/static/stitch"


class Markup(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.nodes = []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        self.nodes.append((tag, dict(attrs)))


class StitchFrontendTests(unittest.TestCase):
    def setUp(self):
        self.html = (STATIC / "index.html").read_text(encoding="utf-8")
        self.markup = Markup(self.html)

    def test_source_manifest_matches_retained_original_bytes(self):
        manifest = json.loads((STATIC / "source-manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(set(manifest["sources"]), {"home", "radar", "passport", "security", "audit"})
        for page in manifest["sources"].values():
            source = ROOT / page["file"]
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), page["sha256"])
            self.assertIn(b"tailwind.config", source.read_bytes())

    def test_independent_entry_and_local_resources_fit_existing_csp(self):
        pages = {attrs["data-page"] for tag, attrs in self.markup.nodes if tag == "main"}
        self.assertEqual(pages, {"home", "radar", "passport", "security", "audit"})
        scripts = [attrs for tag, attrs in self.markup.nodes if tag == "script"]
        self.assertEqual(len(scripts), 1)
        self.assertTrue(scripts[0]["src"].startswith("/static/stitch/app.js"))
        for tag, attrs in self.markup.nodes:
            self.assertFalse(any(key.startswith("on") for key in attrs))
            self.assertNotIn("style", attrs)
            resource = attrs.get("src") if tag in {"img", "script"} else attrs.get("href") if tag == "link" else None
            if resource:
                self.assertTrue(resource.startswith("/static/stitch/"), resource)
                relative = resource.split("?", 1)[0].removeprefix("/static/stitch/")
                self.assertTrue((STATIC / relative).is_file(), relative)
        self.assertNotIn("/static/unified.css", self.html)
        self.assertNotIn("/static/unified.js", self.html)
        self.assertNotIn('data-action="legacy"', self.html)
        self.assertNotRegex(self.html, r"[\u4e00-\u9fff]")
        self.assertIn('data-slot="planning-toggle"', self.html)
        self.assertIn('/static/stitch/assets/vectorized.svg.svg', self.html)
        self.assertNotIn('Isolated demo', self.html)
        self.assertIn('data-layout="question-card"', self.html)
        self.assertIn('data-layout="passport-context"', self.html)
        self.assertNotRegex((STATIC / "fonts.css").read_text(), r"url\(https?://")

    def test_original_mock_scripts_and_verified_claims_are_not_shipped(self):
        self.assertNotIn("function triggerSearch", self.html)
        self.assertNotIn("setTimeout(() =>", self.html)
        for claim in ("Verified Digest", "SIG_VALID", "99.8%", "480ms", "immutably signed", "Encrypted Payload Container"):
            self.assertNotIn(claim, self.html)
        self.assertIn('data-slot="audit-answer"', self.html)
        self.assertIn('data-slot="binding-select"', self.html)
        self.assertIn('data-slot="needs"', self.html)

    def test_passport_has_no_fixed_demo_nodes_and_accordion_uses_one_visibility_mechanism(self):
        for placeholder in ("item-timeline-1", "item-timeline-2", "item-timeline-3", "Rev 04-B", "3 events synchronized", "INC-84920 awaiting", "FIN-SLA-99.95", "9f8a...31c2"):
            self.assertNotIn(placeholder, self.html)
        panel = next(attrs for _, attrs in self.markup.nodes if attrs.get("data-slot") == "technical")
        self.assertNotIn("hidden", panel.get("class", "").split())
        self.assertIn("hidden", panel)
        toggle = next(attrs for _, attrs in self.markup.nodes if attrs.get("data-action") == "technical")
        self.assertEqual(toggle["aria-controls"], panel["id"])
        self.assertEqual(toggle["aria-expanded"], "false")
        self.assertEqual(sum(attrs.get("data-slot") == "notice-host" for _, attrs in self.markup.nodes), 5)


if __name__ == "__main__":
    unittest.main()
