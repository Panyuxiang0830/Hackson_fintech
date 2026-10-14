"""Directory moves must preserve discovery, CLI, resources and MCP transport."""
import ast
import asyncio
import importlib
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from contextledger.paths import PROJECT_ROOT


class FunctionalPackageTests(unittest.TestCase):
    def test_business_packages_do_not_depend_on_scripts_or_retired_src(self):
        for path in (PROJECT_ROOT / "contextledger").rglob("*.py"):
            for node in ast.walk(ast.parse(path.read_text())):
                names = ([node.module or ""] if isinstance(node, ast.ImportFrom)
                         else [alias.name for alias in node.names] if isinstance(node, ast.Import) else [])
                self.assertFalse(any(name == "src" or name.startswith(("src.", "scripts."))
                                     for name in names), str(path))

    def test_old_sample_files_and_test_root_are_retired(self):
        for path in ("data/documents.json", "data/users.json", "app.py",
                     "tests_part_a/test_supplemental.py"):
            self.assertFalse((PROJECT_ROOT / path).exists(), path)
        self.assertFalse(list((PROJECT_ROOT / "src").glob("*.py")))

    def test_all_functional_packages_import(self):
        for package in ("application", "access", "ingestion", "storage", "retrieval",
                        "answering", "radar", "audit", "interfaces", "evaluation"):
            with self.subTest(package=package):
                importlib.import_module("contextledger." + package)

    def test_compatibility_cli_modules_share_the_same_main(self):
        aliases = {"contextledger.__main__": "contextledger.interfaces.part_a",
                   "contextledger.integration": "contextledger.interfaces.integration",
                   "contextledger.source_sync": "contextledger.ingestion.source_sync",
                   "contextledger.tool_api": "contextledger.interfaces.tool_api",
                   "contextledger.mcp_server": "contextledger.interfaces.mcp_server",
                   "contextledger.freshness_eval": "contextledger.evaluation.freshness"}
        for alias, canonical in aliases.items():
            with self.subTest(alias=alias):
                self.assertIs(importlib.import_module(alias).main, importlib.import_module(canonical).main)

    def test_script_cli_can_start_outside_checkout(self):
        for script in ("mcp_private_launcher.py", "radar_demo.py", "evaluate_chat_latency.py",
                       "refine_part_a_retrieval.py", "evaluate_part_a_chunking.py",
                       "expand_part_a_candidates.py", "check_part_a_ui.py", "check_chat_ui.py"):
            with self.subTest(script=script), tempfile.TemporaryDirectory() as directory:
                result = subprocess.run([sys.executable, str(PROJECT_ROOT / "scripts" / script), "--help"],
                                        cwd=directory, capture_output=True, text=True, timeout=20)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("usage:", result.stdout)

    def test_frontend_resources_are_next_to_web_interface(self):
        from contextledger.interfaces import web
        directory = Path(web.__file__).parent
        for asset in ("templates/unified.html", "templates/part_a.html",
                      "static/unified.js", "static/unified.css", "static/onboarding.svg"):
            self.assertTrue((directory / asset).is_file(), asset)
        # Exercise Flask resource resolution, not just presence on disk.
        from tests.application.test_integration import IntegrationTests
        fixture = IntegrationTests()
        fixture.setUp()
        try:
            self.assertEqual(fixture.client.get("/").status_code, 200)
            for asset in ("unified.js", "unified.css", "onboarding.svg"):
                with fixture.client.get("/static/" + asset) as response:
                    self.assertEqual(response.status_code, 200, asset)
        finally:
            fixture.app.extensions["document_updates"].close()
            fixture.doCleanups()

    def test_part_a_tokenizer_fixture_keeps_local_scope(self):
        self.assertTrue((PROJECT_ROOT / "tests/ingestion/part_a/conftest.py").is_file())
        self.assertFalse((PROJECT_ROOT / "tests/conftest.py").exists())
        self.assertFalse((PROJECT_ROOT / "tests/ingestion/conftest.py").exists())


class MCPTransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_private_launcher_still_speaks_stdio_protocol_after_move(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        from contextledger.interfaces.tool_api import write_credential_file
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "credentials.json"
            # Synthetic token, no upstream request, real handshake only.
            write_credential_file(path, {"token": "clt_" + "a" * 32 + "." + "b" * 40})
            parameters = StdioServerParameters(command=sys.executable, args=[
                str(PROJECT_ROOT / "scripts/mcp_private_launcher.py"), "--credentials", str(path)])

            async def handshake():
                async with stdio_client(parameters) as (reader, writer):
                    async with ClientSession(reader, writer) as session:
                        await session.initialize()
                        result = await session.list_tools()
                        self.assertEqual({tool.name for tool in result.tools}, {"search", "fetch"})
                        for tool in result.tools:
                            self.assertTrue(tool.annotations.readOnlyHint)
                            self.assertNotIn("user_id", tool.inputSchema["properties"])

            await asyncio.wait_for(handshake(), timeout=20)
