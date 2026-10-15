# 需求与追踪矩阵

> 此文件由 `project/requirements.json` 自动生成，请勿手工修改。

最后更新：2026-10-15

| ID | 需求 | 权威级别 | 状态 | 代码 | 测试 |
|---|---|---|---|---|---|
| REQ-001 | 跨来源自然语言问答与引用 | `handbook_mandatory` | `in_progress` | `contextledger/answering/service.py`<br>`contextledger/application/service.py`<br>`contextledger/interfaces/web.py` | `tests/application/test_integration.py` |
| REQ-002 | 检索前确定性权限过滤 | `handbook_mandatory` | `in_progress` | `contextledger/answering/service.py`<br>`contextledger/retrieval/filtered_index.py`<br>`contextledger/application/service.py` | `tests/application/test_integration.py`<br>`tests/answering/test_answering.py` |
| REQ-003 | 保留来源访问控制语义 | `handbook_mandatory` | `in_progress` | `contextledger/answering/models.py`<br>`contextledger/access/identity_store.py`<br>`contextledger/retrieval/filtered_index.py`<br>`contextledger/access/source_permissions.py` | `tests/application/test_integration.py` |
| REQ-004 | 新鲜度与来源状态 | `handbook_mandatory` | `in_progress` | `contextledger/answering/models.py`<br>`contextledger/retrieval/filtered_index.py`<br>`contextledger/storage/rechunk.py`<br>`contextledger/retrieval/vectors.py` | `tests/application/test_integration.py` |
| REQ-005 | 权限变更即时生效 | `handbook_mandatory` | `implemented` | `contextledger/access/identity_store.py`<br>`contextledger/interfaces/web.py`<br>`contextledger/application/service.py`<br>`contextledger/interfaces/static/unified.js` | `tests/application/test_integration.py` |
| REQ-006 | 可查询的完整审计记录 | `handbook_mandatory` | `in_progress` | `contextledger/audit/chain.py`<br>`contextledger/audit/store.py`<br>`contextledger/application/service.py` | `tests/application/test_integration.py` |
| REQ-007 | 防篡改审计链 | `handbook_mandatory` | `implemented` | `contextledger/audit/chain.py`<br>`scripts/demo_audit_tamper.py`<br>`contextledger/audit/store.py` | `tests/audit/test_audit.py`<br>`tests/application/test_integration.py` |
| REQ-008 | 自然语言审计查询 | `handbook_mandatory` | `in_progress` | `contextledger/audit/chain.py`<br>`contextledger/audit/query.py`<br>`contextledger/answering/service.py`<br>`contextledger/application/service.py`<br>`contextledger/interfaces/web.py`<br>`contextledger/interfaces/static/unified.js` | `tests/application/test_integration.py`<br>`tests/answering/test_answering.py` |
| REQ-009 | LLM 安全边界 | `handbook_mandatory` | `in_progress` | `contextledger/answering/service.py`<br>`contextledger/application/service.py` | `tests/answering/test_answering.py`<br>`tests/application/test_integration.py` |
| REQ-010 | 单一案例选择与展示声明 | `handbook_mandatory` | `implemented` | — | — |
| REQ-011 | 业务演变呈现与时序冲突提示（Decision Radar） | `team_decision` | `in_progress` | `contextledger/ingestion/connectors.py`<br>`contextledger/storage/models.py`<br>`contextledger/storage/store.py`<br>`contextledger/ingestion/pipeline.py`<br>`contextledger/retrieval/filtered_index.py`<br>`contextledger/application/service.py`<br>`contextledger/interfaces/web.py`<br>`contextledger/interfaces/integration.py`<br>`contextledger/interfaces/templates/unified.html`<br>`contextledger/interfaces/static/unified.js`<br>`contextledger/interfaces/static/unified.css`<br>`contextledger/answering/workflows.py`<br>`contextledger/answering/service.py`<br>`contextledger/radar/protocol.py`<br>`contextledger/radar/tool.py`<br>`contextledger/radar/data.py`<br>`contextledger/radar/store.py`<br>`scripts/radar_demo.py`<br>`contextledger/evaluation/radar_demo.py`<br>`contextledger/retrieval/search.py`<br>`contextledger/radar/resolution.py` | `tests/application/test_integration.py`<br>`tests/application/test_llm_integration.py`<br>`tests/answering/test_llm_workflows.py`<br>`tests/answering/test_answering.py`<br>`tests/radar/test_radar.py`<br>`tests/radar/test_radar_data.py`<br>`tests/radar/test_radar_integration.py`<br>`tests/radar/test_radar_resolution.py` |
| REQ-012 | 项目内容统一入库与 Git 协作 | `team_decision` | `implemented` | `scripts/project_sync.py`<br>`.github/workflows/ci.yml` | `tests/operations/test_project_sync.py` |
| REQ-013 | 交付材料与格式待确认清单 | `pending_confirmation` | `in_progress` | — | — |
| REQ-014 | 异构来源摄取、清洗与高价值信息筛选 | `team_decision` | `in_progress` | `contextledger/ingestion/source_adapters.py`<br>`contextledger/ingestion/source_sync.py` | `tests/ingestion/test_source_adapters.py` |
| REQ-015 | 统一分类、混合索引与身份感知查询路由 | `team_decision` | `in_progress` | `contextledger/retrieval/filtered_index.py`<br>`contextledger/retrieval/search.py`<br>`contextledger/application/service.py` | `tests/application/test_integration.py` |
| REQ-016 | 可信调用身份与持久化身份权限库 | `team_decision` | `in_progress` | `contextledger/access/identity_store.py`<br>`contextledger/access/demo_identity.py`<br>`contextledger/interfaces/web.py`<br>`contextledger/interfaces/integration.py`<br>`contextledger/interfaces/templates/unified.html`<br>`contextledger/interfaces/static/unified.js`<br>`scripts/sync_preview_config.py`<br>`.env.integration.example` | `tests/application/test_integration.py`<br>`tests/access/test_demo_identity.py`<br>`tests/operations/test_preview_config.py`<br>`tests/access/test_oidc.py` |
| REQ-017 | Part A 与安全问答服务统一集成 | `team_decision` | `in_progress` | `contextledger/application/service.py`<br>`contextledger/interfaces/web.py`<br>`contextledger/access/identity_store.py`<br>`contextledger/access/demo_identity.py`<br>`contextledger/retrieval/filtered_index.py`<br>`contextledger/audit/store.py`<br>`contextledger/access/source_permissions.py`<br>`contextledger/interfaces/templates/unified.html`<br>`contextledger/interfaces/static/unified.js`<br>`contextledger/interfaces/static/unified.css`<br>`contextledger/interfaces/integration.py`<br>`contextledger/interfaces/demo_app.py`<br>`contextledger/ingestion/pipeline.py`<br>`contextledger/storage/rechunk.py`<br>`scripts/integration.sh`<br>`scripts/prepare_integration_preview.py`<br>`scripts/verify_unified_snapshot.py`<br>`scripts/sync_preview_config.py`<br>`requirements-integration.txt`<br>`.github/workflows/ci.yml`<br>`contextledger/interfaces/static/onboarding.svg`<br>`contextledger/answering/service.py`<br>`contextledger/radar/protocol.py` | `tests/application/test_integration.py`<br>`tests/access/test_demo_identity.py`<br>`tests/operations/test_preview_config.py`<br>`tests/operations/test_prepare_preview.py`<br>`tests/access/test_oidc.py`<br>`tests/operations/test_integration_dependencies.py`<br>`tests/ingestion/part_a/test_supplemental.py`<br>`tests/ingestion/part_a/conftest.py`<br>`tests/application/test_llm_integration.py`<br>`tests/answering/test_radar_synthesis.py`<br>`tests/radar/test_radar_integration.py` |
| REQ-018 | 端到端质量、安全与性能评测 | `team_decision` | `in_progress` | `contextledger/evaluation/retrieval.py`<br>`contextledger/evaluation/scenarios.py`<br>`contextledger/evaluation/quality.py`<br>`scripts/refine_part_a_retrieval.py`<br>`contextledger/evaluation/refinement.py`<br>`scripts/tune_part_a_retrieval.py`<br>`contextledger/evaluation/tuning.py`<br>`scripts/part_a.sh`<br>`contextledger/evaluation/freshness.py`<br>`contextledger/evaluation/workload.py`<br>`contextledger/evaluation/replay.py`<br>`scripts/freshness_eval.sh` | `tests/evaluation/test_part_a_evaluation.py`<br>`tests/evaluation/test_part_a_refinement.py`<br>`tests/evaluation/test_part_a_tuning.py`<br>`tests/answering/test_llm_workflows.py`<br>`tests/application/test_llm_integration.py`<br>`tests/evaluation/test_freshness_eval.py` |
| REQ-019 | 回答 Prompt 的管理与质量评测 | `team_decision` | `in_progress` | `contextledger/answering/service.py`<br>`contextledger/answering/workflows.py`<br>`contextledger/application/service.py` | `tests/answering/test_answering.py`<br>`tests/answering/test_llm_workflows.py` |
| REQ-020 | 面向上游 Agent 的权限感知工具接口 | `team_decision` | `in_progress` | `contextledger/application/service.py`<br>`contextledger/access/identity_store.py`<br>`contextledger/retrieval/filtered_index.py`<br>`contextledger/access/tool_access.py`<br>`contextledger/interfaces/tool_api.py`<br>`contextledger/interfaces/mcp_server.py`<br>`scripts/mcp_private_launcher.py`<br>`contextledger/interfaces/private_launcher.py`<br>`requirements-tools.txt` | `tests/application/test_integration.py`<br>`tests/interfaces/test_tool_interfaces.py`<br>`tests/interfaces/test_mcp_launcher.py` |

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

  - 代码：`contextledger/answering/service.py`, `contextledger/application/service.py`, `contextledger/interfaces/web.py`
  - 测试：`tests/application/test_integration.py`
  - 文档：`README.md`, `docs/product/mvp-v0.md`, `docs/source/handbook-fintech-track.md`, `docs/product/workload.md`, `docs/evaluation/chat.md`

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

  - 代码：`contextledger/answering/service.py`, `contextledger/retrieval/filtered_index.py`, `contextledger/application/service.py`
  - 测试：`tests/application/test_integration.py`, `tests/answering/test_answering.py`
  - 文档：`docs/product/mvp-v0.md`, `docs/source/handbook-fintech-track.md`, `docs/product/workload.md`, `docs/product/llm-feature-plan.md`, `docs/product/demo-acceptance.md`

### 功能扩展 · 零证据安全回答与全部读取权限撤销 Demo

- 扩展键：`zero_evidence_response`
- 来源：user requested on 2026-10-11
- 权威级别：`team_decision`（独立于基础需求）
- 状态：`implemented`
- 说明：权限过滤后无证据使用统一中英文提示和版本化 Prompt；本机及 gpushare 合成回归覆盖保持账号/绑定有效的全部读取撤权、零证据无模型调用、旧原文拒绝和审计。新版隔离预览的实际部署记录见实施说明，真人与录制验收仍待完成，不把回归或页面启动当作录制验收。
- 验收标准：

  - 零证据返回 insufficient、空证据与空引用，不猜测业务事实，不说明资料在全库不存在，也不披露受限内容的存在、名称、标题、链接、ID、数量或被拒绝原因
  - 系统指令明确空证据处理；默认由服务端直接返回统一安全提示，不为零证据额外调用模型。若上游模型需要该状态，仅发送原问题与空授权证据，不发送无权限资料，并继续校验输出
  - 零证据提示区分于未登录、账号停用、索引/同步异常；这些状态不能伪装成正常零结果
  - Demo 保持员工账号和会话有效，仅撤销全部业务读取权限：先正常回答、管理员撤权、相同问题返回零证据与安全提示、尝试旧原文被拒绝、合规人员核对审计；权限恢复只恢复演示前合法状态
  - 中英文未知问题和撤权后的零证据均使用不暗示受限内容存在的措辞；有权限时仍有正常回答的正向对照

- 影响范围：

  - 代码：`contextledger/answering/service.py`, `contextledger/application/service.py`, `contextledger/interfaces/web.py`, `contextledger/interfaces/static/unified.js`
  - 测试：`tests/answering/test_answering.py`, `tests/application/test_integration.py`, `tests/access/test_demo_identity.py`, `tests/application/test_llm_integration.py`
  - 文档：`docs/product/llm-feature-plan.md`, `docs/product/workload.md`, `docs/product/demo-acceptance.md`, `docs/architecture/llm-workflows.md`

## REQ-003 · 保留来源访问控制语义

- 来源：FinTech track handbook
- 权威级别：`handbook_mandatory`
- 状态：`in_progress`
- 说明：统一层必须保留来源系统的部门、角色、项目和敏感级别约束。
- 验收标准：

  - 合成数据包含部门、角色、项目和敏感级别元数据
  - 后续真实连接器不得把来源权限降级为单一公开/私有标记

- 影响范围：

  - 代码：`contextledger/answering/models.py`, `contextledger/access/identity_store.py`, `contextledger/retrieval/filtered_index.py`, `contextledger/access/source_permissions.py`
  - 测试：`tests/application/test_integration.py`
  - 文档：`docs/product/mvp-v0.md`, `docs/source/handbook-fintech-track.md`, `docs/product/workload.md`

### 功能扩展 · 四平台只读适配的来源授权快照

- 扩展键：`live_source_permission_snapshots`
- 来源：user confirmed automatic source permission reads on 2026-10-14
- 权威级别：`team_decision`（独立于基础需求）
- 状态：`in_progress`
- 说明：本轮读取平台可验证的授权信息并映射显式配置的稳定来源身份；未知、失败或不完整权限隔离，不能把采集账号权限授予全部员工。初次实现按用户要求不运行测试；随后 Codex 试用阶段离线回归通过，但四来源未做真实联调，状态不提升为 validated。2026-10-15 用户确认收窄来源门闩：刷新、失败或过期只隔离对应 live 来源数据，静态导入和其他已验证来源继续查询；同步发布路径及交付复核一并修复，真实平台验收仍另记。
- 验收标准：

  - Jira/Confluence 使用来源有效权限检查，Slack 使用完整成员快照，Drive 保留权限条目并仅映射可验证的用户授权；来源身份映射显式配置，未映射或不支持的权限语义不猜测放行
  - 分页、限流和检查失败不生成宽松 ACL；原始记录和权限检查依据保存于私有存储，权限未知的新记录不入检索，既有记录重新检查时先阻断旧授权
  - 来源授权仅证明本次观察快照，不宣称实时原平台撤权或完整企业目录同步；系统内权限限制仍优先生效
  - 来源刷新、失败、快照过期或缺少就绪依据时，仅 live:<source>: 资源及其待发布版本被检索前隔离；同 corpus 静态数据、其他有效来源和其他 corpus 不被来源门闩整体锁住，SQL 与 Qdrant 均前置过滤
  - 来源队列在分块/向量发布期间和失败重试后仍隔离对应资料；模型前后、原文、Radar 与交付复核重新读取门闩；整库重建和非来源手工更新继续保留既有一致性保护，不把来源部分结果当作全库完整扫描
  - 2026-10-15 用户确认修复 ACL 依据：管理员改变实际 ACL 后，当前依据标为管理员调整，原来源依据、观察时间、版本及 ACL 保存在既有不可变版本历史；仅正文修改或 ACL 重排不冒充权限变更，可信来源重新验证与来源撤权分别标注，依据说明不参与授权决定

- 影响范围：

  - 代码：`contextledger/ingestion/source_adapters.py`, `contextledger/ingestion/source_sync.py`, `contextledger/retrieval/filtered_index.py`, `contextledger/storage/document_updates.py`
  - 测试：`tests/ingestion/test_source_adapters.py`, `tests/ingestion/test_source_sync.py`, `tests/application/test_document_updates.py`
  - 文档：`docs/architecture/source-and-agent-interfaces.md`, `config/sources.example.json`, `docs/decisions/ADR-0005-source-adapters-and-mcp.md`, `docs/architecture/index-and-freshness.md`

### 功能扩展 · 多模式确定性权限接入接口 v2 设计

- 扩展键：`permission_provider_contract_v2`
- 来源：user requested on 2026-10-15: preserve current dataset ACL; design native Slack, project/classification/department and POSIX rwx permission integrations without requiring live dataset use
- 权威级别：`team_decision`（独立于基础需求）
- 状态：`planned`
- 说明：本轮交付接口设计和报告可用表述，不接入或替换现有数据集 ACL。统一快照、原生平台、企业属性策略、POSIX DAC/ACL及外部PDP五种模式；标明现有适配子集与新设计能力，不以设计稿冒充实现或真实企业验收。
- 验收标准：

  - 权限解析和执行不依赖LLM；身份、组、项目、部门、密级来自已配置的可信来源，正文不能自行授予权限
  - 每份资源配置一种主授权依据，可叠加必须满足的属性和本地撤权规则；不同模式不得任意取并集或在失败时降级放行
  - 统一接口记录稳定身份、资源、权限版本、观察时间、过期时间、完整性与授权依据，明确unknown/unsupported和缺失字段语义
  - 分别规定Slack范围/成员/线程继承、项目与密级及允许部门组合、Linux UID/GID/父目录搜索/访问ACL及mask的确定性处理和边界
  - 权限条件在SQL/FTS/Qdrant检索前应用，生成和交付重查当前权限；外部PDP仅能单资源check但无法提供安全候选范围时不开放该检索模式
  - 当前离线ACL及服务器演示保持原状；报告区分已实现、受控测试、设计扩展、真实平台未验证，附后续验收矩阵

- 影响范围：

  - 代码：—
  - 测试：—
  - 文档：`docs/architecture/permission-interfaces-v2.md`, `docs/decisions/ADR-0007-permission-provider-contract.md`, `docs/README.md`

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

  - 代码：`contextledger/answering/models.py`, `contextledger/retrieval/filtered_index.py`, `contextledger/storage/rechunk.py`, `contextledger/retrieval/vectors.py`
  - 测试：`tests/application/test_integration.py`
  - 文档：`docs/product/mvp-v0.md`, `docs/source/handbook-fintech-track.md`, `docs/architecture/index-and-freshness.md`, `docs/product/workload.md`, `docs/architecture/decision-radar-v1.md`

### 功能扩展 · 正式新增与修改的自动索引发布闭环

- 扩展键：`document-update-chain`
- 来源：user requested automatic add/update to indexed answers on 2026-10-12
- 权威级别：`team_decision`（独立于基础需求）
- 状态：`validated`
- 说明：管理员或可信运维提交新增／修改后，由持久化后台任务更新事实库、FTS 与受影响分块的向量并发布，随后问答使用新版证据。用户于 2026-10-12 明确跳过本次真实模型验收。
- 验收标准：

  - 新增／修改通过受控 API 与 CLI 提交，版本前置条件防止旧任务覆盖新内容，来源 ACL 不默认放开
  - 更新任务持久化、进程重启可恢复、失败可重试；更新未发布时不交付旧版证据或答案
  - 事实库与关键词索引事务更新，向量只重算受影响分块；两类索引核对成功后发布新的代次
  - 保存旧版内容、版本、ACL 与分块；同一问题在新增／修改后从 5 万切换到 10 万，分别验证关键词、向量、混合检索、回答与审计

- 影响范围：

  - 代码：`contextledger/storage/document_updates.py`, `contextledger/storage/index_lock.py`, `contextledger/retrieval/filtered_index.py`, `contextledger/interfaces/web.py`, `contextledger/interfaces/integration.py`, `contextledger/retrieval/vectors.py`, `scripts/verify_document_updates.py`
  - 测试：`tests/application/test_document_updates.py`
  - 文档：`QUICKSTART.md`, `docs/architecture/index-and-freshness.md`

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

  - 代码：`contextledger/access/identity_store.py`, `contextledger/interfaces/web.py`, `contextledger/application/service.py`, `contextledger/interfaces/static/unified.js`
  - 测试：`tests/application/test_integration.py`
  - 文档：`docs/product/mvp-v0.md`, `docs/source/handbook-fintech-track.md`, `docs/product/workload.md`

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

  - 代码：`contextledger/audit/chain.py`, `contextledger/audit/store.py`, `contextledger/application/service.py`
  - 测试：`tests/application/test_integration.py`
  - 文档：`docs/product/mvp-v0.md`, `docs/source/handbook-fintech-track.md`, `docs/architecture/unified-integration.md`, `docs/product/engineering-challenges.md`, `docs/product/workload.md`

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

  - 代码：`contextledger/audit/chain.py`, `scripts/demo_audit_tamper.py`, `contextledger/audit/store.py`
  - 测试：`tests/audit/test_audit.py`, `tests/application/test_integration.py`
  - 文档：`docs/product/mvp-v0.md`, `docs/source/handbook-fintech-track.md`, `docs/product/workload.md`

## REQ-008 · 自然语言审计查询

- 来源：FinTech track handbook
- 权威级别：`handbook_mandatory`
- 状态：`in_progress`
- 说明：授权人员可以询问谁在何时访问了哪些信息以及系统为何允许。既有条件查询与事件引用已实现；新增模型摘要代码和合成回归已接，真实配置/效果和人工验收仍进行中，不把代码或旧查询实现当作模型质量通过。
- 验收标准：

  - 支持按用户、请求、时间和证据 ID 查询
  - 审计查询本身受权限控制并被审计
  - 回答包含可核对的事件引用

- 影响范围：

  - 代码：`contextledger/audit/chain.py`, `contextledger/audit/query.py`, `contextledger/answering/service.py`, `contextledger/application/service.py`, `contextledger/interfaces/web.py`, `contextledger/interfaces/static/unified.js`
  - 测试：`tests/application/test_integration.py`, `tests/answering/test_answering.py`
  - 文档：`docs/product/mvp-v0.md`, `docs/source/handbook-fintech-track.md`, `docs/product/workload.md`, `docs/product/llm-feature-plan.md`, `docs/product/demo-acceptance.md`

### 功能扩展 · 合规人员的大模型审计问答

- 扩展键：`llm_audit_answer`
- 来源：user requested on 2026-10-11
- 权威级别：`team_decision`（独立于基础需求）
- 状态：`in_progress`
- 说明：已接入角色受控审计模型回答、白名单脱敏、有界事件与 E 引用，模型前后/交付检查当前角色、证据与链。合成回归通过；真实模型回答和真人验收仍待完成。
- 验收标准：

  - 调用前执行 admin/compliance 角色检查；普通员工不能通过页面、接口或模型生成的参数访问审计，模型不能执行任意 SQL 或决定角色、授权与查询范围
  - 模型只读取服务端已授权、已脱敏且预算内的审计事件，不读取整份日志库；日志里的历史问题、回答与指令均作为不可信数据
  - 答案使用 [E序号] 等事件引用，服务端检查引用属于本次可见结果；日志截断或无匹配时说明本次结果范围，不据此推断整个时间段没有访问行为
  - 审计问答在模型前后和交付前复核当前角色及相关业务证据权限；日志完整性异常时不把记录作为可信事实回答
  - 记录本次审计问答的请求、可见事件引用、模型/Prompt 版本与复核状态；不记录或泄漏无权限明文，查询本身继续进入哈希链
  - 模型失败、未配置或输出不合规时回退现有确定性查询结果，不宣称已生成可靠的模型审计回答

- 影响范围：

  - 代码：`contextledger/application/service.py`, `contextledger/answering/workflows.py`, `contextledger/interfaces/web.py`, `contextledger/audit/store.py`, `contextledger/interfaces/static/unified.js`, `contextledger/interfaces/templates/unified.html`, `contextledger/audit/query.py`, `contextledger/answering/service.py`, `.env.integration.example`
  - 测试：`tests/application/test_integration.py`, `tests/answering/test_answering.py`, `tests/answering/test_llm_workflows.py`, `tests/application/test_llm_integration.py`
  - 文档：`docs/product/llm-feature-plan.md`, `docs/product/workload.md`, `docs/product/demo-acceptance.md`, `docs/architecture/llm-workflows.md`

### 功能扩展 · 审计自然语言时间条件解析修复

- 扩展键：`audit_relative_time_filters`
- 来源：user confirmed parser repair on 2026-10-13 after actual request-log validation
- 权威级别：`team_decision`（独立于基础需求）
- 状态：`implemented`
- 说明：修复过去一周／一个月被静默当作无时间条件的问题；使用确定性规则生成带时区的起止时间，不新增日志时间字段或LLM查询解析。模型路由是后续独立改动。
- 验收标准：

  - 最近／过去N天、N周、N个月支持数字和常用中文数量；一周是连续7天，一个月按自然月回退并处理月末
  - 今天／昨天按UTC日界查询；支持范围及UTC口径在文档说明，不支持或歧义的时间条件返回明确错误，不静默扩大为全时间范围
  - 通过实际统一审计服务验证旧事件在模型调用前被过滤；保持普通员工拒绝、脱敏、完整性校验及失败回退

- 影响范围：

  - 代码：`contextledger/audit/query.py`, `contextledger/application/service.py`
  - 测试：`tests/audit/test_audit_time_parser.py`
  - 文档：`docs/architecture/audit-query-flow.md`

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

  - 代码：`contextledger/answering/service.py`, `contextledger/application/service.py`
  - 测试：`tests/answering/test_answering.py`, `tests/application/test_integration.py`
  - 文档：`README.md`, `docs/product/mvp-v0.md`, `docs/evaluation/model-selection.md`, `docs/source/handbook-fintech-track.md`, `docs/product/workload.md`, `docs/product/llm-feature-plan.md`, `docs/product/demo-acceptance.md`

### 功能扩展 · 模型引用复核（用户已取消）

- 扩展键：`independent_citation_review`
- 来源：user cancelled the complete review and feedback rewrite workflow on 2026-10-11
- 权威级别：`team_decision`（独立于基础需求）
- 状态：`deferred`
- 说明：2026-10-11 用户明确取消整个模型复核与反馈重答功能。本条保留需求历史，deferred 表示退出本轮及后续待办，不代表等待自动重启。移除业务/审计复核调用、重答、配置、界面与专用评测，保留确定性格式、引用编号、权限与版本检查；未实施逐句事实保证。
- 验收标准：

  - 业务和审计不再执行模型语义复核及反馈重答，删除专用配置、界面和评测入口，旧 LLM_REVIEW_* 配置不能重启该功能
  - 继续确定性校验输出格式与本次授权引用编号，模型调用前后和 HTTP 交付时仍校验权限、版本；审计仍校验角色、事件引用和哈希链
  - 页面、文档和审计不把取消后的回答宣称为逐句事实已验证；历史记录保留，不清除身份权限、内容索引或审计数据

- 影响范围：

  - 代码：`contextledger/answering/service.py`, `contextledger/answering/workflows.py`, `contextledger/application/service.py`, `contextledger/interfaces/web.py`, `contextledger/interfaces/static/unified.js`, `contextledger/interfaces/static/unified.css`, `contextledger/interfaces/templates/unified.html`, `.env.integration.example`, `scripts/sync_preview_config.py`
  - 测试：`tests/answering/test_answering.py`, `tests/application/test_integration.py`, `tests/answering/test_llm_workflows.py`, `tests/application/test_llm_integration.py`, `tests/operations/test_preview_config.py`
  - 文档：`docs/product/llm-feature-plan.md`, `docs/product/workload.md`, `docs/product/demo-acceptance.md`, `docs/architecture/llm-workflows.md`, `docs/product/prompt-and-login-walkthrough.md`, `docs/product/update-2026-10-11.md`

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

## REQ-011 · 业务演变呈现与时序冲突提示（Decision Radar）

- 来源：team discussion; user confirmed automatic internal tool design on 2026-10-12
- 权威级别：`team_decision`
- 状态：`in_progress`
- 说明：在现有统一问答入口默认由 LLM 判断是否调用内部 decision_radar 工具，围绕问题与授权检索结果定位实体、补查证据并组织业务演变；不提供用户手动切换，不要求入库预建业务标签/事件库。按具体事实评价证据，有充分支持给结论，部分支持说明边界，不足或冲突说明原因。2026-10-12 最终方案与 ADR-0004 方向已确认，随后实现本地候选版本；生产与语义验收另记。 2026-10-12 用户授权开始开发：保留 PR #7 的检索前 QueryPlanner，Radar 在检索后的回答阶段自动调用；分支基于 PR #7 head，按先合并工作流再合并 Radar 的顺序交付。代码与真实质量验收分别记录。 本地 v1 已接入内部结构化工具 action、当前权限下的编号/名称补查、统一引用与折叠时间线，保留 PR #7 检索前规划；四案例原生业务 fixture、三阶段受控发布/观测修订已实现。真实模型触发、语义质量与生产增量/原生完整历史的验收分别记录，未部署或合并。 2026-10-12 用户要求将资料上限从40提高并以项目名称/业务词语而非预给编号验证：新增查询时有界名称/多语言检索，先召回授权候选、再从候选识别编号展开；独立管理资料与模型正文预算并报告各类截断。
- 验收标准：

  - 用户只需在现有问答入口提问，默认自动；LLM 可直接回答或请求 decision_radar，前端无普通/自动/Radar 切换、工具按钮或专用入口
  - 复用 /api/ask 与 UnifiedService，旧请求无新增必填字段，旧 answer/evidence/request_id 等字段兼容；需要时可附 radar 结构化过程，普通搜索与原文契约保留
  - 系统提示词与严格工具契约定义可调用能力；原生工具格式或结构化 action 由服务端执行同一验证，模型不能传身份/权限、任意 SQL、网络地址或数据库路径
  - 单请求最多一次内部 Radar 调用、内部最多两轮补查；实体来自原问题或实际授权证据，保持原问题约束；未知/多义实体不编造或静默合并，预算超限报告范围
  - 原文照常存储，实际来源修订保留；可选轻量明确 ID 引用索引，主体/事件/关系按问题查询时组装，不要求预建全库业务标签与事件表
  - 所有补查复用当前 Scope，工具前后、模型前后与最终交付检查权限 epoch、索引 generation、来源/分块版本；隐藏标题、节点、边和数量不泄漏，子资源/历史读取遵守当前根资源权限
  - 新证据加入统一 citation registry，事件/关系有真实出处、revision/hash 与原文定位；作者报告、要求、承诺、批准和运行通知分别表示，不补造回滚、diff 或行动项完成
  - 区分事件、采集与业务生效时间，缺失保持未知，date/day/timestamp 冲突不静默改写；不同部门状态和明确属性分歧给出出处，不以逻辑时钟、最新时间或平台名称裁决真相
  - 可靠性按具体事实与原始记录类型评价；Jira 工单状态、PR 合并/revert、生产部署/回滚和运行恢复分别说明；人工 Slack 与可验证 bot 回执分开，重复转发不计独立证据，无未经校准可靠概率
  - 有足够支持给明确结论并引用，部分支持说明边界，证据不足或冲突说明原因；工具返回证据给同次问答模型组织答案，不强制所有问题展开时间线
  - 工具或模型缺失/失败保留已支持的确定性来源/状态与安全降级，不伪造工具成功；权限/版本变化中止交付，不恢复已取消的第二模型语义复核和反馈重答
  - 四组 OrgForge 作为开发与分阶段回放材料，未来评论/最终状态/evaluator 真值不提前入模；补充来源 ACL 明确为合成映射或默认拒绝，不冒充真实平台权限同步
  - 实际来源历史、删除/撤回与回滚复用 REQ-004；SQLite/FTS/Qdrant/可选引用索引与历史存储同代次安全发布，失败不可读，新信息可见耗时实测，不冒称生产增量同步
  - 自动触发正反例、错/漏调用率、实体/关系召回、事件覆盖、证据支持、更新时间与 Token/延迟分别评测；四个开发案例不证明泛化，初始预算与 60 秒小样本工程目标经实测调整
  - 内部 LLM 工具不等于 REQ-020 外部 Agent/MCP/插件适配，本轮不扩展对外协议或恢复浏览器登录
  - 默认资料上限提高至120，资料/事件/关系/正文/时间预算分别报告；模型正文预算不随资料数量无限增加，关键状态和提问相关段落优先保留
  - 员工可使用项目名、组件名或无编号业务描述起查；跨语言查询时生成有界检索短语，内部编号只能来自实际授权候选，不硬编码四案例别名或将语义近似候选判为同一实体；未知专名不自动纠错
  - 四案例补充全部不含内部编号的真实模型问题；区分名称匹配、证据召回、工具触发、故事节点覆盖与全量语料泛化，增加未知/同名/权限变更负例
  - Radar 综合回答额外返回受限结构化展示摘要：只有证据足以支持所问业务结果、授权检索未截断且没有未解决重要分歧时才可标为 Confirmed；其余不可判定情况标为 Pending confirmation 并列出具体待核实条件；该状态与 answered/insufficient 回答状态分离

- 影响范围：

  - 代码：`contextledger/ingestion/connectors.py`, `contextledger/storage/models.py`, `contextledger/storage/store.py`, `contextledger/ingestion/pipeline.py`, `contextledger/retrieval/filtered_index.py`, `contextledger/application/service.py`, `contextledger/interfaces/web.py`, `contextledger/interfaces/integration.py`, `contextledger/interfaces/templates/unified.html`, `contextledger/interfaces/static/unified.js`, `contextledger/interfaces/static/unified.css`, `contextledger/answering/workflows.py`, `contextledger/answering/service.py`, `contextledger/radar/protocol.py`, `contextledger/radar/tool.py`, `contextledger/radar/data.py`, `contextledger/radar/store.py`, `scripts/radar_demo.py`, `contextledger/evaluation/radar_demo.py`, `contextledger/retrieval/search.py`, `contextledger/radar/resolution.py`
  - 测试：`tests/application/test_integration.py`, `tests/application/test_llm_integration.py`, `tests/answering/test_llm_workflows.py`, `tests/answering/test_answering.py`, `tests/radar/test_radar.py`, `tests/radar/test_radar_data.py`, `tests/radar/test_radar_integration.py`, `tests/radar/test_radar_resolution.py`
  - 文档：`docs/product/roadmap.md`, `docs/product/mvp-v0.md`, `docs/product/workload.md`, `docs/architecture/decision-radar-v1.md`, `docs/decisions/ADR-0004-decision-radar.md`, `docs/architecture/decision-radar-validation.md`, `fixtures/radar/README.md`

### 功能扩展 · Radar综合阶段Flash high与推理预算

- 扩展键：`radar_reasoning_synthesis`
- 来源：user requested task-three model comparison and selected Flash high without flagship routing on 2026-10-13
- 权威级别：`team_decision`（独立于基础需求）
- 状态：`implemented`
- 说明：普通问答与内部工具选择保持原Flash配置；只有服务端执行Radar后才将同一Flash模型的综合阶段升为high推理档位，收紧来源报告与因果、状态和时间边界。模型测试不恢复已取消的第二模型复核。
- 验收标准：

  - 阶段切换由服务端工具执行结果触发，不能由用户正文、模型自由参数或普通直接回答触发；无配置时综合阶段沿用基础model但使用high推理档位
  - 支持RADAR_LLM_REASONING_EFFORT、MAX_TOKENS、TIMEOUT_SECONDS独立预算；不提供独立旗舰模型切换，旧RADAR_LLM_MODEL不生效；普通路径配置不变；每次调用记录阶段、实际模型与用量
  - 引用/格式校验、权限和索引交付门闩保持有效；格式重试留在综合阶段，不重复执行工具；网络失败明确降级而非换模型编造
  - 固定任务三相同授权证据，分别测试原提示/收紧提示、Flash low/high及可用旗舰模型；保留格式失败、超时、耗时和小样本限制

- 影响范围：

  - 代码：`contextledger/answering/service.py`, `contextledger/radar/protocol.py`, `scripts/sync_preview_config.py`, `.env.example`, `.env.integration.example`
  - 测试：`tests/answering/test_radar_synthesis.py`, `tests/operations/test_preview_config.py`, `tests/audit/test_audit_time_parser.py`
  - 文档：`docs/architecture/radar-reasoning-comparison.md`

### 功能扩展 · Radar 状态摘要与 Aspire 响应式界面

- 扩展键：`radar_presentation_ui`
- 来源：user design handoff and explicit status rule confirmed 2026-10-14
- 权威级别：`team_decision`（独立于基础需求）
- 状态：`implemented`
- 说明：在 Radar 工具综合回答后返回有界业务状态摘要与待确认事项，按 Aspire Financial Modern 设计改造现有应用的 Radar、证据、权限和审计展示。Confirmed 必须有可用授权证据、回答充分、无工具检测到的未决分歧且结果未被截断；其余情况标记 Pending confirmation 并提供具体待核实项。复用当前引用与权限 API，不宣称逐句语义验证或用模型自报置信度百分比。
- 验收标准：

  - Radar 响应中仅在工具综合阶段附加 presentation 字段；包含 confirmed/pending_confirmation、简短判断、说明、授权引用编号和待确认列表；旧字段与非 Radar 请求保持兼容
  - 服务端验证字段形状、文本边界与所有引用均属于本次授权证据；confirmed 必须 answered、至少有引用、无未决分歧且资料未截断；pending_confirmation 必须列出具体待核实事项
  - 前端只在 confirmed 时显示 Confirmed，只在 pending_confirmation 时显示 Pending confirmation 和 Needs confirmation；普通回答或格式降级失败时不猜测业务状态
  - 证据护照从现有引用打开原文并显示版本、时间、访问依据和内容指纹；不展示未经校准置信度、实时 p95 或外部签章能力
  - 隔离 Demo 的管理员可用现有权限接口撤销员工来源绑定，员工切换身份后重查；普通员工页面不泄漏受限标题或受限资料是否存在
  - 审计页面展示请求字段和当前可见证据；事件被整体脱敏时同时隐藏 Radar presentation
  - Desktop、tablet 与 320px 以上 mobile 使用同一组页面结构自适应，手机端保留顶部横向角色受控导航，资料 Passport 为全屏对话框
  - 页面遵循用户提供的 Stitch 结构：搜索首页为全宽提问区加双栏引导／示例；Radar 为问题横幅加判断／时间线主栏与 Security Lens／证据侧栏；权限页为员工选择条与变更前／权限操作／变更后三栏；审计页为顶部筛选与下方事件列表／请求详情。权限状态来自现有用户／绑定 API，不用合成统计冒充证据数量

- 影响范围：

  - 代码：`contextledger/answering/service.py`, `contextledger/radar/protocol.py`, `contextledger/application/service.py`, `contextledger/interfaces/templates/unified.html`, `contextledger/interfaces/static/unified.js`, `contextledger/interfaces/static/unified.css`
  - 测试：`tests/answering/test_radar_synthesis.py`, `tests/radar/test_radar_integration.py`, `tests/application/test_llm_integration.py`, `tests/access/test_demo_identity.py`
  - 文档：`docs/architecture/decision-radar-v1.md`, `docs/architecture/unified-integration.md`, `docs/product/prompt-and-login-walkthrough.md`

### 功能扩展 · Radar 来源记录时间映射与排序修复

- 扩展键：`radar_source_record_time`
- 来源：user requested deployed Radar timestamp fix, PR and merge on 2026-10-15
- 权威级别：`team_decision`（独立于基础需求）
- 状态：`validated`
- 说明：2026-10-15 用户授权修复、PR并合并：读取授权检索结果 ts，区分来源记录时间与实际操作时间；保留无时区及 date/day/timestamp 差异，修正可比较记录的时间排序并把时间依据传递给同次综合模型。
- 验收标准：

  - ENG-195/PR-135 两条 Slack 记录按来源 ts 排序，原始无时区时间不转换为 SGT
  - 来源 date 与 ts 日期差异可见且传入模型；不将 Slack 通知时间当作 GitHub 操作时间
  - 原生快照状态不借用创建或观察时间冒充状态变更时间；未知及不同时间基准不强行排序

- 影响范围：

  - 代码：`contextledger/radar/timing.py`, `contextledger/radar/tool.py`, `contextledger/radar/protocol.py`, `contextledger/application/service.py`, `contextledger/interfaces/static/stitch/app.js`, `contextledger/interfaces/static/unified.js`, `frontend/stitch/build.cjs`
  - 测试：`tests/radar/test_radar.py`, `tests/radar/test_radar_timing.py`, `tests/radar/test_radar_integration.py`, `frontend/stitch/verify.cjs`
  - 文档：`docs/architecture/decision-radar-v1.md`, `docs/architecture/decision-radar-validation.md`

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
  - 基础需求下的团队功能扩展使用唯一 key、独立 authority 和 status；生成视图同时展示两者，不把团队 planned 扩展继承成官方硬性要求或已实现能力

- 影响范围：

  - 代码：`scripts/project_sync.py`, `.github/workflows/ci.yml`
  - 测试：`tests/operations/test_project_sync.py`
  - 文档：`AGENTS.md`, `CONTRIBUTING.md`, `.github/PULL_REQUEST_TEMPLATE.md`, `docs/README.md`, `docs/decisions/ADR-0001-repository-as-source-of-truth.md`

### 功能扩展 · 按功能分包并统一测试目录

- 扩展键：`functional_package_refactor`
- 来源：user confirmed functional packages and small in-test fixtures on 2026-10-14
- 权威级别：`team_decision`（独立于基础需求）
- 状态：`implemented`
- 说明：已在独立重构分支保留 main bf57bebf 与四来源/MCP f590ba83 功能；src 共享核心和脚本内评测实现迁入十个功能包，scripts 保留命令/运维入口。删除旧 Streamlit、两份跟踪 JSON 及13项旧链路专用测试，共享回答/审计/解析改用小样本，新增11项组织与入口回归。323项 unittest、包含其在内的331项 pytest（含8项 Part A）、真实 stdio 握手及CLI回归通过；未改服务器，真实平台和生成模型联调不属于本次回归。2026-10-14 PR #17 被误合并为 11a805c7，随后 main 由 952881f9 撤回。按用户要求在原工作分支同步该历史，仅在分支撤销撤回并恢复 2f9a405c 的完整代码；业务代码与原提交一致，新增恢复说明。重新走草稿 PR 审查，不改变 main 的撤回状态，不自动合并。
- 验收标准：

  - 业务源码按 application/access/ingestion/storage/retrieval/answering/radar/audit/interfaces/evaluation 分包，scripts 只保留入口或独立运维工具
  - 保留当前前端、四来源/MCP、问答规划/Radar、权限撤销、审计、增量发布、离线 Part A 与评测行为；不更改权限策略、模型默认、数据库或索引格式
  - 删除跟踪的 data/documents.json、data/users.json 及旧 JSON/Streamlit 专用测试与服务；共享回答、审计、类型和解析测试使用构造的小样本继续覆盖，不通过删除核心测试掩盖回归
  - 统一 tests 下的功能测试，保留 Part A 测试分词器的局部作用域；unittest 与 pytest 全量通过，无漏发现测试；CI 安装包括 MCP 在内的依赖
  - 同步需求影响路径、CLI/资源路径、文档、生成视图和变更记录；保留必要 CLI 兼容入口，不删除本地未跟踪数据或服务器原文/权限/索引/审计

- 影响范围：

  - 代码：`contextledger/application/service.py`, `contextledger/retrieval/filtered_index.py`, `contextledger/interfaces/web.py`, `contextledger/answering/service.py`, `contextledger/audit/chain.py`, `contextledger/audit/query.py`, `contextledger/answering/models.py`, `scripts/project_sync.py`, `.github/workflows/ci.yml`, `contextledger/paths.py`, `contextledger/evaluation/audit_fixture.py`, `contextledger/interfaces/private_launcher.py`, `contextledger/interfaces/part_a.py`, `contextledger/evaluation/chat.py`, `contextledger/evaluation/chat_latency.py`, `contextledger/evaluation/refinement.py`, `requirements.txt`
  - 测试：`tests/answering/test_answering.py`, `tests/audit/test_audit.py`, `tests/application/test_integration.py`, `tests/audit/test_audit_time_parser.py`, `tests/ingestion/part_a/test_supplemental.py`, `tests/audit/test_query.py`, `tests/operations/test_functional_packages.py`, `tests/operations/test_integration_dependencies.py`
  - 文档：`docs/architecture/functional-packages.md`, `docs/decisions/ADR-0006-functional-packages.md`, `README.md`, `AGENTS.md`, `CHANGELOG.md`, `QUICKSTART.md`, `CONTRIBUTING.md`, `docs/README.md`, `docs/product/mvp-v0.md`

## REQ-013 · 交付材料与格式待确认清单

- 来源：Handbook pp. 14-20 and 37, and user-provided Submission Requirements screenshot received 2026-10-15; remaining submission details pending confirmation
- 权威级别：`pending_confirmation`
- 状态：`in_progress`
- 说明：已核对用户提供的完整 Handbook 第37页及提交截图：标题、少于10词的简介、四部分项目说明、至少3份真实CodeBuddy/WorkBuddy开发聊天截图或录屏及16:9封面为Required；5–8分钟演示视频和项目链接为Optional。准备英文报告并同步到用户指定Overleaf；真实开发对话附件尚待补齐，未确认的公开仓库、Pitch Deck、截止时间及合规细节继续单独核实。
- 验收标准：

  - 提交前逐项核对比赛邮件中的 Handbook 和登录后的提交表
  - 把已确认字段、格式和截止时间更新到官方来源文档
  - 团队可以提前准备代码、Demo 和架构材料，但必须标记为团队交付策略而非官方硬性要求

- 影响范围：

  - 代码：—
  - 测试：—
  - 文档：`docs/source/submission-open-questions.md`, `docs/source/handbook-fintech-track.md`, `docs/product/workload.md`

### 功能扩展 · 按Handbook与提交表准备英文报告

- 扩展键：`submission_report_20261015`
- 来源：User-provided Handbook pp.14-20 and37 and Submission Requirements screenshot, verified 2026-10-15
- 权威级别：`handbook_mandatory`（独立于基础需求）
- 状态：`in_progress`
- 说明：英文报告覆盖Handbook用户、痛点、五个场景、三个创新功能和实测指标；使用最新前端截图，保留真实开发聊天附件缺口。
- 验收标准：

  - 开头明确唯一案例Internal Brain及FinTech/Aspire赛道；目标用户和痛点从Handbook第14–19页出发，标注30%为场景估计
  - 提供项目标题及少于10个英文单词的简介；四部分覆盖目标场景/用户/价值、现实痛点、业务/技术/Prompt设计及量化或明确影响
  - 五个赛题场景均有worked example，权限、来源新鲜度、审计和当前实现/验证边界清楚区分
  - 附16:9封面和真实CodeBuddy/WorkBuddy开发对话的待补清单；不得把产品截图或整理的提示词冒充开发聊天证据
  - Overleaf写入并编译成功；报告不宣称所有附件或生产验收已完成；只推送工作分支，不合并main

- 影响范围：

  - 代码：—
  - 测试：`tests/operations/test_project_sync.py`
  - 文档：`docs/submission/main.tex`, `docs/submission/README.md`, `docs/submission/assets/cover.png`, `docs/source/submission-requirements-20261015.md`, `docs/source/submission-requirements-20261015.png`, `docs/source/submission-open-questions.md`, `docs/source/handbook-fintech-track.md`, `docs/README.md`, `docs/submission/assets/workspace-latest-en.png`, `docs/submission/assets/workspace-latest-en.json`

### 功能扩展 · 三项创新展示与新版前端截图

- 扩展键：`innovation_showcase_20261015`
- 来源：User requested emphasis on Decision Radar, Security Lens and Evidence Passport, plus latest frontend screenshots on 2026-10-15
- 权威级别：`team_decision`（独立于基础需求）
- 状态：`validated`
- 说明：突出Decision Radar、Security Lens、Evidence Passport；标注示意场景与验证边界。评测数字保持不变。
- 验收标准：

  - 分别说明Decision Timeline、Conflict Radar和Answer Replay，不能把示意09:40/09:47/09:50事件写成实测结果
  - Security Lens展示系统内撤权与角色边界，普通员工不显示受限文档存在与否
  - Evidence Passport列来源/原文/版本/当前访问依据；引用合法与逐句事实支持分开，不编造可信度百分比
  - 最新前端英文截图同步Overleaf并编译，既有实验数字保持不变

- 影响范围：

  - 代码：—
  - 测试：`tests/operations/test_project_sync.py`
  - 文档：`docs/submission/main.tex`, `docs/submission/README.md`, `docs/README.md`, `docs/submission/assets/workspace-latest-en.png`, `docs/submission/assets/workspace-latest-en.json`

## REQ-014 · 异构来源摄取、清洗与高价值信息筛选

- 来源：team discussion marked 【新需求】 on 2026-10-02
- 权威级别：`team_decision`
- 状态：`in_progress`
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

  - 代码：`contextledger/ingestion/source_adapters.py`, `contextledger/ingestion/source_sync.py`
  - 测试：`tests/ingestion/test_source_adapters.py`
  - 文档：`docs/product/roadmap.md`, `docs/product/workload.md`, `docs/architecture/source-and-agent-interfaces.md`, `config/sources.example.json`

## REQ-015 · 统一分类、混合索引与身份感知查询路由

- 来源：team discussion marked 【新需求】 on 2026-10-02
- 权威级别：`team_decision`
- 状态：`in_progress`
- 说明：通过统一分类和身份感知路由组织异构信息；集成版采用支持元数据过滤的 Qdrant 向量后端，保留结构化事实库与关键词索引，并由应用服务维护可信权限和版本条件。
- 验收标准：

  - 统一分类字段至少覆盖来源、内容类型、部门、项目、业务实体、时间、权威等级、安全密级和当前状态
  - 明确字段保存在结构化索引，语义内容按需进入向量索引，内容未变化时不重复生成向量
  - Query 路由提取意图、实体、时间和来源范围，并结合当前身份生成检索过滤条件
  - 首次业务证据检索前的问题理解功能及预算、纠错与权限边界，由本需求的 pre_retrieval_planner 扩展统一管理，不把回答 Prompt 变更当作已接入 Query Planner
  - 先执行元数据和关键词过滤，再进行向量召回与排序，最后只把少量 Top-K 证据交给模型
  - 物理索引默认共享、通过 collection 或 namespace 和 metadata filter 逻辑隔离；只有规模或安全边界需要时才拆分
  - 向量后端使用已确认的 Qdrant，检索携带服务端生成的授权与有效状态过滤条件，并对实际使用的过滤字段建立 payload 索引；不能仅用 Top-K 后过滤充当索引层授权
  - 查询结果回到结构化事实库核对文档、分块、内容版本与当前权限；Qdrant 不作为权限或新鲜度的唯一事实源
  - 团队后续专题 EC-004/006：细化失败恢复、增量发布与分类或过窄路由造成的漏检；首版整快照阻断不冒充高可用增量同步

- 影响范围：

  - 代码：`contextledger/retrieval/filtered_index.py`, `contextledger/retrieval/search.py`, `contextledger/application/service.py`
  - 测试：`tests/application/test_integration.py`
  - 文档：`docs/product/roadmap.md`, `docs/architecture/integration-plan.md`, `docs/architecture/index-and-freshness.md`, `docs/architecture/query-planning.md`, `docs/product/demo-acceptance.md`, `docs/product/workload.md`, `docs/product/llm-feature-plan.md`

### 功能扩展 · 提问先过 LLM 的子问题与关键词检索计划

- 扩展键：`pre_retrieval_planner`
- 来源：user requested on 2026-10-07 and reaffirmed on 2026-10-11
- 权威级别：`team_decision`（独立于基础需求）
- 状态：`in_progress`
- 说明：已接启用时首次检索前一次规划、受限 JSON、子问题/语义句进入授权 Qdrant、关键词进入授权 FTS、原问题保留与总 Top-5 融合。开关/失败回退/纠错确认和撤权有合成回归；真实模型的召回/质量/延迟收益评测待完成。
- 验收标准：

  - 保留原问题；LLM 输出受限 JSON 的子问题、关键词、语义检索句与歧义候选，服务端校验格式、长度、数量与总检索预算，不接受任意 SQL、过滤表达式、身份或权限指令
  - 子问题与语义检索句用于向量检索，关键词用于 FTS 关键词检索；Top-K 是返回数量而非另一种索引，各分支去重融合为总预算内的最终授权 Top-K
  - 所有分支沿用当前身份、来源 ACL、本地限制与版本过滤，保留原问题检索，规划失败或超时回退原问题，不放宽权限
  - 启用规划时先解析当前身份，模型只接收原问题与必要安全提示，不预读全库或无权限标题；每次最多一次规划，不对每个子问题递归调用模型
  - 纠错和话外意思仅为候选，不擅自更换实体、时间、否定或比较条件；改变问题含义时先要求用户确认，最终回答仍针对原问题
  - 设置功能开关与模型调用/Token/超时预算，记录计划和安全诊断版本；通过固定评测比较不开启与开启的召回、回答质量、延迟、费用与撤权安全

- 影响范围：

  - 代码：`contextledger/answering/workflows.py`, `contextledger/application/service.py`, `contextledger/retrieval/filtered_index.py`, `contextledger/retrieval/search.py`, `contextledger/interfaces/web.py`, `contextledger/interfaces/static/unified.js`, `contextledger/interfaces/templates/unified.html`, `.env.integration.example`, `scripts/sync_preview_config.py`, `contextledger/answering/service.py`
  - 测试：`tests/application/test_integration.py`, `tests/answering/test_answering.py`, `tests/answering/test_llm_workflows.py`, `tests/application/test_llm_integration.py`, `tests/operations/test_preview_config.py`
  - 文档：`docs/architecture/query-planning.md`, `docs/architecture/llm-workflows.md`, `docs/product/llm-feature-plan.md`, `docs/product/workload.md`

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

  - 代码：`contextledger/access/identity_store.py`, `contextledger/access/demo_identity.py`, `contextledger/interfaces/web.py`, `contextledger/interfaces/integration.py`, `contextledger/interfaces/templates/unified.html`, `contextledger/interfaces/static/unified.js`, `scripts/sync_preview_config.py`, `.env.integration.example`
  - 测试：`tests/application/test_integration.py`, `tests/access/test_demo_identity.py`, `tests/operations/test_preview_config.py`, `tests/access/test_oidc.py`
  - 文档：`docs/architecture/integration-plan.md`, `docs/decisions/ADR-0002-unified-entry-and-trusted-identity.md`, `docs/decisions/ADR-0003-tool-first-and-deferred-browser-login.md`, `docs/architecture/unified-integration.md`, `docs/product/prompt-and-login-walkthrough.md`, `docs/product/tool-entry-scope.md`, `docs/product/workload.md`

### 功能扩展 · 所属数据集保持可选与资料范围授权

- 扩展键：`resource_access_controls`
- 来源：user confirmed on 2026-10-15 for submission demo; preserve imported ACL and focus OrgForge
- 权威级别：`team_decision`（独立于基础需求）
- 状态：`in_progress`
- 说明：已实现并部署至既有 gpushare 17866 隔离演示入口；所属数据集保持可选，Security Lens 按数据集、来源和文档管理后端读取限制，保留原始 ACL 与撤权状态。真实 OrgForge 索引隔离验证及当前 Jax 撤权查询通过；用户人工重试待完成。 2026-10-15用户授权只对实际演示问题相关资源人工标注项目、部门和密级，并接通相应管理与追溯；不推广到其他数据。 2026-10-16 定向4份资料标注已部署到17866并通过真实模型、撤权/密级/部门对照与浏览器技术验收；用户人工验收待完成。
- 验收标准：

  - 撤销数据集或全部来源读取权后，员工仍能选择已有映射的数据集；无证据时不调用模型并返回安全提示
  - 管理员按数据集、来源和文档调整本地限制，恢复不能绕过原始来源 ACL；普通员工无法调用管理接口
  - 同一员工部分撤权后仅返回剩余授权来源，全部撤权后旧原文不可读，权限版本与审计记录同步更新
  - 历史撤销的身份绑定不自动恢复；页面仅提供员工已绑定来源身份的明确恢复入口，不展示其他员工身份作为授权选项
  - 演示权限按显式文档ID和原内容哈希白名单应用，保留正文与其他全部文档；人工标注带独立来源说明，私聊不额外授予Jax权限
  - 只对ENG-195/PR-135演示资源标注项目、允许部门及confidential级别；项目拒绝和密级变化在实际关键词/向量检索、原文及回答交付生效，恢复后正常回答
  - Security Lens展示已标注的演示项目、允许部门和员工密级，Evidence Passport展示人工权限标注；原始来源ACL与本地限制继续生效

- 影响范围：

  - 代码：`contextledger/interfaces/web.py`, `contextledger/access/identity_store.py`, `contextledger/interfaces/static/stitch/app.js`, `contextledger/interfaces/static/stitch/index.html`, `contextledger/interfaces/static/stitch/responsive.css`, `contextledger/answering/service.py`, `contextledger/access/demo_permissions.py`, `contextledger/storage/document_updates.py`, `config/demo-permissions.example.json`, `scripts/apply_demo_permissions.py`
  - 测试：`tests/interfaces/test_stitch_api.py`, `tests/interfaces/test_stitch_frontend.py`, `tests/answering/test_answering.py`, `tests/access/test_demo_permissions.py`, `tests/application/test_document_updates.py`
  - 文档：`docs/product/resource-permissions.md`, `docs/README.md`, `docs/product/curated-demo-permissions.md`, `docs/product/permission-demo-handoff-2026-10-15.md`

## REQ-017 · Part A 与安全问答服务统一集成

- 来源：team integration discussion confirmed on 2026-10-05
- 权威级别：`team_decision`
- 状态：`in_progress`
- 说明：将 Part A 数据与检索连接既有权限管理、新鲜度、回答、引用校验和审计服务，形成同一应用服务；用户于 2026-10-06 澄清本轮保留 Part A 前端作为集成和人工验收入口，只延期真实浏览器登录，Agent Tool 由 REQ-020 后续讨论。
- 验收标准：

  - 保留统一前端入口，提供搜索、问答、证据与原文，并向相应授权角色提供权限管理和审计功能，支持完整人工验收
  - 2026-10-12 用户要求在组员最新版中保留现有 DashKit 风格英文前端与教学图，接入检索前规划状态／开关和受控模型审计解释入口；前端仍复用服务端身份、权限、CSRF 与审计接口，不绕过现有安全检查
  - 前端调用同一应用服务，读取一致的身份权限状态，不维护第二套权限逻辑；未来工具适配层复用该服务，不是当前验收前置条件
  - Part A 检索证据通过统一权限与新鲜度检查后进入既有回答服务和查询审计链
  - 集成前对齐 main 与本地模型集成分支的需求和引用校验能力，不能把未合入功能宣称为 main 已实现
  - 身份权限与隔离演示边界由 REQ-016、索引权限由 REQ-002、来源 ACL 由 REQ-003、新鲜度由 REQ-004、撤权由 REQ-005、回答与审计由既有 REQ 管理；浏览器登录和未来 Tool 都不属于当前交付前置条件
  - 集成版采用已确认的 Qdrant 可过滤后端，仍保留 Part A 解析、原始与标准化存储能力
  - 本轮优先保障系统内权限撤销，不实现原平台权限撤销的自动发现与同步；保留来源权限检查与同步的适配接口，未启用时明确返回 not_enabled 或 unknown，不伪造同步成功
  - 外部权限自动同步的阶段性延期不取消既有来源 ACL 保真要求，界面和文档明确区分离线权限快照与实时来源权限
  - 不重新加入已取消的四个数据摄取审计模块
  - 中文与英文实体相邻输入可检索；未知实体不强行用无关候选作答，拼写建议仅来自当前授权资料且不自动替换；模型降级明确标记未生成可靠答案，记录不含密钥或原始模型输出的失败原因
  - 本次集成在独立工作分支实施；2026-10-08 用户授权在修复审查问题、补齐依赖并完成真实索引重建与验证后，通过 Pull Request 合并到 main；条件未满足时不得合并
  - 重新分块后旧 Qdrant 快照明确失效；元数据主键、授权过滤字段与分块变化进入变更检查；新向量与新 collection 校验通过后才发布，旧 collection、身份权限与审计保留；副本链接指向实际原始数据位置，目录切换不能产生循环链接；不把整快照重建冒充高可用增量同步
  - 2026-10-13 用户明确授权合并 feat/REQ-017-team-ui-integration 到 main；DashKit 页面保留当前后端及自动 Radar 的覆盖说明、分歧与证据原文入口，普通模式不自动选择身份
  - 2026-10-14 按 Aspire Financial Modern 设计改造统一问答、Radar、证据护照、权限和审计页面；桌面与移动端自适应，手机保留顶部横向导航；权限演示复用隔离 Demo 的真实权限服务，页面只显示接口提供的证据和审计状态

- 影响范围：

  - 代码：`contextledger/application/service.py`, `contextledger/interfaces/web.py`, `contextledger/access/identity_store.py`, `contextledger/access/demo_identity.py`, `contextledger/retrieval/filtered_index.py`, `contextledger/audit/store.py`, `contextledger/access/source_permissions.py`, `contextledger/interfaces/templates/unified.html`, `contextledger/interfaces/static/unified.js`, `contextledger/interfaces/static/unified.css`, `contextledger/interfaces/integration.py`, `contextledger/interfaces/demo_app.py`, `contextledger/ingestion/pipeline.py`, `contextledger/storage/rechunk.py`, `scripts/integration.sh`, `scripts/prepare_integration_preview.py`, `scripts/verify_unified_snapshot.py`, `scripts/sync_preview_config.py`, `requirements-integration.txt`, `.github/workflows/ci.yml`, `contextledger/interfaces/static/onboarding.svg`, `contextledger/answering/service.py`, `contextledger/radar/protocol.py`
  - 测试：`tests/application/test_integration.py`, `tests/access/test_demo_identity.py`, `tests/operations/test_preview_config.py`, `tests/operations/test_prepare_preview.py`, `tests/access/test_oidc.py`, `tests/operations/test_integration_dependencies.py`, `tests/ingestion/part_a/test_supplemental.py`, `tests/ingestion/part_a/conftest.py`, `tests/application/test_llm_integration.py`, `tests/answering/test_radar_synthesis.py`, `tests/radar/test_radar_integration.py`
  - 文档：`docs/evaluation/aspire-server-20261015.md`, `docs/architecture/integration-plan.md`, `docs/decisions/ADR-0002-unified-entry-and-trusted-identity.md`, `docs/decisions/ADR-0003-tool-first-and-deferred-browser-login.md`, `docs/product/engineering-challenges.md`, `docs/architecture/unified-integration.md`, `docs/product/part-a-integration-review.md`, `docs/product/demo-acceptance.md`, `docs/product/tool-entry-scope.md`, `QUICKSTART.md`, `README.md`, `docs/product/roadmap.md`, `docs/product/workload.md`, `docs/architecture/decision-radar-v1.md`, `docs/evaluation/chat.md`, `docs/product/frontend-team-integration.md`, `docs/product/prompt-and-login-walkthrough.md`

### 功能扩展 · Tailscale 私有常驻试用入口

- 扩展键：`private-tailnet-preview`
- 来源：user requested deployment for browser use on other Tailscale machines on 2026-10-13
- 权威级别：`team_decision`（独立于基础需求）
- 状态：`validated`
- 说明：通过 Tailscale Serve 与回环可信网关部署隔离演示；保持固定账号、CSRF、权限与版本检查，持久化内容/权限/审计和 Qdrant，由后台服务常驻。不是生产登录。 2026-10-13 固定代码部署通过新浏览器、真实模型、角色导航、零证据拒答及另一台 Tailscale 机器 TLS 检查；适用合成演示与允许登录范围。
- 验收标准：

  - 入口只通过私有 Tailscale Serve 到达回环后端，校验明确允许的 Tailscale 登录、固定 Host 和浏览器 Origin；不开启公网 Funnel
  - TLS、Secure Cookie、固定演示账号与原应用 CSRF/ACL/版本检查保留；来源身份不能由代理头授予
  - 后台服务和 Qdrant 可重启，内容与安全状态分离并持久化；部署使用固定代码提交，不重跑或改写测评结果
  - 实测 HTTPS 页面、身份选择、真实模型回答、越权拒答和跨机器访问，保存部署步骤与当前 URL
  - 2026-10-13 API 交互检查：当前请求的拒绝／冲突／网络失败显示明确错误并恢复按钮；错误响应清理证据后仍可提示，身份或问题变化后的旧成功与旧错误都不能覆盖当前页面。真实请求与失败注入分别报告

- 影响范围：

  - 代码：`contextledger/interfaces/tailnet_preview.py`, `scripts/serve_tailnet_preview.py`, `requirements-tailnet-preview.txt`, `contextledger/interfaces/web.py`, `contextledger/interfaces/templates/unified.html`, `contextledger/interfaces/static/unified.js`, `contextledger/interfaces/static/unified.css`, `contextledger/interfaces/static/onboarding.svg`
  - 测试：`tests/interfaces/test_tailnet_preview.py`, `tests/access/test_demo_identity.py`, `tests/application/test_integration.py`, `tests/application/test_llm_integration.py`, `scripts/check_chat_ui.py`
  - 文档：`docs/architecture/tailnet-preview.md`, `docs/decisions/ADR-0003-tool-first-and-deferred-browser-login.md`

### 功能扩展 · 直接使用 Stitch HTML 的独立前端

- 扩展键：`stitch_independent_frontend`
- 来源：user explicitly requested a separate frontend preserving the existing version on 2026-10-14
- 权威级别：`team_decision`（独立于基础需求）
- 状态：`implemented`
- 说明：直接导入用户五张桌面设计页的 HTML，保留原始文件并编译本地样式、字体与素材；新版作为唯一默认首页复用现有身份、问答、证据、权限和审计 API。原 unified 前端仅备份，不提供切换入口。
- 验收标准：

  - 原 unified.html、unified.css、unified.js 保留本轮开始时的版本并备份；新版使用独立文件并作为默认首页，不与原版集成
  - 保留用户 HTML 的页面 DOM、Tailwind 配置和组件类，不用原前端样式重新绘制；原文件哈希纳入来源清单
  - 本地编译样式并整理字体和图片，不加载原设计里的模拟交互脚本；业务数据只来自现有 API，未知／示意指标不作为已验证结果
  - 搜索、Radar、证据护照、管理员撤权和审计使用当前会话、CSRF 与授权检查；身份／权限变化或页面隐藏时清理旧结果
  - 桌面保留设计稿布局，移动端使用顶部横向导航并堆叠多栏内容
  - 2026-10-15 显示审查修复：Passport 清除全部原稿示例节点与固定版本／事件数；技术详情可实际展开、折叠并提供正确的可访问状态
  - 320–1600px 包括 768/820/900px 平板断点的页面与顶栏控件无横向溢出；紧凑视口直接聚焦证据面板，支持关闭、键盘返回及恢复引用焦点
  - 手机首页压缩重复信息并将示例问题放在使用引导之前；长标题与时间线使用可展开的有界显示，证据总数保留且列表可滚动
  - 审计标识缩略展示并支持复制完整值；时间明确标注时区且完整原值保留；手机交互目标约44px，加载状态在按钮内，错误提示置于对应页面内容中
  - 2026-10-15 新版作为唯一默认首页，原版前端按文件备份且不显示切换入口；删除中文设计说明，演示身份显示英文；Query planning 可切换且不会被会话轮询覆盖；操作按钮自动调整字号保持单行；Audit 筛选自适应网格；使用用户提供的 vectorized.svg.svg 引导图
  - 2026-10-15 问题卡使用独立配色与结论分层；移除 Isolated demo 视觉标签；搜索区数据集、规划和提交控件统一高度；下拉菜单圆角与主题绿色选中态；参考 emilkowalski/skills 的动效原则实现 Radar 与 Passport 的焦点转移和短时切换，支持 reduced motion 与快速返回，权限清理不等待动画
  - 2026-10-15 定稿前端与 origin/main 9ad487e 合并；沿用功能分包和 sources/MCP 功能，静态文件迁入 interfaces/static/stitch，默认首页仅使用定稿新版；保留主分支语言与工具参数校验及本地 Radar presentation 契约，来源 ACL 当前依据与历史追溯分离；布局、配色与动效不重新设计
  - 2026-10-15 补齐英文页面生成语言契约，覆盖Has开头、insufficient及Radar所有展示字段；原文外链仅在有效HTTP(S)来源地址存在时显示；审计区分未记录证据、当前不可访问、版本不匹配和索引不可核对，并在授权范围内展示历史授权记录，不泄漏受限标题/ID
  - 首页使用引导标签保持单行和独立宽度；窄屏时整块标签换到标题下方，不压缩图标或挤成两行
  - 2026-10-15 Radar摘要与完整回答分别展示；完整回答可键盘展开，保留原文与引用，身份或权限变化后清空；没有摘要时不重复显示同一回答
  - 2026-10-15 侧栏左上角品牌图使用团队提供的 ContextLedger 矢量 logo，替换原截图式占位图；去除整幅白底并裁成方形，与两行品牌文字等高，同时作为页面图标

- 影响范围：

  - 代码：`frontend/stitch/build.cjs`, `frontend/stitch/package.json`, `frontend/stitch/package-lock.json`, `frontend/stitch/source/01_search_home.html`, `frontend/stitch/source/02_decision_radar.html`, `frontend/stitch/source/03_evidence_passport.html`, `frontend/stitch/source/04_security_lens.html`, `frontend/stitch/source/05_audit_trail.html`, `contextledger/interfaces/static/stitch/index.html`, `contextledger/interfaces/static/stitch/app.js`, `contextledger/interfaces/static/stitch/design.css`, `contextledger/interfaces/static/stitch/responsive.css`, `contextledger/interfaces/static/stitch/fonts.css`, `contextledger/interfaces/static/stitch/source-manifest.json`, `contextledger/interfaces/web.py`, `contextledger/interfaces/static/stitch/assets/vectorized.svg.svg`, `frontend/legacy-backup/2026-10-15`, `.gitattributes`, `contextledger/answering/service.py`, `contextledger/application/service.py`, `contextledger/interfaces/static/stitch/assets/contextledger-logo.svg`
  - 测试：`tests/interfaces/test_stitch_frontend.py`, `frontend/stitch/verify.cjs`, `tests/interfaces/test_stitch_api.py`, `tests/answering/test_radar_synthesis.py`
  - 文档：`docs/product/stitch-independent-frontend.md`

## REQ-018 · 端到端质量、安全与性能评测

- 来源：engineering challenges confirmed by user on 2026-10-06
- 权威级别：`team_decision`
- 状态：`in_progress`
- 说明：以可复现的测试集和规模基准验证信息筛选、授权检索、回答依据、同步与撤权时效、模型费用和存储增长，不仅依赖界面演示。已接入 Part A 固定参考证据召回、覆盖率、耗时与合成安全回归；离线 BGE/Qwen 排序实验不自动接入前端。真实回答质量、未见测试集、模型费用和完整规模评测仍未完成。 2026-10-12 PR #7 同步已合入 main 的 #8/#9 新鲜度评测与英文 quickstart，保留模型工作流和在线版本评测的全部验收及影响文件；同步与回归不代表生产或语义验收完成。 Radar 分支同步该父分支修复，保留 REQ-011 与名称起查评测范围；未改变业务实现或完成状态。
- 验收标准：

  - 测试集保存问题、身份权限真值、期望证据和期望拒答行为
  - 分别评估信息筛选的关键事实召回、授权范围内检索质量和回答证据支持程度
  - 安全测试覆盖越权访问、系统内撤权、缓存或历史绕过及不可信来源指令
  - 记录数据规模、查询延迟、索引吞吐、撤权和更新时效、模型 Token 或费用及存储增长
  - 测试结果附运行配置与可复现步骤；小样本集成测试不冒充完整规模化评测
  - 2026-10-10 团队确认一周交付优先覆盖 Handbook 五个场景：跨来源引用问答、新鲜度、无权限不泄漏、撤权和合规审计；每项保存可复现步骤、预期与实际结果，区分离线回归、受控来源端到端测试和真实平台验证
  - 五场景端到端评测调用当前集成服务及其真实权限、索引、回答和审计链路，不能仅以旧 MVP 或 Part A 离线评测通过替代；系统内撤权和原平台权限同步分别报告，Mock 降级不能计为真实模型回答质量通过
  - 2026-10-11 保留三项功能的端到端正反例：模型审计问答的角色/脱敏/事件引用、检索前拆解的开关对比、全部业务读取权限撤销后的零证据提示；模型引用复核及反馈重答已取消，不再作为交付或评测待办。失败注入与真实模型质量分别报告
  - 新鲜度评测按固定事件流和查询时点的证据版本真值计算在线 Recall；未同步、拒答、失败与缺失结果保留在分母，在线曲线与最终静态测量分开报告

- 影响范围：

  - 代码：`contextledger/evaluation/retrieval.py`, `contextledger/evaluation/scenarios.py`, `contextledger/evaluation/quality.py`, `scripts/refine_part_a_retrieval.py`, `contextledger/evaluation/refinement.py`, `scripts/tune_part_a_retrieval.py`, `contextledger/evaluation/tuning.py`, `scripts/part_a.sh`, `contextledger/evaluation/freshness.py`, `contextledger/evaluation/workload.py`, `contextledger/evaluation/replay.py`, `scripts/freshness_eval.sh`
  - 测试：`tests/evaluation/test_part_a_evaluation.py`, `tests/evaluation/test_part_a_refinement.py`, `tests/evaluation/test_part_a_tuning.py`, `tests/answering/test_llm_workflows.py`, `tests/application/test_llm_integration.py`, `tests/evaluation/test_freshness_eval.py`
  - 文档：`docs/product/engineering-challenges.md`, `docs/product/roadmap.md`, `BENCHMARK_QUICKSTART.md`, `QUICKSTART.md`, `docs/product/workload.md`, `docs/product/llm-feature-plan.md`, `docs/product/update-2026-10-11.md`, `docs/README.md`, `docs/architecture/llm-workflows.md`, `docs/architecture/decision-radar-v1.md`

### 功能扩展 · 真实模型聊天与前端回归评测

- 扩展键：`real-chat-evaluation`
- 来源：user requested chat evaluation and latest frontend update on 2026-10-13
- 权威级别：`team_decision`（独立于基础需求）
- 状态：`validated`
- 说明：固定合成授权资料与问题，调用实际 /api/ask、Qdrant、回答和审计链；分别记录事实/状态/引用检查、拒答、更新与浏览器行为。真实模型实测不等同完整语义或生产验收。
- 验收标准：

  - 保存固定问题、期望事实与证据版本；失败和拒答保留在分母
  - 使用本地配置的真实模型及原生 Qdrant，分别报告回答、跨来源审批状态、无证据/越权、更新后答案和延迟
  - 浏览器检查回答/原文/权限切换与手机布局；明确当前为单轮问答，省略实体的追问不自动继承旧上下文
  - 保留原始结果、模型/Prompt/源码指纹和复现命令；不保存密钥或真实公司资料
  - 2026-10-15 定稿 Stitch 前端在 c7a7967 基线上完成3项真实API冒烟：2项真实模型问答/原文哈希通过，1项未知实体零生成拒答；保留一次格式修正记录。本次keyword/规划关闭，不计为真实向量召回或生产验收

- 影响范围：

  - 代码：`scripts/evaluate_chat.py`, `contextledger/evaluation/chat.py`, `scripts/check_chat_ui.py`, `fixtures/chat/evaluation.json`, `contextledger/answering/service.py`, `contextledger/interfaces/static/unified.js`, `contextledger/interfaces/templates/unified.html`, `contextledger/radar/protocol.py`, `contextledger/answering/workflows.py`
  - 测试：`tests/evaluation/test_chat_evaluation.py`, `tests/answering/test_answering.py`, `tests/answering/test_radar_synthesis.py`, `tests/radar/test_radar_integration.py`
  - 文档：`docs/evaluation/chat.md`, `docs/README.md`, `BENCHMARK_QUICKSTART.md`, `docs/product/prompt-and-login-walkthrough.md`, `docs/evaluation/stitch-live-20261015.md`

### 功能扩展 · 聊天延迟分阶段对照

- 扩展键：`chat_latency_experiments`
- 来源：user requested measured optimisation opportunities on 2026-10-14
- 权威级别：`team_decision`（独立于基础需求）
- 状态：`validated`
- 说明：冻结合成内容、权限、原生索引与模型，交错比较既有 high、只改工具提示与低推理参数；逐次计时模型调用、检索和工具，并保留失败。不修改在线服务或已确认的复杂问题 high 默认。补充固定复杂业务综合输入的 high/low/none 与严格 JSON 候选；none仅隔离属性覆写，不扩展生产配置。2026-10-14 完成36个原生完整HTTP与14个固定综合阶段观测；原始与重评分分开，记录候选退化和复杂材料失败。合并前补充HTTP超时/连接/响应解析失败入账与只读索引保护；修复验证不重新生成历史测量、不宣称生产优化。
- 验收标准：

  - 同一问题和快照交错运行至少两轮，记录当前模型参数、实际工具调用、阶段耗时、事实/引用/版本与失败，原始结果不可覆盖
  - 权限与发布门闩、未知实体和越权零模型调用保留；简单事实工具提示不能取消显式历史/关系/业务链的 Radar 要求
  - 性能按实际完整请求计时，内部阶段计时另列；推理预算改变按当前提供方实际支持和观测解释，不承诺只改 low 必然提速
  - 小规模开发对照不冒充未见测试集或通用语义准确率；没有跨业务复杂场景质量证据时不替换已确认默认配置
  - HTTP超时、连接失败、身份准备失败与非JSON响应保留为失败观测，计入分母和等待时间；不打印原始错误正文或凭据，后续观测继续运行
  - 评测只接收已发布且没有待处理更新任务的副本；不启动后台更新，共享Qdrant客户端限制为只读，评测管理写入接口拒绝访问，不能改动源索引

- 影响范围：

  - 代码：`scripts/evaluate_chat_latency.py`, `contextledger/evaluation/chat_latency.py`, `scripts/evaluate_radar_latency.py`, `contextledger/evaluation/radar_latency.py`
  - 测试：`tests/evaluation/test_chat_latency.py`, `tests/evaluation/test_chat_evaluation.py`, `tests/radar/test_radar_integration.py`
  - 文档：`docs/evaluation/chat-latency.md`, `docs/evaluation/chat.md`, `docs/README.md`, `docs/decisions/ADR-0004-decision-radar.md`

### 功能扩展 · 提交报告的五维实测与费用证据

- 扩展键：`submission_metrics_20261015`
- 来源：user requested freshness, permission, recall, latency and cost experiments on 2026-10-15
- 权威级别：`team_decision`（独立于基础需求）
- 状态：`validated`
- 说明：冻结952881f基线，记录新鲜度、权限、召回、单次延迟和账单费用。仅文档化已完成实验，不重跑模型、不改变在线配置。原始失败、重评分和实验范围分别保留。
- 验收标准：

  - 报告用直观表格回答更新多久可查、是否越权、召回多少、单次回答多久、实际模型费用
  - 固定受控来源与权限样例，保留失败、不可用、误放行/误拒绝和在途撤权记录
  - 公开集按三种模式顺序执行，报告 Recall@1/5/10/20 和参考证据覆盖；离线排序不冒充已接入或未见测试效果
  - 延迟与费用只使用单次请求，统计实际 provider token 和账单，包括重试和被丢弃的答案；被取消的并发与压测记录保留但不进报告
  - 英文报告保持 Handbook 场景、用户、痛点和字体；原始与修正后的自动判分分别注明

- 影响范围：

  - 代码：—
  - 测试：—
  - 文档：`docs/evaluation/submission-20261015.md`, `docs/submission/main.tex`, `docs/submission/evaluation/metrics.json`

## REQ-019 · 回答 Prompt 的管理与质量评测

- 来源：user requested recording answer prompt design on 2026-10-06
- 权威级别：`team_decision`
- 状态：`in_progress`
- 说明：将回答阶段的系统指令、原用户问题与授权证据模板、上下文预算及模型参数作为项目资产记录并管理，后续通过固定样例评估改进；安全边界沿用 REQ-009，评测框架复用 REQ-018。2026-10-07 已实施版本化 Prompt、证据不足无引用约束与一次受限格式重试，本次扩充自然表达、术语解释、分段和问题相关性要求，避免机械抄写或无关细节；完整质量和成本评测仍待完成。
- 验收标准：

  - 记录当前实际发送的系统指令、问题与证据格式、身份字段、证据截断和模型输出限制，示例不得包含真实密钥或无权限资料
  - 实际模型请求包含独立的系统指令、未经替换的原用户问题和带编号的授权检索证据，动态数据分区表达且不被提升为系统指令
  - 回答先用自然语言直接回答问题，再按需分段或列项解释相关用途、关系和必要术语；禁止整段搬运或堆砌技术名词，引用贴近所支持事实，不为生动或详细编造事实，不擅自增加未被询问的迁移等话题
  - 后续修改回答 Prompt 时保留可追踪版本与变更理由，使实验能够区分 Prompt、模型和检索证据的变化
  - 通过固定的跨来源、证据不足、引用及不可信来源指令样例比较 Prompt 版本，质量与成本评测复用 REQ-018，不把更改措辞本身当作改进证明
  - Prompt 不能替代 REQ-009 的确定性权限与引用校验；当前编号合法检查不得宣称已经验证逐句事实支持
  - 审计回答、检索规划及零证据提示模板单独记录版本、输入边界、输出格式和预算；answer-v9 移除已取消的引用复核和反馈重答上下文，保留原问题与授权证据；旧部署记录不能充当本次验证

- 影响范围：

  - 代码：`contextledger/answering/service.py`, `contextledger/answering/workflows.py`, `contextledger/application/service.py`
  - 测试：`tests/answering/test_answering.py`, `tests/answering/test_llm_workflows.py`
  - 文档：`docs/product/prompt-and-login-walkthrough.md`, `docs/product/demo-acceptance.md`, `docs/architecture/query-planning.md`, `docs/evaluation/model-selection.md`, `docs/product/workload.md`, `docs/product/llm-feature-plan.md`, `docs/architecture/decision-radar-v1.md`

## REQ-020 · 面向上游 Agent 的权限感知工具接口

- 来源：user proposed future tool on 2026-10-06; 2026-10-11 meeting recap specifies future Codex plugin direction
- 权威级别：`team_decision`
- 状态：`in_progress`
- 说明：2026-10-14 用户确认实现 MCP stdio 与可信工具 API：默认宿主模型消费授权证据，可选内部 ask 保留用户自行配置的 OpenAI-compatible API。两路复用统一服务；凭据绑定稳定用户且可撤销，不恢复浏览器登录。随后用户授权配置其 Codex 并试用：已以现有 Jax 演示员工权限经 SSH 连接 gpushare 私有网关。实际 SDK 握手、关键词/混合检索、原文与零证据，以及凭据/伪造身份/越权负例已验证；本机300项回归通过。桌面重载及真人问答待用户试用，不提升为企业认证、宿主最终答案或四来源验收。
- 验收标准：

  - 首版使用 MCP stdio 经私有 HTTP 工具 API 调用统一服务；Codex/Claude Code/WorkBuddy 提供配置示例，标准 MCP HTTP 与企业 OAuth 后续单独确认；浏览器登录不是工具接入的必要前置条件
  - 工具只接受问题与已授权范围内的检索条件，权限身份由可信运行时注入或验证，不能由模型在工具参数中任意选择 user_id、角色或来源 principal
  - 即使使用共享服务凭据，也必须保留并验证最终用户身份，不把全部请求归为拥有所有员工权限的一个服务账号
  - 工具复用统一身份权限库、Qdrant/FTS 前置过滤、证据二次校验、交付检查和审计，不建立旁路权限实现
  - 默认返回可追溯的授权证据、来源、版本和请求标识供上游模型使用；是否在工具内部再次生成回答需要明确，不强制每次工具调用重复调用模型
  - 测试同一问题对两个不同权限身份的结果、伪造身份、未验证身份、系统内撤权、原文访问和审计权限；未建立可信身份时拒绝访问
  - 不以实现 Tool 阻塞 REQ-017 当前前端验收；Tool 与前端复用服务，测试注入身份不得暴露为生产伪登录
  - 默认 search/fetch 不调用内部生成或规划模型；ask/audit 的内部生成需服务端显式启用，API 地址/Key/模型由部署者配置，模型参数不得携带凭据或任意地址
  - 工具凭据只保存哈希，绑定单一稳定身份及能力范围、有效期，调用和交付前检查撤销/停用/当前权限，不向模型提供平台凭据、管理或同步写入工具
  - Codex 试用仅开放普通员工 search/fetch；凭据可独占写入0600私有文件，启动器拒绝链接/不安全权限，不在配置或命令参数存放明文 Token；保留已有 Codex 配置及服务器权限、索引和审计

- 影响范围：

  - 代码：`contextledger/application/service.py`, `contextledger/access/identity_store.py`, `contextledger/retrieval/filtered_index.py`, `contextledger/access/tool_access.py`, `contextledger/interfaces/tool_api.py`, `contextledger/interfaces/mcp_server.py`, `scripts/mcp_private_launcher.py`, `contextledger/interfaces/private_launcher.py`, `requirements-tools.txt`
  - 测试：`tests/application/test_integration.py`, `tests/interfaces/test_tool_interfaces.py`, `tests/interfaces/test_mcp_launcher.py`
  - 文档：`docs/product/update-2026-10-11.md`, `docs/product/tool-entry-scope.md`, `docs/decisions/ADR-0003-tool-first-and-deferred-browser-login.md`, `docs/decisions/ADR-0005-source-adapters-and-mcp.md`, `docs/architecture/source-and-agent-interfaces.md`, `docs/architecture/unified-integration.md`, `docs/product/roadmap.md`, `docs/product/workload.md`, `.env.tools.example`
