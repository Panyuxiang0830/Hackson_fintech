import unittest

from scripts.sync_preview_config import preview_config


class PreviewConfigTests(unittest.TestCase):
    def test_whitelist_excludes_local_app_oidc_and_unrelated_keys(self):
        values = {"LLM_API_KEY": "fixture-token", "OIDC_CLIENT_SECRET": "never-sync", "APP_SECRET_KEY": "never-sync",
                  "OTHER_API_KEY": "never-sync", "LLM_MODEL": "fixture-model"}
        payload = preview_config(values, "http://127.0.0.1:17860", "/tmp/isolated-demo", "http://127.0.0.1:6335")
        self.assertEqual(payload["LLM_API_KEY"], "fixture-token")
        self.assertEqual(payload["LLM_MODEL"], "fixture-model")
        self.assertEqual(payload["DEMO_MODE"], "true")
        self.assertNotIn("OIDC_CLIENT_SECRET", payload)
        self.assertNotIn("APP_SECRET_KEY", payload)
        self.assertNotIn("OTHER_API_KEY", payload)
        self.assertNotIn("HF_HOME", payload)

    def test_embedding_cache_requires_explicit_absolute_server_path(self):
        payload = preview_config({"LLM_API_KEY": "fixture-token", "HF_HOME": "/local/ignored"},
                                 "http://127.0.0.1:17860", "/tmp/isolated-demo", "http://127.0.0.1:6335",
                                 "/server/existing-cache")
        self.assertEqual(payload["HF_HOME"], "/server/existing-cache")
        for path in ("relative/cache", "/cache\nOTHER=value", "/cache\x00"):
            with self.assertRaises(ValueError):
                preview_config({"LLM_API_KEY": "fixture-token"}, "http://127.0.0.1:17860",
                               "/tmp/isolated-demo", "http://127.0.0.1:6335", path)

    def test_public_preview_and_missing_or_multiline_key_are_rejected(self):
        for values, url in (({}, "http://127.0.0.1:17860"),
                            ({"LLM_API_KEY": "token\nother=value"}, "http://127.0.0.1:17860"),
                            ({"LLM_API_KEY": "token"}, "http://example.com:17860")):
            with self.assertRaises(ValueError):
                preview_config(values, url, "/tmp/isolated-demo", "http://127.0.0.1:6335")


if __name__ == "__main__":
    unittest.main()
