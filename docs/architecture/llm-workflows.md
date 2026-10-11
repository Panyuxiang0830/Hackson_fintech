# 有界模型链路实施说明

2026-10-11，`codex/llm-workflows`。复用 Part A 事实库、Qdrant/FTS、身份权限库和审计链；不改索引格式、不需要为本次模型功能重建索引。登录/Tool 仍延期，四个平台真实增量同步和新鲜度闭环仍未实现。

## 当前代码已接的链路

业务请求：可信会话与当前权限 → 固定索引快照 → 可选规划 → 原问题＋有限分支的授权检索 → 文档 RRF 去重 Top-5 → 再次检查 → 首次回答生成及编号校验 → 单独调用复核 → 通过则交付；未通过则把反馈交回原生成模型重答一次 → 第二版只做确定性校验，不再语义复核 → 权限/版本交付检查 → 页面与审计。

审计请求：admin/compliance → 确定性条件查询与哈希链验证 → 当前业务权限脱敏/白名单投影 → 最多 20 个事件给模型 → `[E序号]` 校验与单独调用复核 → 未通过则用同一可见事件和反馈重答一次，不再次语义复核 → 再次验证角色、证据和链 → 交付及追加审计。失败的第一版草稿不写入最终回答记录，第二版可以交付但明确未再次复核。

实现集中在 `contextledger/llm_workflows.py`，由 `unified_service.py` 编排。规划与复核没有检索工具、SQL 或身份接口。API：`/api/search`、`/api/ask` 支持 planning 开关；新增 CSRF/角色受控的 `POST /api/audit/ask`；旧 `GET /api/audit` 保留确定性查询。

## 配置和状态

复制 `.env.integration.example` 的字段至忽略的运行配置，不在聊天或 Git 中粘贴 Key。

- 回答继续使用 `LLM_MODEL`；规划和审计型号分别用 `LLM_PLANNER_MODEL`、`LLM_AUDIT_MODEL`，省略时复用回答型号。各阶段的 `BASE_URL/API_KEY/REASONING_EFFORT` 可独立配置；省略/空的地址与 Key 复用基础配置。
- `LLM_PLANNER_ENABLED` 的代码默认 false，示例配置为 true。页面复选框可开启或关闭；关闭用于原问题基线。配置缺失、超时或计划不合规都回退原问题，不放宽权限。
- `LLM_REVIEW_ENABLED` 默认 true。用户确认复用当前 GLM：`LLM_REVIEW_MODEL` 省略/空值时沿用 `LLM_MODEL`，地址和 Key 同样默认沿用基础配置，无需开通另一型号。复核使用单独的一次调用、专用 Prompt 和受限输入。2026-10-11 用户改为首次复核失败/不确定/无配置时不交付第一版，而是重答一次；第二版不再语义复核。false 用于 disabled 的未复核基线，不等于已确认。
- 页面显示 planning/review 的实际状态：supported、unsupported、uncertain、not_configured、api_unavailable、disabled、not_reviewed_mock、not_required。同模型时显示“同模型单独调用”；审计诊断保留生成/复核实际型号、`review_mode=separate_call`、`model_relation` 和 `independence=not_established`。supported 是模型辅助判断，不是独立事实证明；同型号可能重复相同错误，即使配置不同字符串也不能保证模型或错误独立。
- `scripts/sync_preview_config.py` 已扩充白名单，可同步这些运行配置，继续不打印凭据。新版隔离预览复用服务器现有 0600 配置，并用进程环境开启规划/复核；没有再次传输 Key 或改写原配置文件。

## 输入、输出与预算

| 阶段 | Prompt 版本 | 输入/输出上限 | 单请求调用 |
|---|---|---|---|
| 规划 | query-plan-v1-2026-10-11 | 原问题；3 子问题、3 语义句、8 关键词、2 候选；900 输出 Token | 0/1 次，15 秒网络超时 |
| 生成 | answer-v8-2026-10-11 | 原问题＋Top-5，每段最多 4000 字符；1600 输出 Token | 最多 2 次，30 秒网络超时/次；只有格式失败重试 |
| 审计生成 | audit-answer-v1-2026-10-11 | 最多 20 可见事件、事件 JSON 总计 ≤40000 字符；1600 输出 Token | 0/1 次，20 秒网络超时 |
| 复核 | citation-review-v3-2026-10-11 | 原问题、未交付回答、实际输入证据；最多 24 段、每段理由 ≤600 字符；2400 输出 Token | 0/1 次，20 秒网络超时 |
| 业务反馈重答 | answer-revision-v1-2026-10-11 | 原问题、同一证据、第一版（≤16000 字符）及有界反馈；1600 输出 Token | 0/1 次，30 秒网络超时，无格式重试/二次语义复核 |
| 审计反馈重答 | audit-answer-revision-v1-2026-10-11 | 同一可见事件/选择范围、第一版及反馈；1600 输出 Token | 0/1 次，20 秒网络超时，无二次语义复核 |

各次模型 JSON 输入 ≤60000 字符、HTTP 响应 ≤128 KiB。字符限制不是精确 Token 预算；网络超时不是完整链路的 SLA。业务最多规划一次＋首次生成两次＋复核一次＋重答一次（最多 5 次），审计最多 3 次；不无限重试。分别记录首次生成、复核和 regeneration 的耗时/参数/Token，不丢弃初次用量。币种费用和真实链路延迟仍待测。

模型计划字段严格校验，原问题不变；关键词必须出自原问题，扩展实体不能静默替换，显式数字/日期/否定不允许被删除。不同实体的子问题可以分别检索；不清楚的纠错只请求确认。所有分支使用同一 ACL/快照，最多 5 个分支、每路 Top-5，RRF 融合总 Top-5；原问题始终保留。只依据词法保护并不能证明语义完全不变，最终回答仍按原问题和证据核对，路由收益待评测。

复核模型收到 server-defined 的完整段落列表，返回 supported/unsupported/uncertain、理由和精确摘录。服务端核对段落覆盖、引用集合及摘录。**摘录存在仍不能证明语义支持**。未通过时，将逐段理由或技术失败的服务端提示与第一版一起作为不可信 JSON 数据发回原生成模型；不扩大检索范围、不把反馈当成证据/系统指令。仅重答一次；第二版继续格式、编号/授权、角色、版本与审计完整性检查，不再拦截语义复核状态。

页面显示首次状态、反馈和“已重答一次，未再次语义复核”；`regeneration.status=revised_not_reviewed` 不能写成 supported。用户接受的代价是第二版可能仍有事实错误。重答失败、非法编号或 insufficient 时仍使用安全提示/确定性审计结果。自由文本反馈仅在本请求内使用和当前授权页面显示，不写入长期诊断；审计保存最终交付文本、首次状态、反馈数量、重答诊断及明确警告，不保存第一版或复核摘录。权限变化后的反馈与答案一起被交付门闩丢弃，前端清除。

审计模型只读事件白名单元数据及可见 query/answer 的截断内容，不读任意 extras、旧计划或全库标题；无业务权限时问题/回答/证据脱敏。证据总数可见性遵循脱敏；真实零返回可以记录 returned_evidence_count=0。结果部分截断会由服务端追加范围警告，无匹配不证明从未访问。审计模型只摘要既有安全查询结果，不能代替合法的条件解析。

## 测试与尚未验证项

`tests/test_llm_workflows.py` 和 `tests/test_llm_integration.py` 使用真实本地 Qdrant/SQLite、合成语料及受控 API 返回，验证调用顺序、各路 ACL、模型前后/HTTP 交付撤权、版本变化、完整性异常、脱敏、错误摘录/引用、覆盖缺失、预算、失败降级和零证据。**不证明真实模型遵守 Prompt、规划提高 Recall，或复核错误率可接受。**

前版 `1fa92b23` 本机 203 项主测试及 8 项 Part A、gpushare 203 项主测试通过。本次反馈重答新增回归：逐段理由、一次重答/不再复核、第二版非法引用/网络失败/依据不足、重答期间及 HTTP 交付撤权、版本变化、审计脱敏/角色撤销/完整性异常。自动检查使用受控 API，不证明真实模型表达或正确性；本次实际运行结果另行记录。

本次本机 208 项主测试及 8 项 Part A 通过；需求同步、JavaScript 语法和 diff 检查通过。用户在前版的请求 `018271a8-03cd-43a2-bce8-ceb3ff039da0` 确认生成 API 正常，3 段复核为 supported/uncertain/supported，因此整篇拒答；本次调整解决该控制流，尚不能仅凭自动测试断言真实模型重答更正确。

单独调用复核的 9 个固定合成正反例在 `tests/fixtures/llm_review_cases.json`，含时间、状态、错引、同名、缺引、来源注入与审计脱敏。评测脚本允许复用当前 GLM，单独报告同模型评判的数量；默认 dry-run，无 API 调用：

```bash
.venv/bin/python scripts/evaluate_llm_review.py
# 已有 GLM 配置、决定消耗调用额度后（不要求另配复核型号）：
.venv/bin/python scripts/evaluate_llm_review.py --run-models --config .env
```

输出带分母的漏检/误拒数量、未成功的状态、调用/Token/耗时，不能把 9 个合成用例当生产准确率。规划开关的固定检索评测、五场景完整验收、新鲜度、来源撤权同步、费用和录制 Demo 仍待完成。新版隔离预览已启动，不代表真实模型质量通过，也没有推送或合并分支。

## gpushare 新版隔离预览（2026-10-11）

用户要求打开前端进行人工操作后，将 Git 提交 `1fa92b23` 的已跟踪代码打包至 `/hy-tmp/data_pyx/contextledger-integration/releases/llm-workflows-1fa92b23`；没有修改服务器原 Git checkout 或 main。新的预览进程 PID 为 4093059，仅监听服务器 `127.0.0.1:17861`；本机 SSH 转发 `127.0.0.1:17860 → 服务器 127.0.0.1:17861`，页面打开于 `http://127.0.0.1:17860/`。

复用原 `content`、Qdrant、`security-demo` 和 `preview-demo.env`，未重建索引或初始化账号。原 7860、服务器旧 17860 和 Qdrant 6335 均继续运行。新进程的 `APP_PUBLIC_URL` 是本机访问 URL 17860；`LLM_PLANNER_ENABLED/LLM_REVIEW_ENABLED=true`，型号默认复用基础 GLM。`/api/session` 已验证 planner/review 为 enabled、configured；浏览器已确认新规划开关、同模型提示、七账号和“让模型解释审计”入口。没有自动修改用户权限或触发真实模型问答。

若本机转发断开，先确认本机 17860 没有被占用，再恢复：

```bash
ssh -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
  -L 127.0.0.1:17860:127.0.0.1:17861 gpushare
```

服务器启动日志：`/hy-tmp/data_pyx/contextledger-integration/logs/llm-workflows-preview-1fa92b23.log`；203 项主测试日志同目录 `llm-workflows-regression-1fa92b23.log`。预览是本次代码快照，后续代码提交不会自动热更新。用户尚未完成完整验收，不能因页面可打开就标记模型功能 validated。
