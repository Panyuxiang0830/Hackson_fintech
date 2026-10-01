# 需求与追踪矩阵

> 此文件由 `project/requirements.json` 自动生成，请勿手工修改。

最后更新：2026-10-02

| ID | 需求 | 权威级别 | 状态 | 代码 | 测试 |
|---|---|---|---|---|---|
| REQ-001 | 跨来源自然语言问答与引用 | `handbook_mandatory` | `in_progress` | `app.py`<br>`src/retrieval.py`<br>`src/answering.py`<br>`src/service.py` | `tests/test_end_to_end.py` |
| REQ-002 | 检索前确定性权限过滤 | `handbook_mandatory` | `in_progress` | `src/policy.py`<br>`src/service.py` | `tests/test_policy.py`<br>`tests/test_no_leakage.py` |
| REQ-003 | 保留来源访问控制语义 | `handbook_mandatory` | `in_progress` | `src/models.py`<br>`src/policy.py`<br>`data/documents.json`<br>`data/users.json` | `tests/test_policy.py` |
| REQ-004 | 新鲜度与来源状态 | `handbook_mandatory` | `in_progress` | `src/models.py`<br>`src/freshness.py`<br>`src/retrieval.py`<br>`src/service.py`<br>`app.py`<br>`data/documents.json` | `tests/test_permission_freshness.py` |
| REQ-005 | 权限变更即时生效 | `handbook_mandatory` | `implemented` | `src/identity.py`<br>`src/policy.py`<br>`src/service.py`<br>`app.py` | `tests/test_permission_freshness.py` |
| REQ-006 | 可查询的完整审计记录 | `handbook_mandatory` | `implemented` | `src/audit.py`<br>`src/service.py`<br>`app.py` | `tests/test_end_to_end.py`<br>`tests/test_audit_query.py` |
| REQ-007 | 防篡改审计链 | `handbook_mandatory` | `implemented` | `src/audit.py`<br>`scripts/demo_audit_tamper.py` | `tests/test_audit.py` |
| REQ-008 | 自然语言审计查询 | `handbook_mandatory` | `implemented` | `src/audit.py`<br>`src/audit_query.py`<br>`src/service.py`<br>`app.py` | `tests/test_audit_query.py` |
| REQ-009 | LLM 安全边界 | `handbook_mandatory` | `validated` | `src/answering.py`<br>`src/service.py`<br>`app.py` | `tests/test_answering.py`<br>`tests/test_no_leakage.py`<br>`tests/test_end_to_end.py` |
| REQ-010 | 单一案例选择与展示声明 | `handbook_mandatory` | `implemented` | — | — |
| REQ-011 | 时序和权威冲突检测 | `team_decision` | `deferred` | — | — |
| REQ-012 | 项目内容统一入库与 Git 协作 | `team_decision` | `implemented` | `scripts/project_sync.py`<br>`.github/workflows/ci.yml` | `tests/test_project_sync.py` |
| REQ-013 | 交付材料与格式待确认清单 | `pending_confirmation` | `planned` | — | — |
| REQ-014 | 异构来源摄取、清洗与高价值信息筛选 | `team_decision` | `planned` | — | — |
| REQ-015 | 统一分类、混合索引与身份感知查询路由 | `team_decision` | `planned` | — | — |

## REQ-001 · 跨来源自然语言问答与引用

- 来源：FinTech track handbook
- 权威级别：`handbook_mandatory`
- 状态：`in_progress`
- 说明：员工可以提出自然语言问题，系统从相关平台组装授权上下文并返回带来源链接的统一回答。
- 验收标准：

  - 用户可以输入自由文本问题
  - 系统可以从 Confluence、Jira、Slack 和 Google Drive 的相关内容组装上下文
  - 只把已授权且未过期的 Top-K 证据交给回答模型
  - 回答能够解释跨来源证据之间的关系并使用与证据面板一致的数字引用
  - 回答至少引用一条有权限访问的证据并提供来源链接
  - 证据不足时系统明确说明限制

- 影响范围：

  - 代码：`app.py`, `src/retrieval.py`, `src/answering.py`, `src/service.py`
  - 测试：`tests/test_end_to_end.py`
  - 文档：`README.md`, `docs/product/mvp-v0.md`, `docs/source/handbook-fintech-track.md`

## REQ-002 · 检索前确定性权限过滤

- 来源：FinTech track handbook
- 权威级别：`handbook_mandatory`
- 状态：`in_progress`
- 说明：未经授权的文档不能进入检索候选、模型上下文或返回引用；规模化检索时权限条件必须下推到索引层。
- 验收标准：

  - 权限策略在检索和模型调用之前执行
  - 无权限内容不出现在证据、模型输入和审计详情中
  - 相同问题对不同身份返回不同的授权证据
  - 租户、部门、角色、项目和密级被转换为索引层过滤条件
  - 服务端对索引返回的候选证据再次执行权限校验

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
- 状态：`in_progress`
- 说明：回答必须说明证据更新时间并在规定窗口内反映来源变化，同时保留可回退的历史版本。
- 验收标准：

  - 每条证据展示来源时间和同步时间
  - 已知过期证据在检索前被排除，延迟同步被明确标记
  - 测试覆盖更新后的状态在目标窗口内可见
  - 旧版本被保留但不会进入当前检索视图，删除、撤回和回滚使用显式状态表达
  - 系统可以通过 active version 指针或等效机制安全回退，并记录回退审计事件

- 影响范围：

  - 代码：`src/models.py`, `src/freshness.py`, `src/retrieval.py`, `src/service.py`, `app.py`, `data/documents.json`
  - 测试：`tests/test_permission_freshness.py`
  - 文档：`docs/product/mvp-v0.md`, `docs/source/handbook-fintech-track.md`

## REQ-005 · 权限变更即时生效

- 来源：FinTech track handbook
- 权威级别：`handbook_mandatory`
- 状态：`implemented`
- 说明：用户或文档权限变化后，旧权限不能继续读取受保护内容。
- 验收标准：

  - 演示一次用户权限撤销
  - 撤销后重新查询不返回此前可见的敏感证据
  - 每次请求从当前 IdentityService 重新解析身份，不沿用调用方的旧用户对象

- 影响范围：

  - 代码：`src/identity.py`, `src/policy.py`, `src/service.py`, `app.py`
  - 测试：`tests/test_permission_freshness.py`
  - 文档：`docs/product/mvp-v0.md`, `docs/source/handbook-fintech-track.md`

## REQ-006 · 可查询的完整审计记录

- 来源：FinTech track handbook
- 权威级别：`handbook_mandatory`
- 状态：`implemented`
- 说明：每次请求记录身份、查询、逐文档授权决定、检索结果、最终回答和时间，并可供后续查询。
- 验收标准：

  - 每次请求写入追加式审计记录
  - 记录查询、检索文档 ID、最终回答和逐文档允许/拒绝决定
  - 可以按请求 ID、用户和时间范围查询
  - 审计展示不泄漏无权限文档标题或正文

- 影响范围：

  - 代码：`src/audit.py`, `src/service.py`, `app.py`
  - 测试：`tests/test_end_to_end.py`, `tests/test_audit_query.py`
  - 文档：`docs/product/mvp-v0.md`, `docs/source/handbook-fintech-track.md`

## REQ-007 · 防篡改审计链

- 来源：FinTech track handbook
- 权威级别：`handbook_mandatory`
- 状态：`implemented`
- 说明：审计事件使用哈希链或等效机制，使删除和修改可以被检测。
- 验收标准：

  - 每条事件包含前序哈希和自身哈希
  - 验证工具能检测事件删除、重排和内容修改
  - 演示一次篡改检测

- 影响范围：

  - 代码：`src/audit.py`, `scripts/demo_audit_tamper.py`
  - 测试：`tests/test_audit.py`
  - 文档：`docs/product/mvp-v0.md`, `docs/source/handbook-fintech-track.md`

## REQ-008 · 自然语言审计查询

- 来源：FinTech track handbook
- 权威级别：`handbook_mandatory`
- 状态：`implemented`
- 说明：授权人员可以询问谁在何时访问了哪些信息以及系统为何允许。
- 验收标准：

  - 支持按用户、请求、时间和证据 ID 查询
  - 审计查询本身受权限控制并被审计
  - 回答包含可核对的事件引用

- 影响范围：

  - 代码：`src/audit.py`, `src/audit_query.py`, `src/service.py`, `app.py`
  - 测试：`tests/test_audit_query.py`
  - 文档：`docs/product/mvp-v0.md`, `docs/source/handbook-fintech-track.md`

## REQ-009 · LLM 安全边界

- 来源：FinTech track handbook
- 权威级别：`handbook_mandatory`
- 状态：`validated`
- 说明：大模型只负责对已授权证据进行总结，不能决定权限或引用未授权内容。
- 验收标准：

  - 权限决定由确定性代码执行
  - 通过同一组跨来源回答、拒答、结构化输出、延迟和 Token 用量样例比较候选模型并记录选型依据
  - 模型返回的引用 ID 必须经过服务端校验
  - 模型只接收已授权且未过期的 Top-K 证据，并能生成跨 Jira、Slack、Confluence 和 Google Drive 的综合回答
  - API 超时、配置缺失、输出无法解析或引用非法时自动退回确定性回答
  - 无 API Key 时仍可用确定性模式完成演示

- 影响范围：

  - 代码：`src/answering.py`, `src/service.py`, `app.py`
  - 测试：`tests/test_answering.py`, `tests/test_no_leakage.py`, `tests/test_end_to_end.py`
  - 文档：`README.md`, `docs/product/mvp-v0.md`, `docs/evaluation/model-selection.md`, `docs/source/handbook-fintech-track.md`

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

## REQ-014 · 异构来源摄取、清洗与高价值信息筛选

- 来源：team discussion marked 【新需求】 on 2026-10-02
- 权威级别：`team_decision`
- 状态：`planned`
- 说明：Confluence、Jira、Slack 和 Google Drive 使用来源感知的处理链路，优先以确定性规则过滤低价值内容，只把可追溯的高价值信息送入索引和模型。
- 验收标准：

  - 四类来源分别定义解析和清洗策略，不用同一个文本规则机械处理所有内容
  - Slack 过滤机器人通知、寒暄、表情和重复引用，并按线程、时间窗口、项目或主题聚合
  - 代码、结构化工单字段、长文档和聊天记录使用适合其结构的分块与元数据提取方式
  - 原始数据与清洗后的派生内容分开保存，任何过滤结果都保留来源链接和过滤原因以便恢复
  - 优先使用字段、规则、解析器和轻量分类，只有歧义内容才调用大模型
  - 用保留率、关键事实召回率和节省的模型 Token 衡量筛选效果

- 影响范围：

  - 代码：—
  - 测试：—
  - 文档：`docs/product/roadmap.md`

## REQ-015 · 统一分类、混合索引与身份感知查询路由

- 来源：team discussion marked 【新需求】 on 2026-10-02
- 权威级别：`team_decision`
- 状态：`planned`
- 说明：通过统一的部门、项目、业务实体、内容类型、时间、权威性和权限元数据组织异构信息，并根据问题与提问者身份路由到合适的结构化或向量检索范围。
- 验收标准：

  - 统一分类字段至少覆盖来源、内容类型、部门、项目、业务实体、时间、权威等级、安全密级和当前状态
  - 明确字段保存在结构化索引，语义内容按需进入向量索引，内容未变化时不重复生成向量
  - Query 路由提取意图、实体、时间和来源范围，并结合当前身份生成检索过滤条件
  - 先执行元数据和关键词过滤，再进行向量召回与排序，最后只把少量 Top-K 证据交给模型
  - 物理索引默认共享、通过 collection 或 namespace 和 metadata filter 逻辑隔离；只有规模或安全边界需要时才拆分

- 影响范围：

  - 代码：—
  - 测试：—
  - 文档：`docs/product/roadmap.md`
