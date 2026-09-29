import copy
import unittest

from scripts.project_sync import load_registry, render, validate


class ProjectSyncTests(unittest.TestCase):
    def test_current_requirement_registry_is_valid(self):
        data = load_registry()
        self.assertEqual(validate(data), [])
        self.assertIn("权威级别", render(data))

    def test_unknown_authority_is_rejected(self):
        data = copy.deepcopy(load_registry())
        data["requirements"][0]["authority"] = "assumed_official"
        errors = validate(data)
        self.assertTrue(any("非法权威级别" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
