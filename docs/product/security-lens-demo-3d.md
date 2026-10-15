# 3D：Security Lens——撤权前后对照（约60秒）

2026-10-16；REQ-016/resource_access_controls、REQ-019。采用当前界面的三个来源开关，录制问题为自然问法。以下流程在17866隔离演示入口完成真实模型与后端权限复测；用户人工录制待完成。

## 录制前准备（不计入60秒）

1. 刷新页面，顶部身份选 `ContextLedger Administrator`，进入 `Manage Permissions`，员工选 `Jax`，数据集选 `orgforge`。
2. 保持 `Allow dataset reading` 勾选，勾选 `Confluence`、`Jira`、`Slack`，每次等待自动保存完成。密级为 `Confidential`，项目卡片保留 `SwiftUI Telemetry Dashboard`；若缺少该卡片，搜索 `SwiftUI` 后添加。
3. 切为 `Jax`，数据集选 `orgforge`，`Query planning` 设为 `Off`。输入下方原句，等待正常回答和引用出现，再开始录制。模型等待时间不计入成片60秒。

```text
What did the GitHub review say about the SwiftUI dashboard's UIKit timers?
```

含义：SwiftUI看板评审对UIKit计时器提出了什么问题？本轮实际回答指出后台队列更新UI及UIKit计时器问题，并引用工程Slack中的评审讨论；不把该记录描述为直接读取GitHub原文。

本轮复测结束已恢复测试前状态：Jax的三个来源全部关闭，原三个项目与Confidential密级保留，权限版本128。因此录制前需要完成上面的开通准备。

## 60秒操作与旁白

| 成片时间 | 屏幕操作与应见结果 | 中文讲解要点 |
| --- | --- | --- |
| 0–10秒 | 展示Jax刚得到的正常回答和引用标记。 | 这名员工目前可以读取相关项目资料，系统据此生成带引用的回答。 |
| 10–22秒 | 顶部身份切为 `ContextLedger Administrator` → `Manage Permissions` → 员工选 `Jax`，确认数据集 `orgforge`。 | 现在管理员撤销这名员工的资料读取权限。 |
| 22–38秒 | 依次取消 `Confluence`、`Jira`、`Slack`，每次等待保存完成；保留 `Allow dataset reading`。展示来源Allowed→Blocked和权限版本变化。 | 修改会立即保存，后端在下一次请求使用最新权限。 |
| 38–45秒 | 点击 `Run employee query again`。系统自动切回Jax，重新提交刚才同一句问题。 | 用相同员工、相同问题再次查询。 |
| 45–60秒 | 展示证据不足提示、没有返回来源，并展示数据集下拉框中的 `orgforge` 仍可选择。 | 数据库仍然可以选择，但已撤权资料不会进入回答。 |

第三步三个开关全关后，前后卡片的大数字应从3变为0；这是允许读取的**来源种类**，不是文档数量。权限版本展示实际变化即可，不念固定数字。

`Run employee query again` 会复用当前页面已提交的问题。录制期间保持同一标签页，不刷新页面；不要点首页预置问题替换当前问句。如果误刷新，重新输入上面的原句再查询即可。

## 英文旁白（约40–50秒，配合操作停顿）

> Jax can initially read the relevant evidence and receive a cited answer. Now, the administrator opens Security Lens and revokes his reading access to Confluence, Jira, and Slack. Each change is saved, and the permission version updates. We run the same question again as Jax. The backend applies the new permissions, so no authorised evidence is returned. The system safely reports insufficient evidence instead of generating an unsupported answer. Notice that OrgForge remains selectable: access to the dataset is preserved, while access to its protected content has been revoked.

## 收尾与重录

录制可停在撤权结果。重录时切管理员，重新勾选三个来源，再切回Jax提交同一句问题并等待正常回答。员工绑定、项目卡片及密级按上述准备保持即可。保存成片可用 `3D_security_lens.mov`。

## 2026-10-16 最新复测证据

- 服务代码58ffc6ef，当前17866入口；已应用九项目目录及75份项目标签，本次仅验证录制流程，没有更换服务或修改业务代码。
- 正常回答请求 `e13e556a-04fe-4e7e-a145-07a2d47c9bed`：真实 `openai_compatible/glm-5.3-flash`，decision=answered，引用 `slack_engineering_2026-02-17T09:37:07`，项目为SwiftUI。
- 三来源关闭后请求 `c16771ba-ffea-47a2-8020-e4e0473b0124`：decision=insufficient、provider=deterministic、零证据、回答模型attempts=0；keyword/vector/hybrid均无结果，先前引用原文404，orgforge仍可选。
- 当前英文提示原文：`This request found insufficient usable evidence within your current access permissions. Please check your reading permissions or add more detail to the question.` 不将其描述为已证明数据不存在。
- 测试结束恢复原成员、密级和三来源关闭状态；Jax版本128，审计链有效。运行结果：服务器 `previews/aspire-ui-20261015/project-permissions/security-lens-recording-20261016.json`，不提交运行时日志。
- 项目单独撤权和四案例资料覆盖见[项目权限](project-permissions.md)；自然英文短回答修复与早期验证见[自然问法验证](natural-question-validation-20261016.md)。本稿替换旧版演示项目复选框步骤，历史记录可查Git历史。
