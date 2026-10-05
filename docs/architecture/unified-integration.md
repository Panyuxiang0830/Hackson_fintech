# 集成版实施与验收

日期：2026-10-06。工作分支：`codex/REQ-017-unified-integration`。未经用户验收确认不合并 main。

## 已实施代码边界

- 保留 Part A 风格的 7860 页面；正式 `demo` 启动路径也进入统一服务，不再使用可任意指定 principal 的离线诊断页面。
- `web.py`：通用 OIDC，校验签名、issuer、audience、时效、state、nonce 和 PKCE；身份以 issuer/sub 对应持久化用户。无提供方配置时只显示入口，业务接口返回 401，不提供伪登录。
- `identity_store.py`：持久化账号、角色、部门、组、项目、密级、来源身份绑定、本地拒绝规则与权限版本。来源组自动解析和全面 ACL 重构没有在本轮冒充完成。
- `filtered_index.py`：Qdrant 元数据过滤、FTS 的 SQL 授权条件、候选二次校验与离线快照发布门闩。Qdrant 不保存原文，证据回到 Canonical Store 读取。
- `unified_service.py`：检索、原文、问答共用身份与权限，只把授权 Top-K 分块交给既有 AnswerService；保留引用编号校验、异常 Mock 回退。
- 模型调用前、模型返回后与 HTTP 交付检查权限版本和索引代次。期间权限变化则丢弃回答，不用旧证据再做 Mock。服务端没有可绕过鉴权的回答缓存／历史接口，HTTP 为 no-store；页面每 5 秒检查权限变化并清除展示，已交付内容无法追回。
- `audit_store.py`：SQLite 事务串行追加 SHA-256 查询审计链与本地 checkpoint，记录请求、权限／策略版本、证据版本与回答。审计查询需 admin/compliance，查询自身入链；无当前证据权限时脱敏问题、回答及证据。
- `source_permissions.py`：仅预留检查／同步接口，返回 not_enabled，不声称已经连接真实平台。不增加摄取审计模块。

## 权限模型

来源 ACL 快照允许 **且** 管理员显式绑定的来源身份有效 **且** 本地限制允许。

管理员可绑定／撤销来源身份、停用账号、管理角色与密级，增加／移除平台、项目、部门、文档或整个数据集的拒绝规则。删除本地拒绝规则不能绕过来源 ACL。管理员角色本身不获得全部文档权限。

多组来源授权初版通过多个显式来源身份的 ACL 并集表达，本地拒绝优先；来源角色／部门约束来自这些可信绑定。没有来源映射的新登录用户默认为 member、无数据权限。OrgForge 的历史查询不得恢复已离职身份的当前访问能力。

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

## 配置真实登录

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

管理员随后在页面为成员绑定来源身份。姓名、邮箱或外部 role 声明不自动提权。真实提供方尚未选定；当前完成通用实现与独立测试 issuer 验证，不声称真实提供方已配置、真实企业 ACL 已改造。

## 存储与重建

- `--out`：Part A 原文、标准化事实及可重建索引元数据。
- `--security-dir`：身份权限与查询审计，不能位于 --out 内，也不能包含 --out。
- Qdrant 数据目录：独立派生检索存储。
- Part A build 拒绝删除含身份／审计文件的输出目录。`prepare_integration_preview.py` 使用 SQLite backup 复制快照，拒绝覆盖目标，只读复用原始与 Embedding 文件。

## 人工验收顺序

1. 配置真实 OIDC，登录两个账号；新账号未绑定时无权限。
2. 管理员绑定两个来源身份，同一问题展示各自授权证据；无绑定的管理员也不能读原文。
3. 生成回答、展开引用，核对编号、来源、内容版本和时间。
4. 撤销来源身份或增加平台拒绝规则，搜索、原文、问答不能继续交付旧证据；恢复不得超出来源 ACL。
5. 模型不可用时退回确定性回答，生成期间撤权则丢弃结果。
6. 合规角色查询／导出脱敏审计，普通成员被拒绝；核对完整性和请求引用。
7. 用副本测试篡改、构建中断、快照变化，不篡改真实演示审计库。

自动测试不替代用户人工验收、真实提供方配置和 EC-010 规模／质量评测。十个工程专题仍以固定清单为准。

实际快照与运行中的 Qdrant 可使用 `scripts/verify_unified_snapshot.py --out ...` 做运维冒烟检查。测试身份与日志位于临时目录，不写入正式身份库；回答固定为 Mock，验证关键词／语义／混合检索、原文、引用和撤权，不冒充完整评测或真实登录提供方。
