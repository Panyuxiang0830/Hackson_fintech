# 资料范围权限与演示验收

2026-10-15，REQ-016 / resource_access_controls，团队决定。保留现有导入 ACL，以 OrgForge 为主要演示数据集。

## 行为

- 数据集目录依据账号已有的来源身份映射（包括已撤销映射）显示；撤销内容读取权不再隐藏入口。目录可见不授予检索或原文权限；没有映射的其他数据集仍不显示。
- Security Lens 按员工、数据集选择，分别允许或阻止 Slack、Jira、Confluence 等实际来源；总开关仅添加/删除数据集读取拒绝规则，不拆除身份映射。
- 可输入 Evidence Passport 的文档 ID 单独阻止读取，也可恢复该本地规则。来源 ACL、父资源、其他限制和密级继续生效。允许某来源不代表该来源全部文档可读。
- 已撤销的映射不在重启时恢复。界面只列出该员工已存在的映射，并提供明确的“Restore this mapped identity”操作；不再把其他员工身份作为日常授权选项。恢复映射后若仍有读取限制，需要分别处理。
- 来源数量是允许的来源类别数，不是证据数量或对全库权限的统计。未知、无匹配和无读取权均采用当前权限范围内无可用证据的安全提示，不暴露受限内容存在与否。
- 管理入口使用同一后端权限库和既有审计；每次变更增加权限版本。原文、FTS、Qdrant、模型输入和交付沿用当前权限检查；前端刷新权限版本后清除旧业务内容。

## 人工重试

1. 刷新既有演示入口，选择 ContextLedger Administrator，进入 Manage Permissions。
2. 选择 Jax 和 orgforge；若映射已撤销，明确点击 Restore this mapped identity。
3. 在 Allow dataset reading 开启时选择允许的来源（如 Slack、Jira、Confluence），再点击 Run employee query again。
4. 只关闭 Jira，重新查询，检查其余来源仍可用，Jira 原文不可打开。
5. 关闭 Allow dataset reading，员工仍可选择 orgforge，相同问题返回空证据和安全提示，旧原文不可打开。
6. 恢复总开关，之前选定的来源限制保留；需要恢复的来源分别勾选。结合审计事件验证。

## 验证记录

- 实现提交 `be69fa23` 已部署到 gpushare `/hy-tmp/data_pyx/contextledger-integration/releases/resource-permissions-20261015`，仍使用回环17866和原有 SSH 转发入口。没有合并 main。
- 本地：unittest 373项通过；pytest 381项、149个subtests通过；需求同步和两份前端JS语法检查通过。
- 浏览器受控夹具：关闭Jira后只返回Confluence证据；关闭整个数据集读取后返回零证据、安全提示；返回问题表单仍可选择数据集。服务器浏览器已确认Jax、OrgForge及当前权限版本13。
- 真实OrgForge索引、复制权限/审计的隔离验证：初始TitanDB Top-K为Confluence；禁止Confluence后返回5条Slack证据；单文档阻止/恢复及旧原文拒绝通过；整库撤权返回0证据、0模型调用；恢复后provider为`openai_compatible/glm-5.3-flash`且decision为answered，审计链有效。这些临时变更不写入当前演示权限库。
- 当前演示HTTP验证：Jax仍为版本13、原映射保持撤销，`/api/corpora`包含orgforge；相同问题返回insufficient、0证据、0模型调用。请求ID `4a012ad0-4b56-4459-8e1b-0c730d22c44c`。
- 切换前使用SQLite backup保存身份库和审计库。切换后逐项比较账号状态、权限版本、绑定和本地限制，与切换前完全一致；保留原始数据、向量索引、七账号和审计记录。
- 服务器原服务环境缺可选MCP SDK，全量检查最初有2项依赖失败；在独立test-deps目录补齐SDK并建立测试解释器，不更改在线服务venv。最终在该隔离测试解释器下：unittest 373项全部通过，pytest 381项和149个subtests全部通过。

原地址刷新即可重试。Jax当前保持撤权；若要先展示正常读取，管理员需明确恢复其已有`orgforge:Jax`映射，再选择读取范围。没有恢复Alex映射或新增跨员工绑定。
