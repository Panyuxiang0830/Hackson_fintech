# 需求与追踪矩阵

> 此文件由 `project/requirements.json` 自动生成，请勿手工修改。

最后更新：2026-09-29

| ID | 需求 | 权威级别 | 状态 | 代码 | 测试 |
|---|---|---|---|---|---|
| REQ-001 | 跨来源自然语言问答与引用 | `handbook_mandatory` | `in_progress` | `app.py`<br>`src/retrieval.py`<br>`src/answering.py`<br>`src/service.py` | `tests/test_end_to_end.py` |
| REQ-002 | 检索前确定性权限过滤 | `handbook_mandatory` | `implemented` | `src/policy.py`<br>`src/service.py` | `tests/test_policy.py`<br>`tests/test_no_leakage.py` |
| REQ-003 | 保留来源访问控制语义 | `handbook_mandatory` | `in_progress` | `src/models.py`<br>`src/policy.py`<br>`data/documents.json`<br>`data/users.json` | `tests/test_policy.py` |
| REQ-004 | 新鲜度与来源状态 | `handbook_mandatory` | `planned` | `src/models.py`<br>`src/retrieval.py` | — |
| REQ-005 | 权限变更即时生效 | `handbook_mandatory` | `planned` | `src/policy.py`<br>`src/service.py` | — |
| REQ-006 | 可查询的完整审计记录 | `handbook_mandatory` | `in_progress` | `src/audit.py`<br>`src/service.py`<br>`app.py` | `tests/test_end_to_end.py` |
| REQ-007 | 防篡改审计链 | `handbook_mandatory` | `planned` | `src/audit.py` | — |
| REQ-008 | 自然语言审计查询 | `handbook_mandatory` | `planned` | `src/audit.py`<br>`app.py` | — |
| REQ-009 | LLM 安全边界 | `handbook_mandatory` | `in_progress` | `src/answering.py`<br>`src/service.py` | `tests/test_no_leakage.py`<br>`tests/test_end_to_end.py` |
| REQ-010 | 单一案例选择与展示声明 | `handbook_mandatory` | `implemented` | — | — |
| REQ-011 | 时序和权威冲突检测 | `team_decision` | `deferred` | — | — |
| REQ-012 | 项目内容统一入库与 Git 协作 | `team_decision` | `implemented` | `scripts/project_sync.py`<br>`.github/workflows/ci.yml` | `tests/test_project_sync.py` |
| REQ-013 | 交付材料与格式待确认清单 | `pending_confirmation` | `planned` | — | — |

## REQ-001 · 跨来源自然语言问答与引用

- 来源：FinTech track handbook
- 权威级别：`handbook_mandatory`
- 状态：`in_progress`
- 说明：员工可以提出自然语言问题，系统从相关平台组装授权上下文并返回带来源链接的统一回答。
- 验收标准：

  - 用户可以输入自由文本问题
  - 系统可以从 Confluence、Jira、Slack 和 Google Drive 的相关内容组装上下文
  - 回答至少引用一条有权限访问的证据并提供来源链接
  - 证据不足时系统明确说明限制

- 影响范围：

  - 代码：`app.py`, `src/retrieval.py`, `src/answering.py`, `src/service.py`
  - 测试：`tests/test_end_to_end.py`
  - 文档：`README.md`, `docs/product/mvp-v0.md`, `docs/source/handbook-fintech-track.md`

## REQ-002 · 检索前确定性权限过滤

- 来源：FinTech track handbook
- 权威级别：`handbook_mandatory`
- 状态：`implemented`
- 说明：未经授权的文档不能进入检索候选、模型上下文或返回引用。
- 验收标准：

  - 权限策略在检索和模型调用之前执行
  - 无权限内容不出现在证据、模型输入和审计详情中
  - 相同问题对不同身份返回不同的授权证据

- 影响范围：

  - 代码：`src/policy.py`, `src/service.py`
  - 测试：`tests/test_policy.py`, `tests/test_no_leakage.py`
  - 文档：`docs/product/mvp-v0.md`, `docs/source/handbook-fintech-track.md`

## REQ-003 · 保留来源访问控制语义

- 来源：FinTech track handbook
- 权威级别：`handbook_mandatory`
- 状态：`in_progress`
- 说明：统一层必须保留来源系统的部门、角色、项目和敏感级别约束。
- 验收标准：

  - 合成数据包含部门、角色、项目和敏感级别元数据
  - 后续真实连接器不得把来源权限降级为单一公开/私有标记

- 影响范围：

  - 代码：`src/models.py`, `src/policy.py`, `data/documents.json`, `data/users.json`
  - 测试：`tests/test_policy.py`
  - 文档：`docs/product/mvp-v0.md`, `docs/source/handbook-fintech-track.md`

## REQ-004 · 新鲜度与来源状态

- 来源：FinTech track handbook
- 权威级别：`handbook_mandatory`
- 状态：`planned`
- 说明：回答必须说明证据更新时间，并在规定窗口内反映来源变化。
- 验收标准：

  - 每条证据展示来源时间和同步时间
  - 过期证据被标记或降权
  - 测试覆盖更新后的状态在目标窗口内可见

- 影响范围：

  - 代码：`src/models.py`, `src/retrieval.py`
  - 测试：—
  - 文档：`docs/product/mvp-v0.md`, `docs/source/handbook-fintech-track.md`

## REQ-005 · 权限变更即时生效

- 来源：FinTech track handbook
- 权威级别：`handbook_mandatory`
- 状态：`planned`
- 说明：用户或文档权限变化后，旧权限不能继续读取受保护内容。
- 验收标准：

  - 演示一次用户权限撤销
  - 撤销后重新查询不返回此前可见的敏感证据
  - 权限缓存具有明确失效策略

- 影响范围：

  - 代码：`src/policy.py`, `src/service.py`
  - 测试：—
  - 文档：`docs/product/mvp-v0.md`, `docs/source/handbook-fintech-track.md`

## REQ-006 · 可查询的完整审计记录

- 来源：FinTech track handbook
- 权威级别：`handbook_mandatory`
- 状态：`in_progress`
- 说明：每次请求记录身份、查询、逐文档授权决定、检索结果、最终回答和时间，并可供后续查询。
- 验收标准：

  - 每次请求写入追加式审计记录
  - 记录查询、检索文档 ID、最终回答和逐文档允许/拒绝决定
  - 可以按请求 ID、用户和时间范围查询
  - 审计展示不泄漏无权限文档标题或正文

- 影响范围：

  - 代码：`src/audit.py`, `src/service.py`, `app.py`
  - 测试：`tests/test_end_to_end.py`
  - 文档：`docs/product/mvp-v0.md`, `docs/source/handbook-fintech-track.md`

## REQ-007 · 防篡改审计链

- 来源：FinTech track handbook
- 权威级别：`handbook_mandatory`
- 状态：`planned`
- 说明：审计事件使用哈希链或等效机制，使删除和修改可以被检测。
- 验收标准：

  - 每条事件包含前序哈希和自身哈希
  - 验证工具能检测事件删除、重排和内容修改
  - 演示一次篡改检测

- 影响范围：

  - 代码：`src/audit.py`
  - 测试：—
  - 文档：`docs/product/mvp-v0.md`, `docs/source/handbook-fintech-track.md`

## REQ-008 · 自然语言审计查询

- 来源：FinTech track handbook
- 权威级别：`handbook_mandatory`
- 状态：`planned`
- 说明：授权人员可以询问谁在何时访问了哪些信息以及系统为何允许。
- 验收标准：

  - 支持按用户、请求、时间和证据 ID 查询
  - 审计查询本身受权限控制并被审计
  - 回答包含可核对的事件引用

- 影响范围：

  - 代码：`src/audit.py`, `app.py`
  - 测试：—
  - 文档：`docs/product/mvp-v0.md`, `docs/source/handbook-fintech-track.md`

## REQ-009 · LLM 安全边界

- 来源：FinTech track handbook
- 权威级别：`handbook_mandatory`
- 状态：`in_progress`
- 说明：大模型只负责对已授权证据进行总结，不能决定权限或引用未授权内容。
- 验收标准：

  - 权限决定由确定性代码执行
  - 模型返回的引用 ID 必须经过服务端校验
  - 无 API Key 时仍可用确定性模式完成演示

- 影响范围：

  - 代码：`src/answering.py`, `src/service.py`
  - 测试：`tests/test_no_leakage.py`, `tests/test_end_to_end.py`
  - 文档：`README.md`, `docs/product/mvp-v0.md`, `docs/source/handbook-fintech-track.md`

## REQ-010 · 单一案例选择与展示声明

- 来源：FinTech track handbook
- 权威级别：`handbook_mandatory`
- 状态：`implemented`
- 说明：团队只选择一个案例，并在展示开头明确说明选择 Internal Brain 案例。
- 验收标准：

  - 项目只实现 Internal Brain 案例，不混入其他赛题
  - Presentation 开头明确写出所选案例名称

- 影响范围：

  - 代码：—
  - 测试：—
  - 文档：`README.md`, `docs/source/handbook-fintech-track.md`

## REQ-011 · 时序和权威冲突检测

- 来源：team discussion
- 权威级别：`team_decision`
- 状态：`deferred`
- 说明：当 Slack、Jira、文档和发布记录的状态冲突时，结合来源权威、业务时间和因果关系生成警告。
- 验收标准：

  - 区分事件时间、采集时间和生效时间
  - 同一业务实体的矛盾状态触发冲突说明
  - 不把逻辑时钟单独当作业务事实正确性的证明

- 影响范围：

  - 代码：—
  - 测试：—
  - 文档：`docs/product/roadmap.md`, `docs/product/mvp-v0.md`

## REQ-012 · 项目内容统一入库与 Git 协作

- 来源：team discussion
- 权威级别：`team_decision`
- 状态：`implemented`
- 说明：需求、文档、架构决定、代码和测试统一保存在当前项目文件夹，并通过远程 Git 仓库进行版本管理和多人协作。
- 验收标准：

  - 交付相关内容只能以当前项目文件夹中的版本作为事实依据
  - 需求或功能变更在同一分支中同步修改台账、代码、测试和文档
  - 变更通过 GitHub Pull Request 合并到 main
  - 密钥、虚拟环境和运行时日志不得提交到远程仓库

- 影响范围：

  - 代码：`scripts/project_sync.py`, `.github/workflows/ci.yml`
  - 测试：`tests/test_project_sync.py`
  - 文档：`AGENTS.md`, `CONTRIBUTING.md`, `.github/PULL_REQUEST_TEMPLATE.md`, `docs/README.md`, `docs/decisions/ADR-0001-repository-as-source-of-truth.md`

## REQ-013 · 交付材料与格式待确认清单

- 来源：handbook wording and submission form pending confirmation
- 权威级别：`pending_confirmation`
- 状态：`planned`
- 说明：公开仓库、Demo 视频、部署链接、Pitch Deck、腾讯产品、正式报告及合规格式不得在核实前写成官方硬性要求。
- 验收标准：

  - 提交前逐项核对比赛邮件中的 Handbook 和登录后的提交表
  - 把已确认字段、格式和截止时间更新到官方来源文档
  - 团队可以提前准备代码、Demo 和架构材料，但必须标记为团队交付策略而非官方硬性要求

- 影响范围：

  - 代码：—
  - 测试：—
  - 文档：`docs/source/submission-open-questions.md`, `docs/source/handbook-fintech-track.md`
