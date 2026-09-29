# 协作开发指南

远程仓库：<https://github.com/Panyuxiang0830/Hackson_fintech>

## 工作流

1. 从最新 `main` 创建分支：`git switch -c feat/REQ-xxx-short-name`。
2. 在 `project/requirements.json` 中定位或新增需求，并填写影响文件。
3. 运行 `python3 scripts/project_sync.py` 生成需求文档。
4. 同一分支内完成代码、测试、文档和 `CHANGELOG.md`。
5. 运行一致性检查和测试后提交 Pull Request。
6. 至少由另一位协作者确认需求验收标准，再合并到 `main`。

## 需求状态

- `planned`：已记录，尚未进入实现；
- `in_progress`：正在实现，不能宣称已交付；
- `implemented`：代码和自动测试已完成；
- `validated`：已通过人工演示或评测；
- `deferred`：明确推迟，并在说明中保留原因。

## 新要求模板

新增要求时至少填写：

- 唯一需求 ID；
- 来源和业务动机；
- 可验证的验收标准；
- 受影响的代码、测试、文档；
- 负责人和当前状态。

不要只在聊天或 Obsidian 中记录项目决定。讨论结论应进入需求台账或 `docs/decisions/`，再由 Git 评审和追踪。

项目内容并不限于代码。需求、设计、测试数据说明、评测方案、演示脚本和架构图也应与对应代码一起提交；只有密钥、个人环境、缓存和运行时产物不应入库。
