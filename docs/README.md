# 项目知识入口

这里是 ContextLedger 的项目地图。**Git 仓库是唯一事实源**；Obsidian 可以打开这些 Markdown 文件进行阅读和链接，但不保存另一份副本。

- 本地项目目录：`/Users/panyuxiang/Desktop/hackson`
- 远程协作仓库：<https://github.com/Panyuxiang0830/Hackson_fintech>

需求、讨论结论、设计、代码、测试、演示素材和提交说明，只要会影响项目交付，都应保存在这个目录并进入 Git。聊天和 Obsidian 中尚未落入仓库的内容只能算草稿。

## 信息权威顺序

出现冲突时按以下顺序处理：

1. `docs/source/` 中已经保存并标注版本的比赛官方材料；
2. `project/requirements.json` 中带有权威级别的需求和验收标准；
3. `docs/decisions/` 中已接受的架构决定；
4. 自动测试所证明的当前行为；
5. 其他设计草稿、会议记录和聊天内容。

冲突不能靠“选较新的那份文档”静默解决。需要更新需求或新增 ADR，保留决策理由。

## 文档地图

- `project/requirements.json`：唯一的需求台账，供人和工具修改；
- `docs/requirements.md`：由台账自动生成的只读视图；
- `docs/source/`：Handbook 基线和仍待官方确认的提交字段；
- `docs/product/mvp-v0.md`：当前 MVP 的详细范围和团队内部验收说明；
- `docs/product/roadmap.md`：依据需求差距整理的实现顺序；
- `docs/decisions/`：重要且难以逆转的架构决定；
- `CHANGELOG.md`：跨版本的行为变化；
- `CONTRIBUTING.md`：分支、提交和评审流程；
- `AGENTS.md`：代码 Agent 必须遵循的项目规则。

## 需求同步

修改 `project/requirements.json` 后运行：

```bash
python3 scripts/project_sync.py
python3 scripts/project_sync.py --check
```

第一条命令重新生成 `docs/requirements.md`；第二条命令用于本地或 CI，发现生成文档过期、重复需求 ID、非法状态、非法权威级别或不存在的影响文件时会失败。

## 权威级别

- `handbook_mandatory`：Handbook 有明确要求或必须演示的场景；
- `handbook_guidance`：Handbook 提供的建议，不自动等于硬性提交标准；
- `pending_confirmation`：必须到邮件、最新版 Handbook 或提交表继续核实；
- `team_decision`：团队为了产品质量和协作主动采用的要求。
