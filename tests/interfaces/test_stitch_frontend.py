"""Independent imported UI ships only local assets and preserves its source ledger."""
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import shutil
import subprocess
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
        self.assertIn('alt="ContextLedger Logo" class="h-10 w-10 shrink-0 object-contain" width="40" height="40" src="/static/stitch/assets/contextledger-logo.svg"', self.html)
        self.assertIn('<link rel="icon" type="image/svg+xml" href="/static/stitch/assets/contextledger-logo.svg">', self.html)
        self.assertNotIn('081afda20739cb65562a.png', self.html)
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

    def test_audit_workbench_has_ai_four_domains_and_a_rebuildable_source(self):
        script=(STATIC/'app.js').read_text()
        for slot in ('audit-ai-form','audit-ai-question','audit-domains','audit-event-dialog','audit-ai-result'):
            self.assertIn('data-slot="'+slot+'"',self.html)
        for category in ('access','permissions','updates','violations'):
            self.assertIn("['"+category+"',",script)
        self.assertIn("node.open=['access','permissions'].includes(cat)",script)
        self.assertIn("api('/api/audit/ask'",script)
        self.assertIn("if(nav.dataset.nav==='audit')loadAudit()",script)
        manifest=json.loads((STATIC/'source-manifest.json').read_text())['auditConsole']
        self.assertEqual(hashlib.sha256((ROOT/manifest['file']).read_bytes()).hexdigest(),manifest['sha256'])

    @unittest.skipUnless(shutil.which('node'), 'node is required')
    def test_audit_custom_time_range_is_sgt_and_reversed_ranges_are_rejected(self):
        source=(STATIC/'app.js').read_text()
        helper=re.search(r'^function auditRange\(.*?^\}',source,re.M|re.S).group(0)
        js=helper+"\nprocess.stdout.write(JSON.stringify(auditRange('custom','2026-10-16T00:00','2026-10-16T23:59')));"
        result=subprocess.run(['node','-e',js],capture_output=True,text=True,check=True)
        self.assertEqual(json.loads(result.stdout),{'start':'2026-10-15T16:00:00.000Z','end':'2026-10-16T15:59:00.000Z'})
        result=subprocess.run(['node','-e',helper+"\nauditRange('custom','2026-10-17T00:00','2026-10-16T00:00')"],capture_output=True,text=True)
        self.assertNotEqual(result.returncode,0)

    def test_security_lens_controls_resources_instead_of_arbitrary_identity_binding(self):
        for slot in ('content-corpus', 'dataset-access', 'source-controls', 'document-id', 'document-rules', 'attribute-controls', 'project-controls', 'clearance-select', 'project-search', 'project-results', 'doc-policy'):
            self.assertIn('data-slot="' + slot + '"', self.html)
        self.assertIn('allowed source categories', self.html)
        self.assertNotIn('active source bindings', self.html)
        for text in ('Configured demo permissions', 'Demo evidence allows', 'Turning reading off keeps the dataset available'):
            self.assertNotIn(text, self.html)
        self.assertIn('Search projects', self.html)

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

    @unittest.skipUnless(shutil.which("node"), "node is required to run the frontend helper")
    def test_plain_answer_headline_uses_its_own_first_sentence(self):
        source = (STATIC / "app.js").read_text(encoding="utf-8")
        helper = re.search(r"^function answerSummary\(text\) \{.*?^\}$", source, re.M | re.S).group(0)
        cases = [
            "TracePay's current daily transfer limit is CNY 50,000 per customer, effective immediately per the policy document [1].",
            "TitanDB stores ledger snapshots, e.g. daily balances [1]. It also feeds reconciliation [2].\n\nSee the runbook.",
            "限额为每日五万元[1]。其余条款仍待确认[2]。",
            "The evidence lists two metrics:\n- latency [1]\n- packet loss [1]",
            "Version 1.2 shipped on time [3]",
            "",
        ]
        script = helper + "\nconsole.log(JSON.stringify(" + json.dumps(cases) + ".map(answerSummary)));"
        result = json.loads(subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True).stdout)
        self.assertEqual(result[0], {
            "headline": "TracePay's current daily transfer limit is CNY 50,000 per customer, effective immediately per the policy document.",
            "explanation": "Based on authorised source [1].",
        })
        self.assertEqual(result[1], {
            "headline": "TitanDB stores ledger snapshots, e.g. daily balances.",
            "explanation": "It also feeds reconciliation [2].\n\nSee the runbook.",
        })
        self.assertEqual(result[2], {"headline": "限额为每日五万元。", "explanation": "其余条款仍待确认[2]。"})
        self.assertIsNone(result[3])  # A lead-in ending with a colon is not a conclusion.
        self.assertEqual(result[4], {"headline": "Version 1.2 shipped on time", "explanation": "Based on authorised source [3]."})
        self.assertIsNone(result[5])
        self.assertIn("!p&&data.decision==='answered'&&data.provider!=='mock_fallback'?answerSummary(data.answer)", source)
        # Answers follow the question's language: the page no longer forces English output.
        self.assertNotIn("output_language:'en'", source)
        zh = json.loads(subprocess.run(["node", "-e", helper + "\nconsole.log(JSON.stringify(answerSummary('限额为每日十万元 [1]。')))"],
                                       capture_output=True, text=True, check=True).stdout)
        self.assertEqual(zh, {"headline": "限额为每日十万元。", "explanation": "依据授权来源 [1]。"})


if __name__ == "__main__":
    unittest.main()
