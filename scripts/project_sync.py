#!/usr/bin/env python3
"""Generate and validate the human-readable requirement view."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "project" / "requirements.json"
OUTPUT = ROOT / "docs" / "requirements.md"
ALLOWED_STATUSES = {"planned", "in_progress", "implemented", "validated", "deferred"}
ALLOWED_AUTHORITIES = {
    "handbook_mandatory",
    "handbook_guidance",
    "team_decision",
    "pending_confirmation",
}


def load_registry() -> dict:
    return json.loads(REGISTRY.read_text(encoding="utf-8"))


def validate(data: dict) -> list[str]:
    errors: list[str] = []
    requirements = data.get("requirements", [])
    ids = [item.get("id") for item in requirements]

    if len(ids) != len(set(ids)):
        errors.append("存在重复的需求 ID")

    for item in requirements:
        requirement_id = item.get("id", "<missing>")
        if not isinstance(requirement_id, str) or not requirement_id.startswith("REQ-"):
            errors.append(f"非法需求 ID：{requirement_id}")
        if item.get("status") not in ALLOWED_STATUSES:
            errors.append(f"{requirement_id} 使用了非法状态：{item.get('status')}")
        if item.get("authority") not in ALLOWED_AUTHORITIES:
            errors.append(f"{requirement_id} 使用了非法权威级别：{item.get('authority')}")
        if not item.get("acceptance_criteria"):
            errors.append(f"{requirement_id} 缺少验收标准")

        for field in ("code", "tests", "docs"):
            for relative_path in item.get(field, []):
                if not (ROOT / relative_path).exists():
                    errors.append(f"{requirement_id} 引用的 {field} 文件不存在：{relative_path}")

    return errors


def render(data: dict) -> str:
    lines = [
        "# 需求与追踪矩阵",
        "",
        "> 此文件由 `project/requirements.json` 自动生成，请勿手工修改。",
        "",
        f"最后更新：{data['updated_at']}",
        "",
        "| ID | 需求 | 权威级别 | 状态 | 代码 | 测试 |",
        "|---|---|---|---|---|---|",
    ]

    for item in data["requirements"]:
        code = "<br>".join(f"`{path}`" for path in item.get("code", [])) or "—"
        tests = "<br>".join(f"`{path}`" for path in item.get("tests", [])) or "—"
        lines.append(
            f"| {item['id']} | {item['title']} | `{item['authority']}` | "
            f"`{item['status']}` | {code} | {tests} |"
        )

    for item in data["requirements"]:
        lines.extend(
            [
                "",
                f"## {item['id']} · {item['title']}",
                "",
                f"- 来源：{item['source']}",
                f"- 权威级别：`{item['authority']}`",
                f"- 状态：`{item['status']}`",
                f"- 说明：{item['description']}",
                "- 验收标准：",
                "",
            ]
        )
        lines.extend(f"  - {criterion}" for criterion in item["acceptance_criteria"])
        lines.extend(
            [
                "",
                "- 影响范围：",
                "",
                f"  - 代码：{', '.join(f'`{path}`' for path in item.get('code', [])) or '—'}",
                f"  - 测试：{', '.join(f'`{path}`' for path in item.get('tests', [])) or '—'}",
                f"  - 文档：{', '.join(f'`{path}`' for path in item.get('docs', [])) or '—'}",
            ]
        )

    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="仅检查，不写入文件")
    args = parser.parse_args()

    data = load_registry()
    errors = validate(data)
    expected = render(data)

    if args.check:
        if not OUTPUT.exists() or OUTPUT.read_text(encoding="utf-8") != expected:
            errors.append("docs/requirements.md 已过期，请运行 scripts/project_sync.py")
    else:
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT.write_text(expected, encoding="utf-8")

    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1

    action = "检查通过" if args.check else "已生成 docs/requirements.md"
    print(action)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
