# DashKit 前端与团队版集成

- 日期：2026-10-12
- 分支：`feat/REQ-017-team-ui-integration`，基于团队版 `73c3130`
- 关联：REQ-017、REQ-015 的检索前规划扩展、REQ-008 的模型审计回答扩展
- 状态：本地集成，尚未合入 `main` 或部署到真实数据环境

用户现有的英文 DashKit 风格页面来自工作区 `Hackson_fintech`；其 HTML、CSS、JavaScript 和教学 SVG 已复制到本分支，并保留在 `backup frontend v2`。原项目及备份没有被改写。团队版的事实库、Qdrant/FTS、身份、权限、回答、审计和评测 Python 代码继续使用 `73c3130`。

## 新入口的实际接线

| 页面操作 | 已有团队版接口 | 呈现与边界 |
|---|---|---|
| 检索前规划开关 | `GET /api/session` 的 `workflows.planner_enabled`、`planner_configured`；`GET /api/search` 和 `POST /api/ask` 的 `planning` 布尔参数 | 仅服务端已配置规划模型时允许切换；不可用时显示原因并按原问题检索；结果只显示状态和分支数，不展示不可信计划正文 |
| 提问与证据 | `/api/corpora`、`/api/search`、`/api/ask`、`/api/doc` | 沿用服务端会话与当前权限；回答、版本、引用和原文来自接口，前端不伪造或翻译 |
| 条件审计查询 | `GET /api/audit` | 只对 admin/compliance 显示入口，展示完整性、脱敏事件和可展开详情；导出当前已返回的脱敏 JSON |
| 模型审计解释 | `POST /api/audit/ask` | 提问非空时发送同一条件，保留 CSRF 和角色限制；根据 `provider` 区分模型解释与确定性回退，不把回退标成模型结果 |

业务问答、审计查询和模型审计解释期间若身份或权限版本变化，页面清除旧证据和审计结果；旧请求完成后也不再回填。真实安全决定始终由服务端执行，前端角色显示只用于导航。

## 页面范围

保留英文界面、DashKit 参考的侧栏和卡片布局、查询前教学插图，以及短时入场／反馈动效和 `prefers-reduced-motion`。原始证据与服务端答案仍按来源和服务端返回语言显示；本轮不改回答模型 Prompt 或后端语种规则。没有新增评委权限对比入口，也不恢复真实浏览器登录。

本地隔离预览可使用合成 SQLite/Qdrant 数据和 Mock 回答，验证接口与权限流。若未配置模型 Key，规划状态为 `not_configured`，模型审计解释使用确定性选择结果。该预览不能证明真实 GLM 质量、线上来源新鲜度或服务器部署状态。下一步真实验收应在团队的 Linux 运行环境使用当前数据、权限和审计状态进行。
