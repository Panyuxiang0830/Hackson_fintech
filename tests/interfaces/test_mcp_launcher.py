import asyncio
import json
from pathlib import Path
import tempfile
import unittest

from contextledger.interfaces.mcp_server import create_server
from contextledger.interfaces.tool_api import write_credential_file
from contextledger.interfaces.private_launcher import load_token


class MCPLauncherTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.root.chmod(0o700)
        self.path = self.root / "credential.json"
        self.token = "clt_" + "a" * 32 + "." + "x" * 43

    def test_private_file_round_trip_no_overwrite(self):
        write_credential_file(self.path, {"token": self.token})
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(load_token(self.path), self.token)
        with self.assertRaises(FileExistsError):
            write_credential_file(self.path, {"token": "replacement"})
        self.assertEqual(load_token(self.path), self.token)

    def test_public_directory_or_file_is_rejected(self):
        self.root.chmod(0o755)
        with self.assertRaises(ValueError):
            write_credential_file(self.path, {"token": self.token})
        self.root.chmod(0o700)
        write_credential_file(self.path, {"token": self.token})
        self.path.chmod(0o644)
        with self.assertRaises(ValueError):
            load_token(self.path)

    def test_symlink_and_invalid_token_rejected(self):
        write_credential_file(self.path, {"token": self.token})
        alias = self.root / "alias"
        alias.symlink_to(self.path)
        with self.assertRaises(ValueError):
            load_token(alias)
        other = self.root / "bad.json"
        write_credential_file(other, {"token": "not-a-personal-token"})
        with self.assertRaises(ValueError):
            load_token(other)

    def test_actual_sdk_registers_only_read_tools_by_default(self):
        from unittest.mock import patch
        with patch.dict("os.environ", {"CL_MCP_ENABLE_ASK": "false", "CL_MCP_ENABLE_AUDIT": "false"}):
            server = create_server(client=object())
            tools = asyncio.run(server.list_tools())
        self.assertEqual({tool.name for tool in tools}, {"search", "fetch"})
        for tool in tools:
            self.assertTrue(tool.annotations.readOnlyHint)
            self.assertNotIn("user_id", tool.inputSchema["properties"])


if __name__ == "__main__":
    unittest.main()
