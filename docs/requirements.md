# 需求与追踪矩阵

> 此文件由 `project/requirements.json` 自动生成，请勿手工修改。

最后更新：2026-10-06

| ID | 需求 | 权威级别 | 状态 | 代码 | 测试 |
|---|---|---|---|---|---|
| REQ-001 | 跨来源自然语言问答与引用 | `handbook_mandatory` | `in_progress` | `app.py`<br>`src/retrieval.py`<br>`src/answering.py`<br>`src/service.py`<br>`contextledger/unified_service.py`<br>`contextledger/web.py` | `tests/test_end_to_end.py`<br>`tests/test_integration.py` |
| REQ-002 | 检索前确定性权限过滤 | `handbook_mandatory` | `in_progress` | `src/policy.py`<br>`src/service.py`<br>`contextledger/filtered_index.py`<br>`contextledger/unified_service.py` | `tests/test_policy.py`<br>`tests/test_no_leakage.py`<br>`tests/test_integration.py` |
| REQ-003 | 保留来源访问控制语义 | `handbook_mandatory` | `in_progress` | `src/models.py`<br>`src/policy.py`<br>`data/documents.json`<br>`data/users.json`<br>`contextledger/identity_store.py`<br>`contextledger/filtered_index.py`<br>`contextledger/source_permissions.py` | `tests/test_policy.py`<br>`tests/test_integration.py` |
| REQ-004 | 新鲜度与来源状态 | `handbook_mandatory` | `in_progress` | `src/models.py`<br>`src/freshness.py`<br>`src/retrieval.py`<br>`src/service.py`<br>`app.py`<br>`data/documents.json`<br>`contextledger/filtered_index.py` | `tests/test_permission_freshness.py`<br>`tests/test_integration.py` |
| REQ-005 | 权限变更即时生效 | `handbook_mandatory` | `implemented` | `src/identity.py`<br>`src/policy.py`<br>`src/service.py`<br>`app.py`<br>`contextledger/identity_store.py`<br>`contextledger/web.py`<br>`contextledger/unified_service.py`<br>`contextledger/static/unified.js` | `tests/test_permission_freshness.py`<br>`tests/test_integration.py` |
| REQ-006 | 可查询的完整审计记录 | `handbook_mandatory` | `in_progress` | `src/audit.py`<br>`src/service.py`<br>`app.py`<br>`contextledger/audit_store.py`<br>`contextledger/unified_service.py` | `tests/test_end_to_end.py`<br>`tests/test_audit_query.py`<br>`tests/test_integration.py` |
| REQ-007 | 防篡改审计链 | `handbook_mandatory` | `implemented` | `src/audit.py`<br>`scripts/demo_audit_tamper.py`<br>`contextledger/audit_store.py` | `tests/test_audit.py`<br>`tests/test_integration.py` |
| REQ-008 | 自然语言审计查询 | `handbook_mandatory` | `implemented` | `src/audit.py`<br>`src/audit_query.py`<br>`src/service.py`<br>`app.py`<br>`contextledger/unified_service.py`<br>`contextledger/web.py` | `tests/test_audit_query.py`<br>`tests/test_integration.py` |
| REQ-009 | LLM 安全边界 | `handbook_mandatory` | `in_progress` | `src/answering.py`<br>`src/service.py`<br>`app.py`<br>`contextledger/unified_service.py` | `tests/test_answering.py`<br>`tests/test_no_leakage.py`<br>`tests/test_end_to_end.py`<br>`tests/test_integration.py` |
| REQ-010 | 单一案例选择与展示声明 | `handbook_mandatory` | `implemented` | — | — |
| REQ-011 | 时序和权威冲突检测 | `team_decision` | `deferred` | — | — |
| REQ-012 | 项目内容统一入库与 Git 协作 | `team_decision` | `implemented` | `scripts/project_sync.py`<br>`.github/workflows/ci.yml` | `tests/test_project_sync.py` |
| REQ-013 | 交付材料与格式待确认清单 | `pending_confirmation` | `planned` | — | — |
| REQ-014 | 异构来源摄取、清洗与高价值信息筛选 | `team_decision` | `planned` | — | — |
| REQ-015 | 统一分类、混合索引与身份感知查询路由 | `team_decision` | `in_progress` | `contextledger/filtered_index.py` | `tests/test_integration.py` |
| REQ-016 | 可信调用身份与持久化身份权限库 | `team_decision` | `in_progress` | `contextledger/identity_store.py`<br>`contextledger/demo_identity.py`<br>`contextledger/web.py`<br>`contextledger/integration.py`<br>`contextledger/templates/unified.html`<br>`contextledger/static/unified.js`<br>`scripts/sync_preview_config.py`<br>`.env.integration.example` | `tests/test_integration.py`<br>`tests/test_demo_identity.py`<br>`tests/test_preview_config.py`<br>`tests/test_oidc.py` |
| REQ-017 | Part A 与安全问答服务统一集成 | `team_decision` | `in_progress` | `contextledger/unified_service.py`<br>`contextledger/web.py`<br>`contextledger/identity_store.py`<br>`contextledger/demo_identity.py`<br>`contextledger/filtered_index.py`<br>`contextledger/audit_store.py`<br>`contextledger/source_permissions.py`<br>`contextledger/templates/unified.html`<br>`contextledger/static/unified.js`<br>`contextledger/static/unified.css`<br>`contextledger/integration.py`<br>`contextledger/demo_app.py`<br>`contextledger/pipeline.py`<br>`scripts/integration.sh`<br>`scripts/prepare_integration_preview.py`<br>`scripts/verify_unified_snapshot.py`<br>`scripts/sync_preview_config.py`<br>`requirements-integration.txt` | `tests/test_integration.py`<br>`tests/test_demo_identity.py`<br>`tests/test_preview_config.py`<br>`tests/test_oidc.py` |
| REQ-018 | 端到端质量、安全与性能评测 | `team_decision` | `planned` | — | — |
| REQ-019 | 回答 Prompt 的管理与质量评测 | `team_decision` | `planned` | `src/answering.py`<br>`contextledger/unified_service.py` | `tests/test_answering.py` |
| REQ-020 | 面向上游 Agent 的权限感知工具接口 | `team_decision` | `deferred` | `contextledger/unified_service.py`<br>`contextledger/identity_store.py`<br>`contextledger/filtered_index.py`<br>`contextledger/web.py` | `tests/test_integration.py` |

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

  - 代码：`app.py`, `src/retrieval.py`, `src/answering.py`, `src/service.py`, `contextledger/unified_service.py`, `contextledger/web.py`
  - 测试：`tests/test_end_to_end.py`, `tests/test_integration.py`
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

  - 代码：`src/policy.py`, `src/service.py`, `contextledger/filtered_index.py`, `contextledger/unified_service.py`
  - 测试：`tests/test_policy.py`, `tests/test_no_leakage.py`, `tests/test_integration.py`
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

  - 代码：`src/models.py`, `src/policy.py`, `data/documents.json`, `data/users.json`, `contextledger/identity_store.py`, `contextledger/filtered_index.py`, `contextledger/source_permissions.py`
  - 测试：`tests/test_policy.py`, `tests/test_integration.py`
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

  - 代码：`src/models.py`, `src/freshness.py`, `src/retrieval.py`, `src/service.py`, `app.py`, `data/documents.json`, `contextledger/filtered_index.py`
  - 测试：`tests/test_permission_freshness.py`, `tests/test_integration.py`
  - 文档：`docs/product/mvp-v0.md`, `docs/source/handbook-fintech-track.md`, `docs/architecture/index-and-freshness.md`

## REQ-005 · 权限变更即时生效

- 来源：FinTech track handbook
- 权威级别：`handbook_mandatory`
- 状态：`implemented`
- 说明：用户或文档权限变化后，旧权限不能继续读取受保护内容。
- 验收标准：

  - 演示一次用户权限撤销
  - 撤销后重新查询不返回此前可见的敏感证据
  - 每次请求从当前 IdentityService 重新解析身份，不沿用调用方的旧用户对象
  - 集成版系统内撤权持久化生效，搜索、原文、模型输入和回答交付均校验当前权限；旧缓存或历史回答不得绕过校验

- 影响范围：

  - 代码：`src/identity.py`, `src/policy.py`, `src/service.py`, `app.py`, `contextledger/identity_store.py`, `contextledger/web.py`, `contextledger/unified_service.py`, `contextledger/static/unified.js`
  - 测试：`tests/test_permission_freshness.py`, `tests/test_integration.py`
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
  - 集成版明确记录服务端策略版本、实际返回候选的授权决定与证据版本；不把候选审计宣称为全库逐文档审计，长期合规与诊断日志范围由 EC-009 后续验收

- 影响范围：

  - 代码：`src/audit.py`, `src/service.py`, `app.py`, `contextledger/audit_store.py`, `contextledger/unified_service.py`
  - 测试：`tests/test_end_to_end.py`, `tests/test_audit_query.py`, `tests/test_integration.py`
  - 文档：`docs/product/mvp-v0.md`, `docs/source/handbook-fintech-track.md`, `docs/architecture/unified-integration.md`, `docs/product/engineering-challenges.md`

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

  - 代码：`src/audit.py`, `scripts/demo_audit_tamper.py`, `contextledger/audit_store.py`
  - 测试：`tests/test_audit.py`, `tests/test_integration.py`
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

  - 代码：`src/audit.py`, `src/audit_query.py`, `src/service.py`, `app.py`, `contextledger/unified_service.py`, `contextledger/web.py`
  - 测试：`tests/test_audit_query.py`, `tests/test_integration.py`
  - 文档：`docs/product/mvp-v0.md`, `docs/source/handbook-fintech-track.md`

## REQ-009 · LLM 安全边界

- 来源：FinTech track handbook
- 权威级别：`handbook_mandatory`
- 状态：`in_progress`
- 说明：大模型只负责对已授权证据进行总结，不能决定权限或引用未授权内容。
- 验收标准：

  - 权限决定由确定性代码执行
  - 通过同一组跨来源回答、拒答、结构化输出、延迟和 Token 用量样例比较候选模型并记录选型依据
  - 模型返回的引用 ID 必须经过服务端校验
  - 模型只接收已授权且未过期的 Top-K 证据，并能生成跨 Jira、Slack、Confluence 和 Google Drive 的综合回答
  - API 超时、配置缺失、输出无法解析或引用非法时自动退回确定性回答
  - 无 API Key 时仍可用确定性模式完成演示
  - 团队后续专题 EC-008：在引用编号合法之外评估主张与证据支持关系、无依据推断和不可信来源指令；当前编号校验不能冒充语义验证

- 影响范围：

  - 代码：`src/answering.py`, `src/service.py`, `app.py`, `contextledger/unified_service.py`
  - 测试：`tests/test_answering.py`, `tests/test_no_leakage.py`, `tests/test_end_to_end.py`, `tests/test_integration.py`
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
  - 团队专题 EC-005：Primary 等信息层级标签可解释、可纠正，线程聚合和摘要不混用不同权限内容

- 影响范围：

  - 代码：—
  - 测试：—
  - 文档：`docs/product/roadmap.md`

## REQ-015 · 统一分类、混合索引与身份感知查询路由

- 来源：team discussion marked 【新需求】 on 2026-10-02
- 权威级别：`team_decision`
- 状态：`in_progress`
- 说明：通过统一分类和身份感知路由组织异构信息；集成版采用支持元数据过滤的 Qdrant 向量后端，保留结构化事实库与关键词索引，并由应用服务维护可信权限和版本条件。
- 验收标准：

  - 统一分类字段至少覆盖来源、内容类型、部门、项目、业务实体、时间、权威等级、安全密级和当前状态
  - 明确字段保存在结构化索引，语义内容按需进入向量索引，内容未变化时不重复生成向量
  - Query 路由提取意图、实体、时间和来源范围，并结合当前身份生成检索过滤条件
  - 先执行元数据和关键词过滤，再进行向量召回与排序，最后只把少量 Top-K 证据交给模型
  - 物理索引默认共享、通过 collection 或 namespace 和 metadata filter 逻辑隔离；只有规模或安全边界需要时才拆分
  - 向量后端使用已确认的 Qdrant，检索携带服务端生成的授权与有效状态过滤条件，并对实际使用的过滤字段建立 payload 索引；不能仅用 Top-K 后过滤充当索引层授权
  - 查询结果回到结构化事实库核对文档、分块、内容版本与当前权限；Qdrant 不作为权限或新鲜度的唯一事实源
  - 团队后续专题 EC-004/006：细化失败恢复、增量发布与分类或过窄路由造成的漏检；首版整快照阻断不冒充高可用增量同步

- 影响范围：

  - 代码：`contextledger/filtered_index.py`
  - 测试：`tests/test_integration.py`
  - 文档：`docs/product/roadmap.md`, `docs/architecture/integration-plan.md`, `docs/architecture/index-and-freshness.md`

## REQ-016 · 可信调用身份与持久化身份权限库

- 来源：team integration discussion confirmed on 2026-10-05; browser login deferred by user on 2026-10-06
- 权威级别：`team_decision`
- 状态：`in_progress`
- 说明：以持久化身份权限库管理稳定调用身份、来源映射、组织与组、角色、项目、本地限制和权限版本。真实浏览器登录延期，保留 Part A 前端用于当前集成验收；用户已确认在回环／SSH 预览中新增独立 ContextLedger 管理员和六个员工，使用隔离演示状态复用实际权限和审计服务。Agent Tool 是后续设想，不作为当前前置条件，演示身份选择不能宣称为生产鉴权。
- 验收标准：

  - 生产问答、搜索、原文读取、权限管理和审计查询均以服务端验证的调用身份为准，不接受模型或普通请求参数自报身份；演示模式显式启用、使用独立权限与审计状态、仅允许回环访问并标注非生产鉴权
  - 系统用户使用稳定身份标识映射到来源身份，不仅凭显示姓名匹配；未来 Tool 身份传递机制在延期的 REQ-020 确认，不阻塞当前前端验收方案
  - 身份映射、组、角色、项目、本地限制和权限版本持久化保存，重启或重建内容索引不会丢失
  - 管理员和合规功能在服务端执行角色检查，普通用户不能通过调用接口自行提权
  - 每次请求解析最新权限；具体撤权时效和来源 ACL 保真继续由 REQ-005 与 REQ-003 管理
  - 浏览器登录已于 2026-10-06 延期，不作为当前验收前置条件；OIDC 默认停用，已有配置或旧会话不能意外重新启用；未验证的生产业务请求仍拒绝访问，演示身份入口不在普通模式开放
  - 来源身份由管理员显式绑定，不仅凭姓名自动匹配；离线 ACL 与真实身份的全面一致性改造后续专题讨论
  - 独立系统管理员显示名为 ContextLedger 管理员，不借用现有数据集员工，默认没有来源身份绑定，管理角色不自动授予业务资料读取权限；隔离演示账号不能冒充已验证的真实管理员
  - 六个演示员工显式绑定到六个已存在的来源身份，页面可切换固定名单但不能创建任意身份；停用账号不可进入业务，成员不能直接调用管理员或审计接口
  - 演示初始化与重启保留已有撤权和本地限制，不自动恢复权限；拒绝将已有非演示权限库用于演示模式，禁止演示模式和 OIDC 混用

- 影响范围：

  - 代码：`contextledger/identity_store.py`, `contextledger/demo_identity.py`, `contextledger/web.py`, `contextledger/integration.py`, `contextledger/templates/unified.html`, `contextledger/static/unified.js`, `scripts/sync_preview_config.py`, `.env.integration.example`
  - 测试：`tests/test_integration.py`, `tests/test_demo_identity.py`, `tests/test_preview_config.py`, `tests/test_oidc.py`
  - 文档：`docs/architecture/integration-plan.md`, `docs/decisions/ADR-0002-unified-entry-and-trusted-identity.md`, `docs/decisions/ADR-0003-tool-first-and-deferred-browser-login.md`, `docs/architecture/unified-integration.md`, `docs/product/prompt-and-login-walkthrough.md`, `docs/product/tool-entry-scope.md`

## REQ-017 · Part A 与安全问答服务统一集成

- 来源：team integration discussion confirmed on 2026-10-05
- 权威级别：`team_decision`
- 状态：`in_progress`
- 说明：将 Part A 数据与检索连接既有权限管理、新鲜度、回答、引用校验和审计服务，形成同一应用服务；用户于 2026-10-06 澄清本轮保留 Part A 前端作为集成和人工验收入口，只延期真实浏览器登录，Agent Tool 由 REQ-020 后续讨论。
- 验收标准：

  - 保留 Part A 风格前端，提供搜索、问答、证据与原文，并向相应授权角色提供权限管理和审计功能，支持完整人工验收
  - 前端调用同一应用服务，读取一致的身份权限状态，不维护第二套权限逻辑；未来工具适配层复用该服务，不是当前验收前置条件
  - Part A 检索证据通过统一权限与新鲜度检查后进入既有回答服务和查询审计链
  - 集成前对齐 main 与本地模型集成分支的需求和引用校验能力，不能把未合入功能宣称为 main 已实现
  - 身份权限与隔离演示边界由 REQ-016、索引权限由 REQ-002、来源 ACL 由 REQ-003、新鲜度由 REQ-004、撤权由 REQ-005、回答与审计由既有 REQ 管理；浏览器登录和未来 Tool 都不属于当前交付前置条件
  - 集成版采用已确认的 Qdrant 可过滤后端，仍保留 Part A 解析、原始与标准化存储能力
  - 本轮优先保障系统内权限撤销，不实现原平台权限撤销的自动发现与同步；保留来源权限检查与同步的适配接口，未启用时明确返回 not_enabled 或 unknown，不伪造同步成功
  - 外部权限自动同步的阶段性延期不取消既有来源 ACL 保真要求，界面和文档明确区分离线权限快照与实时来源权限
  - 不重新加入已取消的四个数据摄取审计模块
  - 本次集成在独立工作分支实施，未经用户人工验收确认不得合并到 main

- 影响范围：

  - 代码：`contextledger/unified_service.py`, `contextledger/web.py`, `contextledger/identity_store.py`, `contextledger/demo_identity.py`, `contextledger/filtered_index.py`, `contextledger/audit_store.py`, `contextledger/source_permissions.py`, `contextledger/templates/unified.html`, `contextledger/static/unified.js`, `contextledger/static/unified.css`, `contextledger/integration.py`, `contextledger/demo_app.py`, `contextledger/pipeline.py`, `scripts/integration.sh`, `scripts/prepare_integration_preview.py`, `scripts/verify_unified_snapshot.py`, `scripts/sync_preview_config.py`, `requirements-integration.txt`
  - 测试：`tests/test_integration.py`, `tests/test_demo_identity.py`, `tests/test_preview_config.py`, `tests/test_oidc.py`
  - 文档：`docs/architecture/integration-plan.md`, `docs/decisions/ADR-0002-unified-entry-and-trusted-identity.md`, `docs/decisions/ADR-0003-tool-first-and-deferred-browser-login.md`, `docs/product/engineering-challenges.md`, `docs/architecture/unified-integration.md`, `docs/product/demo-acceptance.md`, `docs/product/tool-entry-scope.md`, `QUICKSTART.md`, `README.md`, `docs/product/roadmap.md`

## REQ-018 · 端到端质量、安全与性能评测

- 来源：engineering challenges confirmed by user on 2026-10-06
- 权威级别：`team_decision`
- 状态：`planned`
- 说明：以可复现的测试集和规模基准验证信息筛选、授权检索、回答依据、同步与撤权时效、模型费用和存储增长，不仅依赖界面演示。
- 验收标准：

  - 测试集保存问题、身份权限真值、期望证据和期望拒答行为
  - 分别评估信息筛选的关键事实召回、授权范围内检索质量和回答证据支持程度
  - 安全测试覆盖越权访问、系统内撤权、缓存或历史绕过及不可信来源指令
  - 记录数据规模、查询延迟、索引吞吐、撤权和更新时效、模型 Token 或费用及存储增长
  - 测试结果附运行配置与可复现步骤；小样本集成测试不冒充完整规模化评测

- 影响范围：

  - 代码：—
  - 测试：—
  - 文档：`docs/product/engineering-challenges.md`, `docs/product/roadmap.md`

## REQ-019 · 回答 Prompt 的管理与质量评测

- 来源：user requested recording answer prompt design on 2026-10-06
- 权威级别：`team_decision`
- 状态：`planned`
- 说明：将回答阶段的系统指令、用户问题与证据模板、上下文预算及模型参数作为项目资产记录并管理，后续通过固定样例评估改进；安全边界沿用 REQ-009，评测框架复用 REQ-018。本轮只记录实际模板与计划，不修改业务 Prompt。
- 验收标准：

  - 记录当前实际发送的系统指令、问题与证据格式、身份字段、证据截断和模型输出限制，示例不得包含真实密钥或无权限资料
  - 后续修改回答 Prompt 时保留可追踪版本与变更理由，使实验能够区分 Prompt、模型和检索证据的变化
  - 通过固定的跨来源、证据不足、引用及不可信来源指令样例比较 Prompt 版本，质量与成本评测复用 REQ-018，不把更改措辞本身当作改进证明
  - Prompt 不能替代 REQ-009 的确定性权限与引用校验；当前编号合法检查不得宣称已经验证逐句事实支持

- 影响范围：

  - 代码：`src/answering.py`, `contextledger/unified_service.py`
  - 测试：`tests/test_answering.py`
  - 文档：`docs/product/prompt-and-login-walkthrough.md`, `docs/evaluation/model-selection.md`

## REQ-020 · 面向上游 Agent 的权限感知工具接口

- 来源：user proposed a future LLM tool on 2026-10-06 and clarified it is not the current integration scope
- 权威级别：`team_decision`
- 状态：`deferred`
- 说明：后续可将统一检索服务作为上游 Agent 可调用的工具。用户已明确本轮不做 Tool，继续在 Part A 前端验收集成；具体采用 MCP、HTTP 工具或本地调用以及身份验证方式待后续确认，不宣称工具入口已实现。
- 验收标准：

  - 明确工具接入协议、部署信任边界与上游最终用户身份验证方式，再实现适配层；浏览器登录不是工具接入的必要前置条件
  - 工具只接受问题与已授权范围内的检索条件，权限身份由可信运行时注入或验证，不能由模型在工具参数中任意选择 user_id、角色或来源 principal
  - 即使使用共享服务凭据，也必须保留并验证最终用户身份，不把全部请求归为拥有所有员工权限的一个服务账号
  - 工具复用统一身份权限库、Qdrant/FTS 前置过滤、证据二次校验、交付检查和审计，不建立旁路权限实现
  - 默认返回可追溯的授权证据、来源、版本和请求标识供上游模型使用；是否在工具内部再次生成回答需要明确，不强制每次工具调用重复调用模型
  - 测试同一问题对两个不同权限身份的结果、伪造身份、未验证身份、系统内撤权、原文访问和审计权限；未建立可信身份时拒绝访问
  - 不以实现 Tool 阻塞 REQ-017 当前前端验收；未来 Tool 与前端复用服务，测试注入身份不得暴露为生产伪登录

- 影响范围：

  - 代码：`contextledger/unified_service.py`, `contextledger/identity_store.py`, `contextledger/filtered_index.py`, `contextledger/web.py`
  - 测试：`tests/test_integration.py`
  - 文档：`docs/product/tool-entry-scope.md`, `docs/decisions/ADR-0003-tool-first-and-deferred-browser-login.md`, `docs/architecture/unified-integration.md`, `docs/product/roadmap.md`
