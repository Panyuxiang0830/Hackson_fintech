# 集成版实施与验收

更新：2026-10-07。工作分支：`codex/REQ-017-unified-integration`。未经用户验收确认不合并 main。

用户已澄清：Tool 是后续设想，本轮仍在 Part A 前端验收集成，只延期真实浏览器登录，不取消身份权限库。现行范围见修正后的 [ADR-0003](../decisions/ADR-0003-tool-first-and-deferred-browser-login.md)。用户已确认并在分支实现独立管理员与六员工的隔离演示入口，取消登录不等于匿名开放生产业务 API。

## 已实施代码边界

- 保留 Part A 风格页面作为当前集成和人工验收入口；正式 `demo` 启动路径进入统一服务。新增显式开启的固定七账号隔离演示模式，不通过 Flask TESTING 或任意来源 principal 参数绕过权限；普通模式仍拒绝未验证身份。
- `web.py`：浏览器登录默认关闭，`/auth/login` 和 `/auth/callback` 返回 404，页面没有登录入口。保留通用 OIDC 作为延期的可选能力，只有显式开启时才使用，校验签名、issuer、audience、时效、state、nonce 和 PKCE。目前生产业务接口仍返回 401，不接受自报身份；未来 Tool 不作为解除当前前端验收缺口的前置条件。
- `identity_store.py`：持久化账号、角色、部门、组、项目、密级、来源身份绑定、本地拒绝规则与权限版本。来源组自动解析和全面 ACL 重构没有在本轮冒充完成。
- `filtered_index.py`：Qdrant 元数据过滤、FTS 的 SQL 授权条件、候选二次校验与离线快照发布门闩。Qdrant 不保存原文，证据回到 Canonical Store 读取。
- `unified_service.py`：检索、原文、问答共用身份与权限，只把授权 Top-K 分块交给既有 AnswerService；保留引用编号校验、异常 Mock 回退。
- 模型调用前、模型返回后与 HTTP 交付检查权限版本和索引代次。期间权限变化则丢弃回答，不用旧证据再做 Mock。服务端没有可绕过鉴权的回答缓存／历史接口，HTTP 为 no-store；页面每 5 秒检查权限变化并清除展示，已交付内容无法追回。
- `audit_store.py`：SQLite 事务串行追加 SHA-256 查询审计链与本地 checkpoint，记录请求、权限／策略版本、证据版本与回答。审计查询需 admin/compliance，查询自身入链；无当前证据权限时脱敏问题、回答及证据。
- `source_permissions.py`：仅预留检查／同步接口，返回 not_enabled，不声称已经连接真实平台。不增加摄取审计模块。

集成审计记录的是实际候选、过滤策略和回答，不重新遍历全库逐文档记录拒绝。旧 Streamlit 全量演示日志仍为 v0 基线；REQ-006 保持进行中，长期合规／诊断日志范围及规模验收留在 EC-009，避免把两者误写成完全相同的已完成实现。

## 权限模型

来源 ACL 快照允许 **且** 管理员显式绑定的来源身份有效 **且** 本地限制允许。

管理员可绑定／撤销来源身份、停用账号、管理角色与密级，增加／移除平台、项目、部门、文档或整个数据集的拒绝规则。删除本地拒绝规则不能绕过已绑定来源身份的 ACL；新增来源身份绑定可能扩大账号范围，必须明确确认映射依据。管理员角色本身不获得全部文档权限。离线推断 ACL 是保存在事实库中的基础授权数据，不会被身份权限库覆盖；授权代码读取两者并合成最终过滤条件。

多组来源授权初版通过多个显式来源身份的 ACL 并集表达，本地拒绝优先；来源角色／部门约束来自这些可信绑定。没有来源映射的新系统用户默认为 member、无数据权限。OrgForge 的历史查询不得恢复已离职身份的当前访问能力。

## 新鲜度最小边界

只证明索引相对已知离线快照一致，不证明真实来源最新状态或跨来源业务权威。

构建新 Qdrant collection，构建中阻断查询，完成并核对数量、来源元数据后才发布。版本、哈希、ACL、标题或元数据变化阻断该数据集并要求重建；读取再检查文档与分块哈希。失败不回退到无前置 ACL 的 RaBitQ 路径，也不静默使用旧代次。

这是保守的整快照发布，不是高可用增量同步。完整历史、回滚、删除事件、同步窗口与细粒度不中断切换仍属于 EC-001/004。废弃 collection 不自动删除，运维清理与备份须另行确认。

## 启动

现有 Part A 数据及 Embedding 模型环境已经准备时：

```bash
.venv/bin/python -m pip install -r requirements-integration.txt
# 先独立运行 Qdrant，仅监听回环地址；默认 HTTP 6335。
bash scripts/integration.sh --out runtime/part_a --security-dir runtime/security index --reuse-part-a-embeddings
bash scripts/integration.sh --out runtime/part_a --security-dir runtime/security serve --port 7860
```

没有 Embedding 缓存时去掉 `--reuse-part-a-embeddings`，使用 Part A 模型生成向量。缓存复用校验模型、维度、条数和 chunk 映射；它仍依赖原缓存可信，不把任意旧缓存当作独立正确性证明。

Qdrant 可使用 [官方安装方式](https://qdrant.tech/documentation/operations/installation/)。实现参考 [过滤语义](https://qdrant.tech/documentation/search/filtering/) 和 [payload 索引](https://qdrant.tech/documentation/manage-data/indexing/)；身份、撤权和跨库发布由应用负责，不是向量库自动提供。

## 当前入口状态

`.env.integration.example` 中 `BROWSER_LOGIN_ENABLED=false`、`DEMO_MODE=false` 是默认值。普通模式没有演示入口，业务请求仍需验证。演示模式需用新的独立安全目录执行 `demo-init`，再显式启用 `--demo` 或 `DEMO_MODE=true`；强制回环 bind、PUBLIC_URL、请求地址、Host 与写入 Origin，保留 CSRF 和业务权限检查，不能与 OIDC 混用。

用户已确认新增一个独立管理员与六个员工，复用实际搜索、问答、权限与审计服务。固定名单只用于演示会话；`/api/session` 明确显示 `identity_mode=isolated_demo`、`identity_verified=false`，审计记录也标记演示身份。任何能访问该回环端口的人都能选择管理员，不能将该模式公开部署或当作生产认证。初始化／重启不重置已撤销的绑定、本地限制或账号状态。启动与走查见 [演示验收](../product/demo-acceptance.md)。

历史配置检查（2026-10-06，已被下方 2026-10-07 部署记录替代）：当时本机有回答模型 API Key、gpushare 无 Key。仅检查 Key 是否存在，没有显示密钥；当时服务器真实模型问答未验收。

同日补充隔离冒烟检查：使用临时合成 Confluence／Jira 证据和真实本地 Qdrant 引擎，经 `UnifiedService.search`／`ask` 调用本机已配置的 `glm-5.3-flash`。实际 provider 为 `openai_compatible/glm-5.3-flash`，返回 `[1] [2]` 与授权证据对应的中文回答，回答与审计查询合计约 4.7 秒。按返回请求 ID 找到对应 answer 事件及真实 provider，哈希链有效；未绑定来源身份的管理员只能看脱敏回答。临时状态已清理，没有修改服务器权限或审计库。这不是 17860 前端人工验收，也不足以证明真实 Part A 大语料的回答质量。当前本地主测试 60 项、需求同步与 diff 检查通过。

## 可选 OIDC 历史配置（延期，不作为当前步骤）

下面仅保存已有实现的运维参考，不继续执行 Auth0 登录配置。只有后续明确要求恢复浏览器登录时才显式设置 `BROWSER_LOGIN_ENABLED=true`；旧会话或仅填写 OIDC 字段不能恢复访问。

参考 `.env.integration.example`，填到被 Git 忽略的 `.env`：

- `APP_SECRET_KEY`：至少 32 字符随机值，不用示例固定值，不发到聊天或提交 Git。
- `APP_PUBLIC_URL`：浏览器访问的固定地址。提供方登记该地址的 `/auth/callback`。
- `OIDC_ISSUER`、`OIDC_CLIENT_ID`、`OIDC_CLIENT_SECRET`：注册信息；支持公共客户端 PKCE。生产使用 HTTPS，HTTP 仅允许回环开发地址。
- `QDRANT_URL`、可选 API Key、位于数据输出目录之外的 `SECURITY_DIR`。
- `LLM_*`：沿用之前模型配置，没有 Key 时确定性模式可用。

登录后 `/api/session` 显示自己的稳定 issuer/sub。首次管理员由可信运维设置，前端不能自行注册管理员：

```bash
bash scripts/integration.sh --out runtime/part_a --security-dir runtime/security user \
  --issuer '你的真实 issuer' --subject '验证后的 sub' --name '管理员' --role admin
```

此可选模式中管理员随后可在页面为成员绑定来源身份。姓名、邮箱或外部 role 声明不自动提权。用户曾选择 Auth0 与独立显示名“ContextLedger 管理员”，Auth0 应用已创建但未配置回调、未读取密钥或接入服务器；随后明确延期浏览器登录。管理员真实身份绑定未执行，不能声称真实企业 ACL 已改造。

## 存储与重建

- `--out`：Part A 原文、标准化事实及可重建索引元数据。
- `--security-dir`：身份权限与查询审计，不能位于 --out 内，也不能包含 --out。
- Qdrant 数据目录：独立派生检索存储。
- Part A build 拒绝删除含身份／审计文件的输出目录。`prepare_integration_preview.py` 使用 SQLite backup 复制快照，拒绝覆盖目标，通过链接复用原始与 Embedding 文件；迁移以只读模式打开向量和行映射。链接本身不是文件系统写保护，预览目录只用于集成查询／迁移，不能通过它运行 Part A 原始导入／向量重建命令，否则可能改到共享来源文件。

## 人工验收顺序

当前实际回答 Prompt、独立系统管理员与更新后的验收范围见 [Prompt 与身份人工走查](../product/prompt-and-login-walkthrough.md)。管理员不是数据集里的员工，默认没有业务资料权限。

1. 不配置 Auth0，不等待 Tool；在明确标记的隔离演示模式下选择固定账号验收，非演示的未验证生产请求仍被拒绝。
2. 六个员工绑定不同来源身份，同一问题验证各自授权证据；独立演示管理员做撤权。无绑定的管理员也不能读原文，演示选择身份不代表生产鉴权已完成。
3. 生成回答、展开引用，核对编号、来源、内容版本和时间。
4. 撤销来源身份或增加平台拒绝规则，搜索、原文、问答不能继续交付旧证据；恢复不得超出来源 ACL。
5. 模型不可用时退回确定性回答，生成期间撤权则丢弃结果。
6. 合规角色查询／导出脱敏审计，普通成员被拒绝；核对完整性和请求引用。
7. 用副本测试篡改、构建中断、快照变化，不篡改真实演示审计库。

自动测试不替代用户人工验收及 EC-010 规模／质量评测。十个工程专题仍以固定清单为准。隔离演示入口已实现，用户人工走查待完成；未来 Tool 单独讨论。

实际快照与运行中的 Qdrant 可使用 `scripts/verify_unified_snapshot.py --out ...` 做运维冒烟检查。测试身份与日志位于临时目录，不写入正式身份库；回答固定为 Mock，验证关键词／语义／混合检索、原文、引用和撤权，不冒充完整评测或真实登录提供方。

## gpushare 独立预览验收记录（2026-10-06）

以下是旧版服务器预览记录；登录停用与七账号演示入口的当前部署状态以紧随其后的 2026-10-07 记录为准。

- 分支代码：`/home/research_pyx/Hackson_fintech-integration`；原 main 代码和 7860 服务未替换。
- 新数据、Qdrant、独立环境与安全状态：`/hy-tmp/data_pyx/contextledger-integration/`，分别放在 `content/`、`qdrant/`、`venv/`、`security/`。原 Part A 的 Raw／Embedding／模型缓存只复用、不重新下载；Canonical Store 使用独立副本。
- Qdrant 1.19.1 只监听服务器回环 6335／6336，发布 45,565 份文档的 293,096 个分块；包含 5 个数据集。这不是全量质量或延迟基准。
- 本地和服务器主测试各 56 项通过（含共享向量行映射只读迁移测试）；服务器 Part A 解析／来源权限测试 8 项通过，需求同步检查通过。
- 实际 Qdrant 和实际 MiniLM Embedding 的隔离冒烟样例：`orgforge:Jax` / `TitanDB`，关键词、语义、混合各返回 8 条授权候选，确定性回答包含 5 条证据；撤权后所有检索无结果、原文不可读、问答证据不足，审计链有效。
- 提供方尚未配置，预览页面显示“OIDC 尚未配置”，业务接口返回 401。协议测试使用独立测试 issuer，不是线上模拟登录。
- 前端开发预览在服务器 17860，经本机 SSH 转发访问 `http://127.0.0.1:17860/`；原 7860 保留。转发需要 SSH 会话存活，Flask 开发服务不作为生产部署。
- 新运行目录当次占用约 2.6 GB；其中事实副本约 1.4 GB、Qdrant 约 1 GB、独立环境约 150 MB，索引优化／日志仍可能增长。共享缓存未计作新增空间。

服务器已缓存模型时，设置 `HF_HUB_OFFLINE=1`、`TRANSFORMERS_OFFLINE=1`，避免查询启动时到 Hugging Face 检查更新；这只影响本地 Embedding，不禁用 OIDC 或问答模型 API。

## gpushare 七账号演示部署与自动走查（2026-10-07）

- 集成工作分支已同步到 `/home/research_pyx/Hackson_fintech-integration`，17860 使用七账号隔离演示入口；main 和原 7860 服务保持不变。未合并 main，用户人工验收待完成。
- 独立状态为 `/hy-tmp/data_pyx/contextledger-integration/security-demo/`；旧 `security/` 未替换。管理员默认无来源绑定，六个员工绑定 orgforge 各自来源身份，名单见演示验收文档。
- 模型与演示配置通过 SSH 白名单同步至 `preview-demo.env`（0600），应用 Secret 独立生成，未复制 Auth0 配置、未打印或提交密钥。进程通过 `CONTEXTLEDGER_ENV_FILE` 加载该运行时文件。
- 修复初次语义／混合检索失败：显式指定 `HF_HOME=/hy-tmp/data_pyx/contextledger-part-a/hf-cache` 复用既有 MiniLM 缓存；未下载模型、未重建 Qdrant。索引仍为 45,565 文档／293,096 分块。
- 本机及服务器各 71 项主测试、需求同步和 diff 检查通过。演示服务使用非 TESTING 配置；真实页面经 SSH 回环转发访问。
- 页面走查 `TitanDB`：Jax 得到 8 条授权混合检索证据，并成功打开技术文档原文；Ariana 的同问题结果为不同的 Slack 证据，未交付 Jax 的工程 Confluence 结果。
- Jax 的“TitanDB 当前有哪些进展和问题”实际调用 `openai_compatible/glm-5.3-flash`，请求 `8c91194a-3042-40b9-b171-e236cea9cb4a`。模型因召回主要为标题／索引片段而拒答。真实 API 链路通过，不代表此问题回答质量通过；分块与排序质量留待 REQ-018/EC-010 评测，未擅自扩大本轮实现。
- 基础问题 `What is TitanDB and what is it used for? 请用中文依据证据回答。` 得到中文实质回答及 `[1]` 至 `[5]` 引用，provider 为真实 GLM，请求 `0d6a91b1-6285-4d2a-b412-fb4920ab6a25`；证据来自当前授权 Confluence 分块。引用编号与授权校验通过，不代表已完成逐句语义验证或总体质量评测。
- 管理员在页面按该请求 ID 找到 answer 事件，provider、权限版本、`identity_mode=isolated_demo` 一致，`integrity.valid=true`；回答和证据因管理员无业务权限而脱敏。
- 管理员在页面仅对 Jax 添加 Slack 平台拒绝，Jax 权限版本从 3 升为 4，同一查询的 8 条结果不再包含 Slack，Ariana 仍有 Slack 结果。随后移除这条测试拒绝，Jax 版本升为 5、限制列表为空；撤权与恢复分别记录为 permission_change 事件，哈希链有效。没有重置其他用户状态。

上述为 Agent 自动走查，不替代用户验收或生产认证／规模评测。新鲜度仍只校验已知离线快照。服务和 SSH 转发须存活，当前 Flask 开发预览不是生产部署。
