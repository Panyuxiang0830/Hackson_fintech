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

本轮新增隔离回归覆盖：原内容哈希变动/未知ID/重复ID拒绝，Slack身份范围不得扩大，标注来源不能冒充已验证源权限，密级/项目/部门在SQL与Qdrant中生效，原文拒绝、幂等与白名单外文档保持不变。服务器应用和真实模型结果在完成后补充。
