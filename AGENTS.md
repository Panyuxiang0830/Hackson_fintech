# ContextLedger 协作约定

本文件适用于人类协作者和代码 Agent。项目的唯一事实源是当前 Git 仓库，不要在 Obsidian、聊天记录或在线文档中维护第二份项目状态。

远程仓库为 `https://github.com/Panyuxiang0830/Hackson_fintech`。需求、设计和演示材料与代码享有相同的版本管理要求。

## 开始修改前

1. 阅读 `docs/README.md`、`project/requirements.json` 和相关 ADR。
2. 检查需求的 `authority`；不得把 `pending_confirmation` 或 `handbook_guidance` 改写为官方硬性要求。
3. 为变更找到已有的 `REQ-xxx`；如果不存在，先新增需求 ID。
4. 在需求台账中记录受影响的代码、测试和文档，再开始实现。

## 新需求自动入账

- 当用户消息中的一行以 `【新需求】` 开头时，立即把内容整理进 `project/requirements.json`，不依赖聊天记录保存状态；
- 先与现有需求的目标和验收标准去重：相同目标扩充原有 REQ，独立目标才分配新的连续 `REQ-xxx`；
- 用户提出但官方材料未规定的内容默认标记为 `team_decision`，不得提升为 `handbook_mandatory`；
- 若用户只提出需求而未要求立即实现，状态使用 `planned`，影响文件可以在设计确定后继续补充；
- 更新台账后运行同步脚本生成 `docs/requirements.md`，不要直接维护生成文件。

## 一次完整变更必须包含

- 需求台账的状态或影响范围更新；
- 实现代码；
- 对应测试；
- 用户可见行为或架构变化所需的文档更新；
- `CHANGELOG.md` 中的一条说明。

不要直接编辑 `docs/requirements.md`，它由 `project/requirements.json` 自动生成。

## 工程难题固定清单

- 用户问“工程难题”“工程难点”或要求回顾难点时，先读取 `docs/product/engineering-challenges.md`，围绕 EC-001 至 EC-010 回答，不用临时想到的其他事项替换清单。
- 可以说明清单内事项的进度和剩余问题；新增专题先明确提出并经用户确认后再更新清单及需求台账。
- 已确认当前先完成 REQ-017 集成；所有改动留在工作分支，未经用户验收明确同意，不合并到 main。

## 完成前检查

```bash
.venv/bin/python scripts/project_sync.py --check
.venv/bin/python -m unittest discover -s tests -v
```

如果没有 `.venv`，以上命令中的 `.venv/bin/python` 可替换为 `python3`。

## Git 约定

- `main` 必须始终可运行、可演示；
- 每项工作使用短生命周期分支，例如 `feat/REQ-011-slack-connector`；
- 提交信息使用 `feat:`、`fix:`、`test:`、`docs:`、`refactor:` 前缀；
- 合并前使用 Pull Request，并逐项完成模板检查；
- 不提交 `.env`、API Key、`.venv`、运行时审计日志或真实公司数据。
