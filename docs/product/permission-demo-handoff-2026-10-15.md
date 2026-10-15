# 权限改进与 OrgForge 演示交接（2026-10-15）

本记录对应用户因五小时额度将尽而要求暂停并总结的时点。恢复工作时先核对 Git、服务进程和数据库；以下是交接时的实测状态，不是后续部署保证。

> **2026-10-16 更新：第8节步骤1–8的技术部分已完成。** 线上已切换至 `curated-demo-permissions-20261015`（提交 `ca0886b2`，PID 775226），4份标注已应用，真实GLM验收、撤权/密级/部门对照、浏览器 Security Lens/Passport 及服务器完整测试均通过；详见 [curated-demo-permissions.md](curated-demo-permissions.md) 的"服务器部署与真实验收"。下文第1节及之后保留交接时的原状态描述。仍待：用户人工验收；是否修复"点名编号时Jira正文无自身编号而不被检索"的既有检索问题；未经同意不合并main。部署使用复制的 `BASE/contextledger_curated_logo_deploy.py`（仅改预期提交号与备份目录名）。

> **后续自然问法更新：** 线上已进一步切至 `releases/natural-question-20261016`（26d9a0d0，PID783815），修复英文短回答格式误拒并完成不带编号问题的撤权前后验证；见 [自然问法验证](natural-question-validation-20261016.md)。旧交接状态仅作历史记录。

> **最新项目管理更新：** 已部署可搜索项目卡片与显式项目成员规则，原SwiftUI之外新增五个项目，14份资料已标注；当前58ffc6ef / PID789262，详情见[项目权限](project-permissions.md)。此前demo项目勾选界面已被替换。

## 1. 最重要的当前状态

- **线上仍是基础权限修复版**：`resource-permissions-20261015`，提交 `be69fa23`，PID `754260`。撤权后数据库保持可选、后端控制读取等已部署。
- **新一轮四份演示资料标注及项目/密级界面尚未上线**。代码已完成并提交，服务器新 release 已准备；没有切换进程，也没有执行 `--apply`。
- 交接时只读检查：`manual_demo` 标注数 **0**，无待执行文档更新；Jax 密级1、权限版本13、自己的 `orgforge:Jax` 绑定禁用；Alex 密级1、版本3；没有本地拒绝规则。
- 因而现在直接用 Jax 提问仍应无证据。不能把新方案的本地测试当成实际演示已经成功。
- 没有创建 PR，也没有合并 main。接续工作留在工作分支。

## 2. 用户已确认的要求与边界

1. 明天交付，保留现有数据导入 ACL，展示以 OrgForge 为主，不重做整套智能 ACL 推断。
2. 员工所属数据库即使撤权仍可选择；真正限制在服务端检索、原文和答案交付执行。无可用证据时安全返回，不调用回答模型。
3. 管理员可给予或撤销具体读取范围；来源开关可控制 Slack/Jira/Confluence，Slack 本轮无需增加更复杂的管理交互。
4. 企业权限解析不必经过模型。真实企业的项目、部门、密级、平台原生权限和文件系统权限都可作为确定性输入。
5. 为未来设计多种权限接入接口，写进设计及报告，但不要求现在接入真实公司数据。
6. 当前演示只标注实际提问所需资料，其他数据不处理。人工标注必须如实标明，不能冒充自动同步的企业权限。
7. 不伪造固定回答、不改写用户问题、不放宽服务端校验、不把员工改绑到别人的身份。

需求台账：`project/requirements.json` 中 **REQ-016 / resource_access_controls** 为 `in_progress`（基础已部署，定向演示扩展待部署验收）；**REQ-003 / permission_provider_contract_v2** 为 `planned`。均为 `team_decision`，不是官方硬性要求。`docs/requirements.md` 由同步脚本生成。

## 3. 仓库、分支与提交

实际工作目录：

```text
/Users/panyuxiang/.codex/worktrees/resource-permissions/hackson
```

不要覆盖 Desktop 原 checkout：`/Users/panyuxiang/Desktop/hackson` 有其他演示/报告工作。当前新代码在上面的独立工作树。

当前分支：`codex/REQ-016-curated-demo-permissions`。交接前业务代码 HEAD：`f969020277407f19eda206f1994c2ef76ad17b02`，本交接文档随后另作 docs 提交。

| 提交 | 内容 | 上线状态 |
| --- | --- | --- |
| `be69fa23` | 数据集保持可选、来源/文档读取限制、自己的绑定恢复 | 已部署 |
| `5607c8c2` | 基础权限部署与验证记录 | 文档 |
| `fd7def14` | 五模式权限接口设计及 Proposed ADR | 仅设计 |
| `5e286d41` | 四份定向资料的标注工具、项目/密级界面、回归测试 | 未部署 |
| `f9690202` | 同密级部门对照：Jax/Backend 允许，Alex/Mobile 拒绝 | 未应用 |

历史分支 `codex/REQ-016-resource-permissions` 和 `codex/REQ-003-permission-interface-design` 已推送；接续从当前分支继续。推送结果以本次交接回复及 `git status -sb` 为准。

## 4. 代码与文档位置（相对上述工作目录）

| 路径 | 职责/接续关注点 |
| --- | --- |
| `contextledger/access/acl.py` | 现有导入 ACL：来源、部门频道、私聊参与者等规则；本轮不重写 |
| `contextledger/access/identity_store.py` | 员工当前身份、密级、绑定、来源/项目/文档拒绝规则及权限版本 |
| `contextledger/retrieval/filtered_index.py` | SQL/向量权限过滤、候选与原文复核；核对项目/部门/密级在真实数据上生效 |
| `contextledger/answering/service.py` | 当前权限下回答交付；零证据安全返回及模型调用边界 |
| `contextledger/access/demo_permissions.py` | `plan_annotations`：只接受显式文档白名单、固定内容哈希；生成既有队列更新体；拒绝扩大 Slack ACL |
| `config/demo-permissions.example.json` | 唯一待应用的4份演示资源清单、原文哈希、项目/部门/密级与演示账号 |
| `scripts/apply_demo_permissions.py` | 默认只预检；`--apply` 才提交真实管理接口队列；备份、幂等、白名单外文档摘要校验 |
| `contextledger/storage/document_updates.py` | 接受严格的 `permission_annotation` 人工标注，保留版本/审计并更新索引；不可冒充来源已验证权限 |
| `contextledger/interfaces/web.py` | 数据库目录及管理接口；`/api/admin/content-scopes` 为已标注资料返回 `attribute_controls` |
| `contextledger/interfaces/static/stitch/app.js` | Security Lens 项目开关/员工密级，Passport 人工策略展示；权限变化时清空旧内容 |
| `contextledger/interfaces/static/stitch/index.html` | 新管理控件与明确包含 ENG-195/PR-135 的演示问题；JS 缓存版本 v9 |
| `tests/access/test_demo_permissions.py` | 白名单、哈希、Slack ACL、幂等、真实 Qdrant 过滤、部门/密级/项目与原文拒绝 |
| `tests/interfaces/test_stitch_frontend.py` | 新界面控件约定 |
| `tests/interfaces/test_stitch_api.py`、`tests/answering/test_answering.py` | 基础管理接口及回答授权回归 |
| `docs/product/resource-permissions.md` | 已上线基础权限行为与验证 |
| `docs/product/curated-demo-permissions.md` | 本轮4份资料、演示步骤和应用方法 |
| `docs/architecture/permission-interfaces-v2.md` | 多模式接口完整设计、限制、验收矩阵与中英文报告草稿 |
| `docs/decisions/ADR-0007-permission-provider-contract.md` | Proposed，不能写成已完成的生产接入 |

## 5. 演示资料和预期行为

实际问题来自本项目 `demo` 对话（thread `01a13deb-c87e-7870-a938-aed571abc93a`）。演示使用 **Jax / orgforge / Query planning Off**：

1. `What can I monitor in the ENG-195 SwiftUI telemetry health dashboard?`
2. `What changed during the ENG-195 / PR-135 SwiftUI telemetry dashboard review, and has it been released yet?`
3. `Which parts of the ENG-195 / PR-135 outcome remain unconfirmed?`

显式资源只有以下4份，原内容 SHA-256 见配置，不做模糊批量标注：

```text
ENG-195
slack_engineering_2026-02-17T09:37:07
slack_engineering_2026-02-18T09:38:43
slack_dm_miki_raj_2026-02-17T15:09:55.860671
```

- 标为 `demo:swiftui-telemetry`、`confidential`（2），人工归类部门 `Engineering_Mobile`，**允许读取部门 `Engineering_Backend`**。归属部门与允许部门是两个字段；此设定服务于明确的部门拒绝对照。
- Jax：Backend，恢复其原有自身绑定，密级升至2。只对 Jira `ENG-195` 明确添加 Jax 读取权；旧 ACL 保存在版本历史，当前依据标为管理员调整。
- 两份公开工程 Slack 不扩大原 ACL；Miki/Raj 私聊只加策略元数据，**Jax 仍不能读**。
- Alex：Mobile，保留自身绑定，密级同样2；即使原来源 ACL 允许，部门不匹配仍拒绝。这样对照不混入密级差异。
- 不设置员工覆盖全语料的 `projects` 白名单。项目开关使用既有项目拒绝规则，避免隐藏其他未标注资料。
- `CONF-ENG-195` 与 Jira `ENG-195` 不是同一份资料；CloudWatch `ENG-218 / PR-144` 是另一条案例，均不纳入本轮。

预期演示：Jax 正常问答 → 撤销该项目 → 同题无相关证据、旧原文不可读但数据库仍可选 → 恢复项目 → 密级降到 Internal(1)同样拒绝 → 恢复2 → Alex 同密级因部门拒绝。无论项目还是密级撤销，底层原始 ACL 仍需通过。

## 6. 多模式接口方案的交付边界

设计包含 `snapshot_acl`（现有快照）、`native_acl`（原生平台）、`attribute_policy`（项目/部门/密级）、`posix_acl`（rwx/UID/GID/ACL）、`external_pdp`（外部策略决策）五种模式。

不要求模型判权限。可信身份/元数据确定性映射；主要权限依据与强制附加约束取交集，未知或不支持情况保守拒绝；检索前必须有可执行过滤，不能先把未授权内容交给模型。POSIX 要考虑目录逐级 x、ACL mask 和真实用户身份，不能拿采集器/root 的读取权代替员工权限。外部 PDP 不能只在检索后逐篇过滤。

仓库已有部分原生平台适配，但 v2 统一契约、新 POSIX/PDP 接入与真实企业全量验证仍是设计/待办。报告可描述扩展方案和本轮人工权限演示，不能声称已经接通这些企业系统或完成自动实时 ACL 同步。

## 7. 服务器位置与恢复入口

```text
SSH: gpushare
BASE=/hy-tmp/data_pyx/contextledger-integration
正在运行: BASE/releases/resource-permissions-20261015
已备好未运行: BASE/releases/curated-demo-permissions-20261015（f9690202）
服务解释器: BASE/venv/bin/python
独立测试解释器: BASE/test-deps/permissions-venv/bin/python
运行数据: BASE/previews/aspire-ui-20261015
  content/canonical.sqlite
  security/identities.sqlite
  security/audit.sqlite
  security/demo-roster.json
  model.env
  server.pid
Qdrant: http://127.0.0.1:6335
演示入口: http://127.0.0.1:17866（已有本地SSH转发）
```

`BASE` 在这里是路径缩写，执行时需先设置或展开。`model.env` 含敏感配置，不打印、不提交。实际模型配置为 `openai_compatible / glm-5.3-flash`，接续时仍须检查真实调用结果。

以下操作脚本已放到服务器，**未运行**，且未作为业务源码纳入 Git；运行前阅读并核对当前 PID、路径和预期提交：

- `BASE/contextledger_curated_deploy.py`：代码切换；先备份身份/审计，旧服务失败可回退；不应用标注。
- `BASE/contextledger_verify_curated_demo.py`：应用后的真实 HTTP/模型验收与撤权对照；输出 `previews/aspire-ui-20261015/demo-permission-annotations/verification.json`。
- bundle：`BASE/contextledger-curated-demo.bundle`，本地 `/tmp/contextledger-curated-demo.bundle`。

旧基础部署备份：`BASE/previews/aspire-ui-20261015/backups/before-resource-permissions-20261015T133833Z`。不要误运行旧的部署脚本，其 PID/路径前提属于上次部署。

## 8. 尚需完成的工作（按顺序）

1. 重新检查服务/源码、未完成更新任务、Jax/Alex 状态；阅读部署与验收脚本。用户此次仅要求交接，因此本轮不继续部署。
2. 在新 release 对最终配置重新执行默认预检。此前初版预检通过，最终同密级部门对照配置更新后尚未再次预检。
3. 切换至 `curated-demo-permissions-20261015`，确认健康检查及静态资源 v9、原有身份/限制未被代码切换改变。
4. 用下面同一命令加 `--apply` 应用4份资料，经既有队列完成版本/分块/向量发布；不得直接随意 SQL 改 ACL 或批量重建全语料。

```bash
cd /hy-tmp/data_pyx/contextledger-integration/releases/curated-demo-permissions-20261015
/hy-tmp/data_pyx/contextledger-integration/venv/bin/python scripts/apply_demo_permissions.py \
  --out /hy-tmp/data_pyx/contextledger-integration/previews/aspire-ui-20261015/content \
  --security-dir /hy-tmp/data_pyx/contextledger-integration/previews/aspire-ui-20261015/security \
  --manifest config/demo-permissions.example.json \
  --url http://127.0.0.1:17866
# 默认仅预检；确认预检结果后在上述命令末尾添加 --apply 才会写入。
```

5. 检查 `demo-permission-annotations/applied.json`、实际队列状态、4份新版本和备份目录。工具逐篇提交，不是整批原子事务；失败需根据已记录任务/备份恢复，不能假设全部没生效或重置审计库。
6. 运行真实验收：3题实际 GLM 回答与引用、私聊不可读；项目撤权及密级降低后 keyword/vector/hybrid 均无目标证据、零证据不调模型、旧原文拒绝、数据库仍可选；Alex 同密级部门拒绝；恢复 Jax 至项目允许/密级2。不相关资料检索及白名单外内容摘要应保持一致。
7. 检查真实浏览器 Security Lens 和 Passport；模型答案仍需阅读，尤其“合并/评审”不能无依据写成“已经发布”。实际答案质量尚未在新标注下验收。
8. 补充服务器完整 pytest，更新验证文档/CHANGELOG/台账，准确区分技术验收与用户人工验收。用户明确同意前不合并 main。

## 9. 已有验证证据与限制

- 本地业务代码完整回归：**377 unittest 通过；385 pytest + 155 subtests 通过**；项目同步检查、JS 语法和 diff 检查通过。
- 服务器新 release 在 `5e286d41` 运行 **377 unittest 通过**，日志 `previews/aspire-ui-20261015/demo-annotation-unittest.log`。后续 `f9690202` 改的是对照配置、操作脚本及说明，尚需最终预检和真实验收。
- 新管理控件、项目/密级保存及 Passport 已在隔离合成数据浏览器检查，不代表真实 OrgForge 新版本上线验收。
- 服务 venv 缺可选 MCP SDK；完整测试用上面独立测试解释器，不向服务 venv 随意安装依赖。仅 PYTHONPATH 可能无法满足测试里的子进程解释器要求。
- 旧线上版曾实测 Jax 撤权后 OrgForge 可选、零证据且零回答模型调用；新4份资料流程尚未执行。
- 现有 OrgForge 4,086份资料原本 project 均空、密级均为1，部门字段只有部分非空。因此不能对外声称全数据集已经配置好项目/密级/部门策略。

正常完成检查（在工作树）：

```bash
/Users/panyuxiang/Desktop/hackson/.venv/bin/python scripts/project_sync.py --check
/Users/panyuxiang/Desktop/hackson/.venv/bin/python -m unittest discover -s tests -v
```

本次只是补充交接文档，无新增业务代码；不因整理文档重复整套测试。接续若修改业务代码，应运行相应回归及项目约定的完成检查。
