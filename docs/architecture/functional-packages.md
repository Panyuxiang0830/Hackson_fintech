# 功能分包重构（REQ-012）

本轮是目录与测试组织重构，不是新的权限算法或数据库迁移。工作基线为 main `bf57bebf` 加四来源/MCP 分支 `f590ba83`；保留现有前端与服务。

## 2026-10-14：误合并后的分支恢复

PR #17 曾被误合并（`11a805c7`），随后 main 使用 `952881f9` 撤回。原工作分支及 `2f9a405c` 代码没有丢失，但已合并的 PR 不能直接重开。

恢复时在原 `codex/REQ-012-functional-refactor` 分支纳入 main 的合并/撤回历史，仅在工作分支撤销该撤回，恢复原改动以重新生成可审查差异。恢复后的代码树在补充说明之前与 `2f9a405c` 完全一致；未增加业务功能或覆盖其他 main 改动。重新开草稿 PR 待人工确认，不改动远端 main，也不部署服务器或改写 Git 历史。

## 当前布局

```text
contextledger/
  application/  统一请求编排
  access/       身份、来源 ACL、撤权与工具凭据
  ingestion/    适配、解析、清洗、分块
  storage/      原文、版本、发布锁与更新任务
  retrieval/    FTS、向量与过滤
  answering/    回答、受限模型阶段与证据 DTO
  radar/        查询时业务演变工具
  audit/        审计记录、哈希与查询解析
  interfaces/   Web、MCP、CLI 与页面资源
  evaluation/   固定样例、排序、回放与延迟测量
tests/          与功能包对应的小样本测试
fixtures/       固定业务回放资料（不是旧 JSON 运行数据）
scripts/        命令入口及独立运维/项目工具
```

`data/documents.json`、`data/users.json`、`app.py` 和只服务旧 JSON 演示的加载器/策略/服务已删除。未跟踪大数据、服务器原文、向量、身份、审计状态不动；固定的 chat/radar 业务 fixture 保留。

## 模块职责与主链路

| 包 | 主要实现 | 职责 |
|---|---|---|
| application | service.py | 统一编排搜索、回答、原文和审计的权限/版本门闩 |
| access | identity_store.py、acl.py、tool_access.py | 持久身份、来源 ACL 与本地限制、撤权和个人工具凭据 |
| ingestion | connectors.py、source_adapters.py、processors.py、pipeline.py | 离线与真实来源适配、解析和分块；source_sync.py 为受控同步入口 |
| storage | store.py、document_updates.py、index_lock.py、models.py | SQLite 原文/历史、更新任务和安全发布；来源与规范记录 DTO |
| retrieval | search.py、vectors.py、filtered_index.py | Part A FTS/RaBitQ，统一版过滤 Qdrant 与事实库复核 |
| answering | service.py、models.py、workflows.py | Prompt/回答/引用范围检查、回答 DTO、共享有界模型阶段 |
| radar | tool.py、protocol.py、data.py、store.py、resolution.py | 按问题补查业务实体、历史/关系候选与出处 |
| audit | store.py、chain.py、query.py | 事务审计、共享哈希/校验类型和确定性时间/查询解析 |
| interfaces | web.py、tool_api.py、mcp_server.py、integration.py、part_a.py | Web/MCP/API/CLI；templates/static 随 Web 包保存 |
| evaluation | retrieval.py、freshness.py、chat.py、chat_latency.py 等 | 评分、受控回放、排序实验与隔离延迟测量；不自动改变在线排序 |

Web 和私有 Tool API 复用 application；它按当前 access 生成检索范围，retrieval 返回事实库核对后的证据，再交 answering/Radar。交付前复查当前权限和发布代次，audit 记录实际请求。ingestion 的更新经 storage 的队列和发布锁进入同一事实库/索引。

回答 User/Document/Evidence DTO 与来源/规范存储 DTO 分开保存，没有因为名字近似而合并字段语义。模型默认、权限策略、来源 ACL、数据库/索引结构和接口响应字段不变。目录深度变化由 paths.PROJECT_ROOT 统一处理，评测代码指纹使用真实新路径。

## scripts 与兼容入口

scripts 中排序/重排/聊天评分/回放/延迟测量已迁入 evaluation；原脚本仅导入同一 main，不复制实现。project_sync、预览准备、配置同步、向量依赖安装、运维核对和浏览器外部走查仍是独立操作工具，不强制塞进业务请求链。

下列旧公开命令保留薄兼容入口：

    python -m contextledger --help
    python -m contextledger.integration --help
    python -m contextledger.source_sync --help
    python -m contextledger.tool_api --help
    python -m contextledger.freshness_eval --help
    python -m contextledger.mcp_server
    python scripts/mcp_private_launcher.py --credentials /private/employee.json

新业务导入使用功能包路径；旧平铺 Python 内部导入路径不再作为 API 保留。对外 CLI 参数、Web/API 路由和 stdio MCP 工具契约保留。调用方如直接导入旧内部模块，应按表迁移；已部署的固定 release 不会被本地重构改写。

## 回归与删除范围

- 合并工作分支基线：325 项 unittest + 8 项独立 Part A pytest，通过。
- 删除5个旧 JSON/KnowledgeService 专用测试文件，共13个用例；其对应旧服务随旧数据退出。共享回答测试全部保留，使用两个本地文档和一个用户；审计4个篡改测试改测实际 SQLite AuditStore，解析器保留时间覆盖并新增3个 DTO 用例。
- 新增11项回归：3个解析器用例、7个目录/依赖/CLI/资源/fixture 作用域用例和1个真实 SDK stdio 握手。握手不访问上游平台或生成模型。
- 当前 unittest 323项；pytest 331项全部通过（含上述323项和8项 Part A，不相加），不跳过失败测试。Part A 的 autouse tokenizer 仅作用于 tests/ingestion/part_a。
- CLI在仓库外工作目录启动、前端资源、JS语法、需求同步和差异检查覆盖迁移风险。审计测评不再读旧 JSON，改用一个文档的统一服务；旧报告 mvp_audit 键为兼容保留，scope 明确当前统一服务与本地检查点边界。
- 附加检查：26个 CLI 帮助入口通过；15个关键业务模块与重构基线作 AST 比较，除导入路径外逻辑一致（含模型 Prompt、ACL、过滤索引、撤权门闩、更新任务和工具 API）。页面及 JS/CSS/SVG 在临时统一服务中实际返回 HTTP 200。

验证使用临时数据库/原生内存 Qdrant 和模拟模型 transport；没有重建或清空服务器数据、付费调用生成模型或执行真实来源同步。本轮回归不能替代真实模型质量、真实企业权限、生产新鲜度或人工 Demo 验收。改动仅在工作分支，须另行审阅后才能合并 main。
