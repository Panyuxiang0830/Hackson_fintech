# 指定演示资源的人工权限配置

日期：2026-10-15；REQ-016/resource_access_controls。用户确认只为实际演示问题相关资料配置权限，其他数据不处理。

## 固定问题与资源

1. What can I monitor in the ENG-195 SwiftUI telemetry health dashboard?
2. What changed during the ENG-195 / PR-135 SwiftUI telemetry dashboard review, and has it been released yet?
3. Which parts of the ENG-195 / PR-135 outcome remain unconfirmed?

问题指定ENG-195和PR-135，避免与ENG-218/PR-144的CloudWatch面板混淆。不重写用户实际提交的问题，不缓存固定答案或插入回答材料。

配置清单：[config/demo-permissions.example.json](../../config/demo-permissions.example.json)。只有4份资源：ENG-195、两份PR-135评审/合并Slack记录、一个Miki/Raj私聊。筛选不把CONF-ENG-195误认为ENG-195，也不把其他仅提及SwiftUI或telemetry的Firebase/销售/设计资料收入此场景。

- 人工演示项目：`demo:swiftui-telemetry`。
- 人工归类部门：`Engineering_Mobile`。
- 允许部门：`Engineering_Backend`；这是人工演示策略，不是声称原始资料天然仅归后端读取。
- 资料密级：`confidential`，员工上限至少2。
- 新字段`permission_annotation`明确标为`manual_demo`和`team_decision`；这是演示策略，不是原平台权限自动同步或模型判断。
- Slack原始人员ACL保持不变，私聊不给Jax新增访问权。只对ENG-195显式添加Jax作为本次获准演示的读取者；旧ACL及来源依据进入既有文档版本历史，当前ACL依据标为管理员调整。
- Jax仅恢复原本的`orgforge:Jax`映射并设密级上限2；Alex保留自己的映射并设同样的密级上限2，作为来源ACL允许但部门不匹配的对照，不增加其他人的身份映射，不给其配置覆盖全语料的项目白名单。

## 执行与检查

`python scripts/apply_demo_permissions.py --out CONTENT --security-dir SECURITY --manifest config/demo-permissions.example.json --url http://127.0.0.1:17866`

默认只预检；显式添加`--apply`后通过当前隔离Demo管理接口提交现有文档更新队列。工具仅接受回环隔离Demo，按4个显式ID和原文SHA-256检查，不做模糊批量匹配。保留正文，只发布这些资料的权限元数据/必要ACL调整与索引分块；保留文档历史、审计和权限版本。

操作前备份选定文档和身份/审计库。执行前后计算白名单之外所有文档（含正文、ACL和元数据）的摘要，要求完全相同。重复执行相同配置不重复发布文档。原文变动则要求重新审核清单。

## 演示操作

1. Jax / orgforge / Query planning Off，先问上述问题，检查真实模型、证据和Passport。
2. Passport显示Manually configured demo policy、项目、密级和允许部门。
3. 管理员进入Security Lens选Jax，可取消SwiftUI项目访问；切回员工同题重问，相关项目证据和旧原文不可交付。
4. 恢复项目，再将员工密级从Confidential降为Internal；同题重问验证confidential资料被过滤；恢复后可再次回答。
5. 部门由员工的真实来源身份与当前部门参与检查，页面显示该员工部门和允许部门。Jax的后端部门匹配，Alex的移动部门不匹配；两者均为Confidential上限，切换到Alex可观察部门拒绝，再切回Jax。不通过把Jax随意改绑成别人的身份演示。
6. 原来的来源开关和整库读取开关继续可用，撤权不隐藏orgforge入口。

项目开关是现有本地项目拒绝规则，不宣称已经接通企业项目成员目录或权限接口v2。未标注的其他文档保留现有ACL/属性行为；同一来源不相关资料不因本次项目撤权被批量改写。

## 验证状态

本轮新增隔离回归覆盖：原内容哈希变动/未知ID/重复ID拒绝，Slack身份范围不得扩大，标注来源不能冒充已验证源权限，密级/项目/部门在SQL与Qdrant中生效，原文拒绝、幂等与白名单外文档保持不变。

### 2026-10-16 服务器部署与真实验收（技术验收）

- 部署：gpushare 17866 切换至 `releases/curated-demo-permissions-20261015`，提交 `ca0886b2`（f9690202 之后只增加交接文档与侧栏 logo），PID 775226。切换前备份 `backups/before-curated-demo-20261015T160124Z`；切换前后身份、绑定、拒绝规则一致。
- 最终配置重新预检通过后执行 `--apply`：4个队列任务均为 ready，`applied.json` 记录 `other_documents_unchanged: true`，标注前备份在 `demo-permission-annotations/backup-1792080117613224150`。数据库只读核对：只有这4份 `project=demo:swiftui-telemetry`、classification=2；私聊ACL仍仅Miki/Raj，两份公开Slack ACL未扩大；ENG-195 当前依据为管理员调整、旧版本可追溯。Jax：Backend、密级2、自身绑定启用；Alex：Mobile、密级2。
- 真实验收（`verification.json`，`openai_compatible/glm-5.3-flash`）：3题均为 answered，引用只来自白名单资料；第2题明确说明已合并不等于已发布，发布状态未知。私聊原文对Jax返回404。
- 撤销项目、密级降为Internal：keyword/vector/hybrid 均无证据，零证据不调用模型（attempts=0），ENG-195原文404，orgforge仍可选，无关TitanDB检索不变。Alex同为Confidential，部门不匹配检索为空。结束时Jax恢复项目允许、密级2，审计哈希链校验通过，权限版本19。
- 浏览器（经本地SSH转发）：Security Lens 显示Jax的项目开关、员工密级、部门与允许部门；Passport 显示 `Manually configured demo policy · SwiftUI telemetry dashboard (demo) · confidential · Eligible departments: Engineering_Backend`。

已知限制：3题证据均为两条PR-135 Slack记录，Jira ENG-195本身未被引用。原因是既有检索在问题点名编号时只保留标题或正文含该编号的文档，而该Jira正文只有标题、未写自身编号；用标题文字检索时Jax可以命中，说明不是权限问题。因此第1题只能看到被截断的"latency and p..."并如实说明无法确认后续指标。本轮未修改检索规则。

- 服务器完整测试（独立测试解释器，`ca0886b2`）：385 pytest + 156 subtests 通过，377 unittest 通过；日志 `previews/aspire-ui-20261015/curated-demo-pytest.log`、`curated-demo-unittest.log`。

以上为技术验收，不代表用户人工验收；未合并main。

### 2026-10-16 再次逐题复测

3道带ENG-195/PR-135的问题在默认hybrid均有证据，所有检索命中和真实GLM引用均为已标注资料。分别项目撤权/降低密级后，3题×3模式均零证据，回答模型attempts为0，4份原文404、orgforge仍可选、无关TitanDB结果不变；同密级Alex部门拒绝。结束恢复Jax项目允许/密级2，版本25，审计链有效。

第三题纯vector未命中，keyword/hybrid正常；旧宽泛问题会召回其他保留原ACL的资料，不应拿它演示定向项目全部拒绝。录制操作与请求ID见 [3D流程](security-lens-demo-3d.md)。本轮无业务代码或数据标注修改。

### 自然问法录制更新

用户要求不在演示问题中输入工单/PR编号；已完成自然问法的真实回答、项目撤权后零证据/零模型调用及恢复后再次回答验证。修复英文短回答被200字符分段阈值误拒，详见 [自然问法验证](natural-question-validation-20261016.md)；当前3D操作与实际原句见 [录制流程](security-lens-demo-3d.md)。既有4份权限标注和原始ACL保持不变。
