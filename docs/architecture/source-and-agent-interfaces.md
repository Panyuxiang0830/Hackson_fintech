# 四来源适配与 Agent/MCP 接口

日期：2026-10-14。分支 `codex/REQ-020-source-mcp-adapters`，基于 main `c2a930e1`。本轮代码待验收：用户要求不运行测试/真实联调；未部署、未推送、未合并。

## 数据接入

平台只读 API → 原始记录/权限检查依据（私有 `source-raw.sqlite`）→ 显式身份映射 → 已有 DocumentUpdates → SQLite/FTS/Qdrant 安全发布。

| 来源 | 首版内容 | 自动读取的授权依据 | 前置条件/限制 |
|---|---|---|---|
| Jira Cloud | 工单正文、标题、当前状态、更新时间 | 对配置 account ID 检查该 issue 的 BROWSE_PROJECTS grant，不用项目级结果替代工单授权 | 对他人检查通常需要 Administer Jira 权限；有 issue security 或该字段不可观察时隔离，须后续委托用户可见性检查；不合并评论/附件 |
| Confluence Cloud | 指定 Space 当前页面、正文、版本 | 平台 read permission check，包括 site/space/content restrictions | 检查其他用户通常需要 Confluence Administrator 权限；失败隔离，不只看页面自身限制 |
| Slack | 指定频道消息与完整可取得的线程 | 完整分页成员快照与 mapped 用户 deleted 状态 | 需 history/read/users 权限与实际可读取线程的 Token；公共频道也只授予已映射当前成员，范围保守；不读取附件 |
| Drive | 指定文件夹直接子文件：Docs 文本、Sheets CSV、普通 txt/md/csv | 完整分页文件权限条目，仅映射非删除、未过期的 user 读权限 | OAuth access token；不展开 group/domain/anyone，不递归目录；PDF、Slides、OCR 等 metadata-only 隔离；CSV 导出不代表全部工作表 |

以上均为**可验证的映射子集**，不是完整企业目录/群组同步。principal_map 只建立身份对应，不手工给每篇资料贴 ACL：实际许可来自本次平台响应。未知用户不能因名称或邮箱域匹配就获得授权。采集账号权限不等于员工权限。

来源更新保留既有系统分类、部门、角色约束和本地拒绝规则，不把受限分类重置为 internal。新资料默认 internal，但读取仍取决于精确来源 ACL；项目/部门跨平台归属不由模型猜测，可在来源配置中显式提供 project 标签，未完成企业目录与统一分类自动对齐。

先在 canonical corpus 建立来源 principals，并由管理员把系统用户显式绑定到正确 principal。已有 CLI `contextledger.integration user` 仅绑定已存在 principal；本轮不自动创建来源用户或提升权限。正式接入须通过企业身份目录/管理员核对完成这个前置步骤。

复制 `config/sources.example.json` 到私有配置，替换站点、范围、native ID → canonical principal 映射，并把目标来源的 enabled 改为 true。建议使用独立 enterprise corpus；不复用离线演示 corpus 来伪装真实公司。必须已有该 corpus 的已发布初始索引，增量更新不能替代初次索引建立。

密钥通过配置中的环境变量名读取；不放入 JSON、不打印请求或原始失败响应。第一版 Atlassian 使用租户域名与 email/API Token；Drive 接收已授权 access token，不实现刷新/注册授权流程。公司权限不足/Token 过期返回失败，不能标为已接通。

```bash
python -m contextledger.source_sync --out /absolute/content \
  --security-dir /absolute/security --config /private/sources.json \
  --env-file /private/connectors.env --source confluence --admin-id EXISTING_ADMIN_ID
```

默认拉取一次；加 `--interval 60` 才启动运维周期进程，未自动设置定时任务。每轮重新读配置范围内的资料/权限，不是 Webhook 或全平台增量游标同步。每轮 API 预算最多 500 请求/120 秒、单响应2 MiB；文档预算默认100，可配置1–1000，超过预算拒绝将截断扫描当完整快照。完整 ACL 分页失败时不部分放行。

原始记录保留每次观察依据，私有原始库上限256 MiB，达到上限阻断而非自动删除；持续周期运行需运维安排容量、备份与后续保留策略。大正文/不支持格式进入隔离区，不静默截断后发布。

### 更新与权限门闩

- `live_source_guards` 位于身份库，内容重建不能绕过它。刷新前先阻断；完成范围枚举、权限映射和所有更新发布后才就绪。
- 刷新失败/进程中断/快照过期，当前 corpus 的所有检索和原文保守返回不可用；不是正常零证据。首版可用性代价明显，不宣称无中断更新。
- 默认 ACL 有效期300秒，可配置60–3600秒；从本轮开始观察计时，不把发布时刻冒充来源检查时刻。超过窗口的长刷新不会放行。
- 同一 corpus/source 刷新由私有文件锁串行化；更新沿用版本前置条件和现有索引锁。普通管理员文档修改仍走原队列。
- 权限未知/不支持格式新资料隔离，既有对应资料撤成空 ACL；完整枚举后消失的既有 live 资源也撤成空 ACL。此行为只使其不可检索，不是完整删除/历史回滚能力。
- 这只能报告“本次来源权限快照 + 系统内限制”，不能承诺变更尚未被观察时已实时获知撤权。系统内撤权、调用前后及交付检查继续生效。
- 现有管理员来源状态 API 可显示 snapshot_ready/unavailable；未启用来源继续 not_enabled，不生成假的健康状态。

## 两条模型路线

宿主路线（默认）：Agent → MCP search/fetch → 私有 Tool API → UnifiedService → 授权证据 → 宿主模型回答。search 的 planning 固定 false，不调用内部 GLM；向量查询仍使用既有本地 Embedding。宿主自己的模型/API 在宿主产品内配置，与 ContextLedger 的 Key 无关。

内部路线（可选）：Agent → MCP ask → UnifiedService.ask → 已有 GLM/Radar → 完整答案与引用。复制 `.env.tools.example` 至私有 env 文件，按用户选择设置 LLM_BASE_URL/API_KEY/MODEL。服务端 TOOL_INTERNAL_ANSWERS=true，MCP 端 CL_MCP_ENABLE_ASK=true，且该用户 Token 具有 ask 能力，三者同时满足才可用。内部接口不接受每次调用传入任意模型URL/Key；切换服务端配置后重启私有 gateway，不影响原 UI 进程。

可选 audit 需 token 的 audit 能力、当前 admin/compliance 角色和 CL_MCP_ENABLE_AUDIT=true；TOOL_INTERNAL_ANSWERS=false 时仅返回已脱敏条件结果，由宿主解释，否则使用已有有界审计模型。普通身份即使能发现该工具也不能查审计。

工具结果中的正文是数据，不是可信指令；建议宿主引用来源/版本并遵守中性零证据提示。系统只能保证其接口的授权输出，不能保证宿主最终回答正确或约束宿主其他工具。宿主回答内容未回传，审计只记录工具调用与交付证据，**不声称记录了宿主最终答案或完成了其引用校验**。

## 工具身份与启动

不使用浏览器 cookie、演示选择用户参数或共享全权 Key。由本机可信运维为既有账号发行有能力范围/有效期的个人 Token；只保存SHA-256哈希，不存明文、不把角色冻结进 Token。凭据撤销、账号停用、权限版本变化、索引或来源门闩变化在交付前再次检查。

Token检查通过请求局部 ContextVar 接入现有检索/模型/交付 fence，结束请求后清理，不在共享服务实例上临时切换用户。发行凭据的命令假设操作者已获本机运维权限；本机文件和环境若能被智能体任意读取/改写，stdio 本身不提供额外隔离，企业需独立服务账号、私有部署和可信网关。

```bash
# 安装动作仅供操作者后续执行，本轮没有安装或启动。
python -m pip install -r requirements-tools.txt
python -m contextledger.tool_api --out /absolute/content --security-dir /absolute/security \
  issue-token --admin-id EXISTING_ADMIN_ID --user-id EXISTING_EMPLOYEE_ID
# 输出一次明文 Token，只存入客户端私有配置，不提交/截图。
# 需要内部回答时，发行命令额外指定 --capabilities search,fetch,ask；
# 需要审计则加 audit，且账号本身必须已有 admin/compliance 角色。
python -m contextledger.tool_api --out /absolute/content --security-dir /absolute/security \
  --env-file /private/tools.env serve --port 17864
# 撤销个人凭据，不等于删除账号或恢复来源权限。
python -m contextledger.tool_api --out /absolute/content --security-dir /absolute/security \
  revoke-token --admin-id EXISTING_ADMIN_ID --token-id TOKEN_ID
```

只监听127.0.0.1。远端可通过SSH端口转发访问；不得公开 Flask 预览。正式共享部署需要TLS代理、限流与企业可信身份方案，未交付OAuth/生产部署。本方案无新登录页面；固定演示用户 Token 也不能包装成企业身份认证。

### Codex 配置示例（私有 config.toml）

```toml
[mcp_servers.contextledger]
command = "/absolute/venv/bin/python"
args = ["-m", "contextledger.mcp_server"]
cwd = "/absolute/repository"
env_vars = ["CL_TOOL_URL", "CL_TOOL_CORPUS", "CL_TOOL_TOKEN", "CL_MCP_ENABLE_ASK", "CL_MCP_ENABLE_AUDIT"]
```

### Claude Code / WorkBuddy 配置示例（私有 MCP JSON）

```json
{
  "mcpServers": {
    "contextledger": {
      "command": "/absolute/venv/bin/python",
      "args": ["-m", "contextledger.mcp_server"],
      "env": {
        "PYTHONPATH": "/absolute/repository",
        "CL_TOOL_URL": "http://127.0.0.1:17864",
        "CL_TOOL_CORPUS": "enterprise",
        "CL_TOOL_TOKEN": "REPLACE_ONLY_IN_PRIVATE_CLIENT_CONFIG",
        "CL_MCP_ENABLE_ASK": "false"
      }
    }
  }
}
```

Claude Code 使用其 MCP 私有配置；WorkBuddy 使用其 MCP 配置入口。不同客户端环境变量/secret扩展行为可能不同，不假设都支持 `${VAR}`。不要把真实 Token 放到 Git 的项目配置。`python -m contextledger.mcp_server` 的 stdout 专供 MCP 协议，不输出启动日志。

CL_TOOL_CORPUS 指定默认数据集（未配置为 orgforge），因此普通提问不必先知道数据库名；显式 corpus 参数仍由服务端验证当前用户范围，该配置不授予权限。

**首版只有 stdio MCP + 私有 HTTP 工具 API；HTTP 工具 API 不是 `/mcp`，不能直接当作标准远程 MCP 地址填入客户端。** 三客户端模板未联调；发行安装包、插件市场、Streamable HTTP/OAuth 为后续任务。

## 本轮验证与 Demo 表述

按用户要求，离线回归用例已准备但未运行；未请求真实平台或GLM、未验证三客户端、未重建现有索引、未改服务器权限或数据。仅进行静态语法、需求生成与diff检查，不能把这些当成功能验收。

建议 Demo：系统提供四平台只读API适配、可验证的来源权限快照及MCP工具入口；演示使用离线数据。企业需配置凭据、采集范围和稳定身份映射，真实企业环境联调及完整目录/实时撤权同步尚待验证。不要宣称“填一个Key就已支持企业全部权限”。

依据：[Jira 权限 API](https://developer.atlassian.com/cloud/jira/platform/rest/v3/api-group-permissions/)、[Confluence 有效权限检查](https://developer.atlassian.com/cloud/confluence/rest/v1/api-group-content-permissions/)、[Slack 会话成员](https://docs.slack.dev/reference/methods/conversations.members/)、[Drive 权限](https://developers.google.com/workspace/drive/api/reference/rest/v3/permissions/list)、[MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)、[Codex MCP](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)。
