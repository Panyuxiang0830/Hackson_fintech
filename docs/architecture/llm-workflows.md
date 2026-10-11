# 有界模型链路实施说明

2026-10-11，`codex/llm-workflows`。**模型引用复核与反馈重答已按用户要求完全取消。** 复用 Part A 的 SQLite 事实库、Qdrant/FTS、身份权限库与审计链；本次不改索引格式、不需要重建向量。旧部署记录仅为历史，不代表当前实现或验收。

## 当前调用链

业务：当前身份/权限 → 固定索引快照 → 可选一次规划 → 原问题＋有限授权检索分支 → 文档 RRF 去重 Top-5 → 证据权限与版本检查 → 回答模型 → 确定性格式/编号检查 → 权限与版本交付检查 → 页面和审计。**不调用第二模型判断，不反馈重答。**

审计：admin/compliance → 确定性合法条件查询 → 哈希链/当前业务权限脱敏 → 有界事件白名单 → 模型解释 → E 引用编号检查 → 角色、证据和链再次检查 → 交付及追加审计。失败仅回退确定性查询结果。

`llm_workflows.py` 只保留规划/审计与共用受限传输；`unified_service.py` 编排。模型无 SQL、检索工具或身份接口。API：search/ask 支持 planning；POST /api/audit/ask 受 CSRF/角色控制；GET /api/audit 保留条件查询。

## 配置与界面

- 生成继续使用 LLM_MODEL；规划/审计可通过 LLM_PLANNER_MODEL、LLM_AUDIT_MODEL 配置，空时沿用基础 GLM。对应地址/Key 可另配，均不写入 Git。
- LLM_PLANNER_ENABLED 代码默认 false，页面可开关。计划错误或超时回退原问题，不放宽 ACL。
- **移除所有 LLM_REVIEW_* 读取及配置同步。** 即使旧运行配置保留 true，也无法重新激活已删除的模型复核。
- 页面只显示规划状态/分支数及回答，不再展示 invalid_review、首次反馈或重答卡片；明确仅校验编号与授权范围，不宣称逐句事实验证。
- 无可用业务范围或证据，服务端直接给中性提示，不调用生成模型。历史审计记录保留。

## 预算与安全

| 阶段 | Prompt | 上限 | 调用 |
|---|---|---|---|
| 规划 | query-plan-v1-2026-10-11 | 原问题；3 子问题、3 语义句、8 关键词、2 候选；900 输出 Token | 0/1，15 秒网络超时 |
| 业务生成 | answer-v9-2026-10-11 | 原问题＋总 Top-5，每段 ≤4000 字符；1600 输出 Token | 最多 2，30 秒/次；仅既有格式错误重试 |
| 审计生成 | audit-answer-v1-2026-10-11 | 最多 20 可见事件、总 JSON ≤40000 字符；1600 输出 Token | 0/1，20 秒 |

JSON 输入 ≤60000 字符、HTTP 响应 ≤128 KiB。字符不是精确 Token 预算，网络超时不是端到端 SLA。业务最多 3 次、审计最多 1 次，不无限循环。诊断保留版本、型号、参数、耗时、用量与安全失败类型，不保存密钥、原始异常或非法输出。

原问题不变；最多 5 个分支/每路 Top-5，最终融合总 Top-5。关键词必须来自原问题，纠错需确认。所有分支与模型调用前后、HTTP 交付都检查同一当前权限和索引版本；角色或版本变化仍丢弃回答。

审计输入只含白名单可见元数据与截断的可见 query/answer；无业务访问权仍脱敏，不读任意 extras/全库。服务端追加截断警告，无匹配不作全时段不存在判断。

## 验证范围

主测试与 Part A 测试使用合成语料/受控 API 验证控制流、错误引用、脱敏、权限/版本竞态与零证据，不证明真实模型正确或规划提高召回。新回归确认旧复核开关无法重启、业务一次生成/审计一次生成、合法编号交付、非法编号仍安全降级、交付撤权仍拒绝。

本轮实际部署/回归结果在下方另记。真实 GLM 质量、规划收益、五场景录制、新鲜度和原平台撤权自动同步仍需分别验收。Codex 插件为未来计划，当前没有工具适配层，不恢复真实浏览器登录。

## 当前取消复核版部署（2026-10-11）

代码快照 `0cebdbf3` 已部署至 `/hy-tmp/data_pyx/contextledger-integration/releases/llm-workflows-0cebdbf3`。本机与服务器传输包 SHA-256 相同，服务器 195 项主测试、需求同步检查通过；本机 195 项主测试、8 项 Part A、需求同步、JavaScript 语法及 diff 检查通过。移除专用模型复核测试并新增取消/基本安全回归，所以测试数变化不代表未跑完。

新 PID 4102192 仅监听 gpushare `127.0.0.1:17863`，本机 SSH 转发 PID 5651 / 执行会话 59531 将 `127.0.0.1:17860` 转至新端口。访问 `http://127.0.0.1:17860/` 后刷新即可加载新版。原 17862/17861/17860/7860 和 Qdrant 6335 保留；既有 content、security-demo、0600 配置均复用，没有重建索引、重置身份权限或删除日志。旧复核配置即使存在，也没有代码读取。

```bash
ssh -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
  -L 127.0.0.1:17860:127.0.0.1:17863 gpushare
```

日志：`/hy-tmp/data_pyx/contextledger-integration/logs/llm-workflows-preview-0cebdbf3.log`；回归日志同目录 `llm-workflows-regression-0cebdbf3.log`。会话 API 不再返回 review_enabled/review_configured，实际 HTML/JS 没有反馈卡片、重答或复核加载状态。配置继续允许规划；下列真实调用为关闭规划的小样本，未验证规划收益。

在独立 HTTP 测试会话选择已有 Jax，未修改其权限，提问“TitanDB 是做什么的？”：请求 `9bfab443-46c2-4233-afee-c588f26dd821` 返回 answered、GLM-5.3-Flash、5 条授权证据，生成 1 次、answer-v9；没有复核或 regeneration 字段。随后使用独立管理员只解释该请求：审计请求 `73712d58-cb5b-47e9-9726-288d07d10cb1` 返回 answered、同 GLM 生成 1 次、E 事件引用、业务内容继续脱敏，审计链有效（当时 98 事件）。这些操作产生正常查询/身份选择审计事件，不是伪造开发工具证明。

这只确认两条真实调用及取消控制流，不证明样本事实逐句正确、规划提升 Recall、五场景全部通过或整体模型质量。未推送/合并分支；后续文档提交不改变该部署的代码快照。

## 历史预览记录（复核/重答链已取消，不再使用下列配置）

## gpushare 首次新版隔离预览（2026-10-11，历史快照）

用户要求打开前端进行人工操作后，将 Git 提交 `1fa92b23` 的已跟踪代码打包至 `/hy-tmp/data_pyx/contextledger-integration/releases/llm-workflows-1fa92b23`；没有修改服务器原 Git checkout 或 main。新的预览进程 PID 为 4093059，仅监听服务器 `127.0.0.1:17861`；本机 SSH 转发 `127.0.0.1:17860 → 服务器 127.0.0.1:17861`，页面打开于 `http://127.0.0.1:17860/`。

复用原 `content`、Qdrant、`security-demo` 和 `preview-demo.env`，未重建索引或初始化账号。原 7860、服务器旧 17860 和 Qdrant 6335 均继续运行。新进程的 `APP_PUBLIC_URL` 是本机访问 URL 17860；`LLM_PLANNER_ENABLED/LLM_REVIEW_ENABLED=true`，型号默认复用基础 GLM。`/api/session` 已验证 planner/review 为 enabled、configured；浏览器已确认新规划开关、同模型提示、七账号和“让模型解释审计”入口。没有自动修改用户权限或触发真实模型问答。

若本机转发断开，先确认本机 17860 没有被占用，再恢复：

```bash
ssh -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
  -L 127.0.0.1:17860:127.0.0.1:17861 gpushare
```

服务器启动日志：`/hy-tmp/data_pyx/contextledger-integration/logs/llm-workflows-preview-1fa92b23.log`；203 项主测试日志同目录 `llm-workflows-regression-1fa92b23.log`。预览是本次代码快照，后续代码提交不会自动热更新。用户尚未完成完整验收，不能因页面可打开就标记模型功能 validated。

## 反馈重答版预览（2026-10-11）

代码提交 `87a07d6e` 独立部署至 `/hy-tmp/data_pyx/contextledger-integration/releases/llm-workflows-87a07d6e`，PID 4094988 监听服务器回环 17862。服务器需求检查和 208 项主回归通过；复用原 0600 模型配置、事实库/Qdrant 和 security-demo，不初始化权限或重建索引。17861 的前版及旧 17860/7860 保留，可恢复旧预览。

本机 17860 的转发目标改为服务器 17862；前端须刷新加载新脚本，已有账号/会话保留。恢复命令：

```bash
ssh -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
  -L 127.0.0.1:17860:127.0.0.1:17862 gpushare
```

新启动日志：`/hy-tmp/data_pyx/contextledger-integration/logs/llm-workflows-preview-87a07d6e.log`；208 项测试日志：同目录 `llm-workflows-regression-87a07d6e.log`。规划/复核配置就绪；真实质量和用户完整验收仍待完成，不自动推送/合并。

真实 GLM 小样本：在独立 HTTP 测试会话选择已有 Jax，提问“TitanDB 是做什么的？”，未更改权限。请求 `cb6875e4-6fd5-4156-a873-be774d833a76` 返回 answered、5 条授权证据；首次复核 invalid_review，重答 1 次、regeneration=revised_not_reviewed，页面警告字段存在。首次生成/复核/重答分别 1 次且审计链有效；未在事件中保存自由反馈。这只验证真实调用与失败后的重答控制流，不证明语义正确性、总体复核质量或完整验收。
