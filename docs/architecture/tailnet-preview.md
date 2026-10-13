# Tailscale 私有试用

REQ-016 / REQ-017，2026-10-13 用户授权在其他 Tailscale 机器上使用浏览器试用。部署内容为聊天评测的合成资料与固定演示账号，不是生产登录或来源平台实时同步。

入口使用 Tailscale Serve HTTPS，后端 Waitress 仅绑定回环。`TailnetPreview` 验证请求来自回环、Host 为运维配置的精确 `*.ts.net` 域名、Tailscale 登录在允许列表内，并检查浏览器 Origin。Tailscale Serve 会移除客户端伪造的身份头并填入真实登录；tagged 节点没有该身份头，因此默认拒绝。依据：[Tailscale Serve 身份头](https://tailscale.com/docs/features/tailscale-serve#identity-headers)。

允许的 Tailscale 身份只获得演示入口，不能直接决定应用角色或来源身份。网关通过校验后将 Host／Origin 规范化到既有回环应用；固定七账号、CSRF、持久化 IdentityStore、索引权限／版本检查与审计继续执行。Cookie 使用 Secure、HttpOnly、SameSite=Lax。不得把该网关用于共享生产 IAM 或对公网 Funnel 开放。

## 启动

安装 `requirements-tailnet-preview.txt` 和既有 MiniLM 依赖、准备独立的内容库和演示权限目录、发布到持久化的原生 Qdrant，再运行：

```bash
.venv/bin/python scripts/serve_tailnet_preview.py \
  --out /absolute/demo/content --security-dir /absolute/demo/security \
  --env-file /absolute/protected/model.env \
  --qdrant-url http://127.0.0.1:16339 \
  --public-url https://YOUR-NODE.YOUR-TAILNET.ts.net:8444 \
  --allowed-login YOUR-TAILSCALE-LOGIN --port 17862
tailscale serve --bg --https=8444 http://127.0.0.1:17862
```

密钥与稳定会话 Secret 保存在仓库外的私有配置，不进入命令参数或 Git。后台部署固定代码提交，使用 systemd 用户服务的自动重启及已启用的 linger；Qdrant 只监听回环，数据挂载到独立目录，容器配置 `unless-stopped`。服务重启不重新初始化账号，也不重跑或覆盖测评。

## 维护

```bash
systemctl --user status contextledger-tailnet-preview.service
systemctl --user restart contextledger-tailnet-preview.service
tailscale serve status
```

撤销本服务的网络入口只操作新增端口，保留节点上其他 Serve／Funnel 配置：

```bash
tailscale serve --https=8444 off
systemctl --user stop contextledger-tailnet-preview.service
```

浏览器连接同一获准 Tailscale 账号后访问 HTTPS 域名。该私有部署显式启用 `DEMO_AUTO_ENTRY`：首次通过既有 CSRF 接口选择启用且绑定来源的普通员工 alice，提问框和按钮即可使用；已有选择及撤权保留，不默认进入管理员。右上角可切换 outside 验证拒答，管理员用于权限与审计。管理员角色不会自动获得业务读取权。当前界面支持单轮问答，追问保留业务名称。

## 当前入口

- URL：<https://lab-cw3.tail4ecfc0.ts.net:8444/>，允许的 Tailscale 登录为 `idjyiq@gmail.com`。
- UI：`feat/REQ-017-team-ui-integration` 的 `81d4164`，同步 main 并保留当前 Radar 展示；浏览器可用例题为“HarborLedger 是做什么的？”和“TracePay 当前每日转账上限是多少？”。
- 内容、安全状态和 Qdrant 位于独立 `runtime/deploy/tailnet` 目录；代码通过固定提交的 Git worktree 发布。浏览器选择身份不会重置权限，服务重启也不重新初始化账号。
- 验证报告保存在本机 `runtime/deploy/tailnet`，13 项浏览器检查通过：首次自动进入、空问题、真实 DeepSeek 回答、原文、问题编辑、移动布局、身份切换、越权零模型调用、已有身份重载、未知实体、旧请求隔离、管理与审计导航；无 JavaScript 错误。另一台 `VM-0-7-ubuntu` 已验证真实 TLS 页面、检索、原文和越权拒答。Radar 以已有真实模型响应回放展示并通过当前原文接口，不将回放计为新模型测评。聊天仍为单轮；评测结果不因 UI 更新而改写。

UI 已通过 [PR #15](https://github.com/Panyuxiang0830/Hackson_fintech/pull/15) 合入 main（`c2a930e`）；聊天与私有网关仍在独立 PR #14。部署版本、报告和后台状态可分别核对，UI 合并不等于 PR #14 已合并。
