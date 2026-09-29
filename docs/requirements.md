# 需求与追踪矩阵

> 此文件由 `project/requirements.json` 自动生成，请勿手工修改。

最后更新：2026-09-29

| ID | 需求 | 状态 | 代码 | 测试 |
|---|---|---|---|---|
| REQ-001 | 自然语言企业知识问答 | `implemented` | `app.py`<br>`src/retrieval.py`<br>`src/answering.py`<br>`src/service.py` | `tests/test_end_to_end.py` |
| REQ-002 | 检索前确定性权限过滤 | `implemented` | `src/policy.py`<br>`src/service.py` | `tests/test_policy.py`<br>`tests/test_no_leakage.py` |
| REQ-003 | 保留来源访问控制语义 | `in_progress` | `src/models.py`<br>`src/policy.py`<br>`data/documents.json`<br>`data/users.json` | `tests/test_policy.py` |
| REQ-004 | 新鲜度与来源状态 | `planned` | `src/models.py`<br>`src/retrieval.py` | — |
| REQ-005 | 权限变更即时生效 | `planned` | `src/policy.py`<br>`src/service.py` | — |
| REQ-006 | 可查询的完整审计记录 | `in_progress` | `src/audit.py`<br>`src/service.py`<br>`app.py` | `tests/test_end_to_end.py` |
| REQ-007 | 防篡改审计链 | `planned` | `src/audit.py` | — |
| REQ-008 | 自然语言审计查询 | `planned` | `src/audit.py`<br>`app.py` | — |
| REQ-009 | LLM 安全边界 | `in_progress` | `src/answering.py`<br>`src/service.py` | `tests/test_no_leakage.py`<br>`tests/test_end_to_end.py` |
| REQ-010 | 比赛交付与现场演示 | `in_progress` | `app.py` | `tests/test_end_to_end.py` |
| REQ-011 | 时序和权威冲突检测 | `deferred` | — | — |
| REQ-012 | 项目内容统一入库与 Git 协作 | `implemented` | `scripts/project_sync.py` | — |

## REQ-001 · 自然语言企业知识问答

- 来源：FinTech track handbook
- 状态：`implemented`
- 说明：员工可以针对统一知识源提出自然语言问题并获得带依据的回答。
- 验收标准：

  - 用户可以输入自由文本问题
  - 回答至少引用一条有权限访问的证据
  - 证据不足时系统明确说明限制

- 影响范围：

  - 代码：`app.py`, `src/retrieval.py`, `src/answering.py`, `src/service.py`
  - 测试：`tests/test_end_to_end.py`
  - 文档：`README.md`, `MVP_v0_开发规格.md`

## REQ-002 · 检索前确定性权限过滤

- 来源：FinTech track handbook
- 状态：`implemented`
- 说明：未经授权的文档不能进入检索候选、模型上下文或返回引用。
- 验收标准：

  - 权限策略在检索和模型调用之前执行
  - 无权限内容不出现在证据、模型输入和审计详情中
  - 相同问题对不同身份返回不同的授权证据

- 影响范围：

  - 代码：`src/policy.py`, `src/service.py`
  - 测试：`tests/test_policy.py`, `tests/test_no_leakage.py`
  - 文档：`MVP_v0_开发规格.md`

## REQ-003 · 保留来源访问控制语义

- 来源：FinTech track handbook
- 状态：`in_progress`
- 说明：统一层必须保留来源系统的部门、角色、项目和敏感级别约束。
- 验收标准：

  - 合成数据包含部门、角色、项目和敏感级别元数据
  - 后续真实连接器不得把来源权限降级为单一公开/私有标记

- 影响范围：

  - 代码：`src/models.py`, `src/policy.py`, `data/documents.json`, `data/users.json`
  - 测试：`tests/test_policy.py`
  - 文档：`MVP_v0_开发规格.md`

## REQ-004 · 新鲜度与来源状态

- 来源：FinTech track handbook
- 状态：`planned`
- 说明：回答必须说明证据更新时间，并在规定窗口内反映来源变化。
- 验收标准：

  - 每条证据展示来源时间和同步时间
  - 过期证据被标记或降权
  - 测试覆盖更新后的状态在目标窗口内可见

- 影响范围：

  - 代码：`src/models.py`, `src/retrieval.py`
  - 测试：—
  - 文档：`MVP_v0_开发规格.md`

## REQ-005 · 权限变更即时生效

- 来源：FinTech track handbook
- 状态：`planned`
- 说明：用户或文档权限变化后，旧权限不能继续读取受保护内容。
- 验收标准：

  - 演示一次用户权限撤销
  - 撤销后重新查询不返回此前可见的敏感证据
  - 权限缓存具有明确失效策略

- 影响范围：

  - 代码：`src/policy.py`, `src/service.py`
  - 测试：—
  - 文档：`MVP_v0_开发规格.md`

## REQ-006 · 可查询的完整审计记录

- 来源：FinTech track handbook
- 状态：`in_progress`
- 说明：每次请求记录身份、决策、证据 ID、时间和请求 ID，并可供后续查询。
- 验收标准：

  - 每次请求写入追加式审计记录
  - 可以按请求 ID、用户和时间范围查询
  - 审计展示不泄漏无权限文档标题或正文

- 影响范围：

  - 代码：`src/audit.py`, `src/service.py`, `app.py`
  - 测试：`tests/test_end_to_end.py`
  - 文档：`MVP_v0_开发规格.md`

## REQ-007 · 防篡改审计链

- 来源：FinTech track handbook
- 状态：`planned`
- 说明：审计事件使用哈希链或等效机制，使删除和修改可以被检测。
- 验收标准：

  - 每条事件包含前序哈希和自身哈希
  - 验证工具能检测事件删除、重排和内容修改
  - 演示一次篡改检测

- 影响范围：

  - 代码：`src/audit.py`
  - 测试：—
  - 文档：`MVP_v0_开发规格.md`

## REQ-008 · 自然语言审计查询

- 来源：FinTech track handbook
- 状态：`planned`
- 说明：授权人员可以询问谁在何时访问了哪些信息以及系统为何允许。
- 验收标准：

  - 支持按用户、请求、时间和证据 ID 查询
  - 审计查询本身受权限控制并被审计
  - 回答包含可核对的事件引用

- 影响范围：

  - 代码：`src/audit.py`, `app.py`
  - 测试：—
  - 文档：`MVP_v0_开发规格.md`

## REQ-009 · LLM 安全边界

- 来源：FinTech track handbook
- 状态：`in_progress`
- 说明：大模型只负责对已授权证据进行总结，不能决定权限或引用未授权内容。
- 验收标准：

  - 权限决定由确定性代码执行
  - 模型返回的引用 ID 必须经过服务端校验
  - 无 API Key 时仍可用确定性模式完成演示

- 影响范围：

  - 代码：`src/answering.py`, `src/service.py`
  - 测试：`tests/test_no_leakage.py`, `tests/test_end_to_end.py`
  - 文档：`README.md`, `MVP_v0_开发规格.md`

## REQ-010 · 比赛交付与现场演示

- 来源：FinTech track handbook
- 状态：`in_progress`
- 说明：交付可运行源代码、现场演示、架构图和信任边界说明。
- 验收标准：

  - 评委可以按 README 启动项目
  - 现场演示身份差异、权限变化和审计能力
  - 提交 GitHub 源码、架构图和 trust-boundary diagram

- 影响范围：

  - 代码：`app.py`
  - 测试：`tests/test_end_to_end.py`
  - 文档：`README.md`, `MVP_v0_开发规格.md`, `FinTech赛题讨论与行动方案.md`

## REQ-011 · 时序和权威冲突检测

- 来源：team discussion
- 状态：`deferred`
- 说明：当 Slack、Jira、文档和发布记录的状态冲突时，结合来源权威、业务时间和因果关系生成警告。
- 验收标准：

  - 区分事件时间、采集时间和生效时间
  - 同一业务实体的矛盾状态触发冲突说明
  - 不把逻辑时钟单独当作业务事实正确性的证明

- 影响范围：

  - 代码：—
  - 测试：—
  - 文档：`FinTech赛题讨论与行动方案.md`, `MVP_v0_开发规格.md`

## REQ-012 · 项目内容统一入库与 Git 协作

- 来源：team discussion
- 状态：`implemented`
- 说明：需求、文档、架构决定、代码和测试统一保存在当前项目文件夹，并通过远程 Git 仓库进行版本管理和多人协作。
- 验收标准：

  - 交付相关内容只能以当前项目文件夹中的版本作为事实依据
  - 需求或功能变更在同一分支中同步修改台账、代码、测试和文档
  - 变更通过 GitHub Pull Request 合并到 main
  - 密钥、虚拟环境和运行时日志不得提交到远程仓库

- 影响范围：

  - 代码：`scripts/project_sync.py`
  - 测试：—
  - 文档：`AGENTS.md`, `CONTRIBUTING.md`, `docs/README.md`, `docs/decisions/ADR-0001-repository-as-source-of-truth.md`
