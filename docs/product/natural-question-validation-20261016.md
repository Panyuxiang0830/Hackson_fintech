# 自然问法演示验证（2026-10-16）

关联REQ-019、REQ-016。用户要求演示问题采用自然问法，实际测试成功后再给出录制问题。

## 发现与修复

无编号的具体评审问题已能在原有权限下召回标注资料，但线上 `answer-v12` 连续两次把几十词的英文单段回答作为“超过200字符长文”拒绝，导致 `mock_fallback`，不能用于正常录制。

`answer-v13-2026-10-16` 按含中日韩文字超过200字符、其他文本超过80词判断长文。短回答允许一段，长文仍须分段；同步系统Prompt、受限重试提示和文档快照。不修改原问题、来源正文或ACL，不放宽引用和权限校验。

回归覆盖：超过200字符但不足80词的英文首轮通过、超过80词的英文仍须格式重试；既有中文长段、非法引用、权限变化停止重试及零证据不调用模型检查继续运行。

## 线上验证状态

- 本地完整379 unittest通过；服务器完整387 pytest + 156 subtests通过，项目同步检查通过。
- 新release `releases/natural-question-20261016`，代码26d9a0d0，PID783815；仍为17866入口。代码切换前后身份、绑定、限制一致，备份在 `backups/before-natural-question-20261015T164732Z`（目录时间为UTC）。不修改内容库标注或来源ACL。
- 实测原问题：`What did the GitHub review say about the SwiftUI dashboard's UIKit timers?`。真实GLM正常回答，一次调用、无格式失败，引用仅为已标注公开评审记录；不是固定答案。请求ID `6fb631ff-5d1e-4ed4-84ea-dece265a63bf`。
- 撤销SwiftUI演示项目后，同句keyword/vector/hybrid均为空，回答模型attempts=0、原文404、orgforge仍可选择；请求ID `9bb62d58-0bbc-4e1f-92a8-6b9ffee41ebe`。
- 恢复项目后同句真实模型再次正常回答，结束Jax项目允许、Confidential(2)、权限版本27，审计链有效。
- 详细结果留服务器 `demo-permission-annotations/natural-question-20261016.json`，不提交运行时日志。用户录制和人工验收待完成，不合并main。
