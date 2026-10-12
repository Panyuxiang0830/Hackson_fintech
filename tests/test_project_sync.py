import copy
import unittest
from unittest.mock import patch

from scripts.project_sync import load_registry, main, render, validate


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

    @staticmethod
    def extension_registry():
        data = copy.deepcopy(load_registry())
        item = data["requirements"][0]
        item["status"] = "in_progress"
        item["extensions"] = [{
            "key": "example_extension", "title": "团队示例功能",
            "source": "test fixture", "authority": "team_decision", "status": "planned",
            "description": "待实现的团队扩展", "acceptance_criteria": ["示例验收"],
            "code": [], "tests": [], "docs": ["docs/README.md"],
        }]
        return data

    def test_extensions_render_independent_authority_status_and_paths(self):
        data = self.extension_registry()
        self.assertEqual(validate(data), [])
        view = render(data)
        self.assertIn("### 功能扩展 · 团队示例功能", view)
        self.assertIn("`team_decision`（独立于基础需求）", view)
        self.assertIn("- 状态：`planned`", view)
        self.assertIn("- 扩展键：`example_extension`", view)
        base_criterion = data["requirements"][0]["acceptance_criteria"][0]
        self.assertLess(view.index(f"  - {base_criterion}"), view.index("### 功能扩展 · 团队示例功能"))

    def test_duplicate_extension_key_is_rejected(self):
        data = self.extension_registry()
        item = data["requirements"][0]
        item["extensions"].append(copy.deepcopy(item["extensions"][0]))
        self.assertTrue(any("重复的功能扩展 key" in error for error in validate(data)))

    def test_invalid_extension_fields_and_missing_paths_are_rejected(self):
        data = self.extension_registry()
        extension = data["requirements"][0]["extensions"][0]
        extension.update(status="maybe", authority="assumed_official", docs=["missing-planned-feature.md"])
        errors = validate(data)
        self.assertTrue(any("非法状态" in error for error in errors))
        self.assertTrue(any("非法权威级别" in error for error in errors))
        self.assertTrue(any("文件不存在" in error for error in errors))

    def test_pending_extension_prevents_claiming_parent_complete(self):
        data = self.extension_registry()
        data["requirements"][0]["status"] = "implemented"
        self.assertTrue(any("整体状态不能" in error for error in validate(data)))

    def test_invalid_extension_structure_stops_before_render_or_write(self):
        data = self.extension_registry()
        data["requirements"][0]["extensions"] = "not a list"
        with patch("scripts.project_sync.load_registry", return_value=data), \
                patch("scripts.project_sync.render") as renderer, \
                patch("sys.argv", ["project_sync.py"]):
            self.assertEqual(main(), 1)
            renderer.assert_not_called()


if __name__ == "__main__":
    unittest.main()
