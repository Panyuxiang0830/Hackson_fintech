# 3D：Security Lens——撤权前后对照（约60秒）

2026-10-16；REQ-016/resource_access_controls。线上17866实际复测通过，用户人工录制待完成。

## 录制前准备

- 页面刷新至当前版本。身份 Jax，dataset `orgforge`，Query planning Off，默认混合检索。
- Jax 当前为 Engineering_Backend、Confidential(2)，自身绑定启用、SwiftUI项目允许；本轮复测结束权限版本25。
- 先提交下方问题，等真实回答完成再开始录制。等待模型的时间可以剪短。
- 本段演示项目撤权。保留来源开关和 Allow dataset reading，不删除员工绑定。

```text
What changed during the ENG-195 / PR-135 SwiftUI telemetry dashboard review, and has it been released yet?
```

## 操作与时间

| 成片时间 | 操作与应见结果 |
| --- | --- |
| 0–10秒 | 展示 Jax 的正常回答及编号引用。可承接3C，关闭Passport回到回答。 |
| 10–20秒 | 顶部 Current identity 切为 ContextLedger Administrator；左侧 Manage Permissions 进入 Security Lens；Selected employee 选 Jax，Dataset 选 orgforge。 |
| 20–35秒 | 找到 Configured demo permissions，取消 `Read project: SwiftUI telemetry dashboard (demo)`。自动保存，无额外提交。展示 Before 的 Allowed、After 的 Blocked 和权限版本变化。 |
| 35–45秒 | 点击 `Run employee query again`。它会自动切回Jax并重问当前问题。 |
| 45–60秒 | 展示无可用授权证据的安全提示和空来源列表，再指向仍可选择的 orgforge。停留几秒，保存为 `3D_security_lens.mov`。 |

前后卡片大数字表示允许的**来源种类**，项目撤权后可能仍为3；应展示项目 Allowed→Blocked 和权限版本，不能说数字是可读文档数量。

录制完如需重录：切管理员→Manage Permissions→Jax→重新勾选项目，密级保持Confidential，再切回Jax。不要删除或更换来源身份。

## 英文旁白

> The employee can initially read the project evidence and receive a cited answer. In Security Lens, the administrator removes access to this project. The permission version changes, and the next request uses the updated permissions. When we run the same question again as the employee, the protected evidence is no longer returned. The dataset remains selectable, while the service safely reports that no authorised evidence is available. Access is checked by the backend, including when an original document is opened.

## 本轮线上复测证据

- 运行代码 `ca0886b2`，PID775226；四份显式资源都有 `manual_demo`、项目 `demo:swiftui-telemetry`、confidential、允许部门Engineering_Backend。
- 配置中的三题在keyword/hybrid均有结果，所有命中及真实GLM回答引用均落在标注范围内，实际引用为两份公开工程Slack。第三题纯vector没有命中，默认hybrid有结果；不把纯向量召回描述为全题通过。
- 三题回答请求ID：`65171d7e-dc4d-4560-b1c2-fa63c1b997fd`、`2d3ab1af-d35e-4d26-ae77-62603cb9f074`、`20eab11c-2c77-4b39-a870-69fe4c1c44ec`。
- 分别撤项目、降密级后，三题×keyword/vector/hybrid均零证据；三题回答模型attempts均0。四份原文均404，OrgForge仍可选，无关TitanDB关键词结果不变。
- Alex同为Confidential，因部门不匹配三题×三模式均零证据；Jax原本不能读的私聊仍404。
- 测试后恢复Jax项目允许、密级2；审计链有效。原始详细结果留服务器 `previews/aspire-ui-20261015/demo-permission-annotations/recheck-20261016.json`，不提交运行时日志。

## 问题范围说明

使用上述带ENG-195/PR-135的完整问题。旧版宽泛问题 `What can I monitor in the telemetry dashboard?` 实测召回5份其他Confluence资料；仅增加SwiftUI但不点编号的旧问题还召回两份其他Slack。它们沿用原ACL、未加本次人工项目标签，因此撤销这个项目不应使其他授权资料全部消失。

不为得到空结果而批量标注这些无关资料。首页已使用三道明确问题；若视频前段用了旧问题，本段应重新展示并提交明确问题，不能把两道不同问题剪成“同题重问”。

本次未改业务代码或重新应用数据标注。真实模型答案仍遵循已知限制：有评审/合并记录不代表已发布，现有选中Slack标题有截断，不能补造完整指标。
