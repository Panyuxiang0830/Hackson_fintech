# 有界模型链路实施说明

2026-10-11，`codex/llm-workflows`。复用 Part A 事实库、Qdrant/FTS、身份权限库和审计链；不改索引格式、不需要为本次模型功能重建索引。登录/Tool 仍延期，四个平台真实增量同步和新鲜度闭环仍未实现。

## 当前代码已接的链路

业务请求：可信会话与当前权限 → 固定索引快照 → 可选规划 → 原问题＋有限分支的授权检索 → 文档 RRF 去重 Top-5 → 再次检查 → 回答生成及编号校验 → 独立复核 → 权限/版本交付检查 → 页面与审计。

审计请求：admin/compliance → 确定性条件查询与哈希链验证 → 当前业务权限脱敏/白名单投影 → 最多 20 个事件给模型 → `[E序号]` 校验与独立复核 → 再次验证角色、证据和链 → 交付及追加审计。未复核草稿不写进最终回答记录。

实现集中在 `contextledger/llm_workflows.py`，由 `unified_service.py` 编排。规划与复核没有检索工具、SQL 或身份接口。API：`/api/search`、`/api/ask` 支持 planning 开关；新增 CSRF/角色受控的 `POST /api/audit/ask`；旧 `GET /api/audit` 保留确定性查询。

## 配置和状态

复制 `.env.integration.example` 的字段至忽略的运行配置，不在聊天或 Git 中粘贴 Key。

- 回答继续使用 `LLM_MODEL`；规划和审计型号分别用 `LLM_PLANNER_MODEL`、`LLM_AUDIT_MODEL`，省略时复用回答型号。各阶段的 `BASE_URL/API_KEY/REASONING_EFFORT` 可独立配置；省略/空的地址与 Key 复用基础配置。
- `LLM_PLANNER_ENABLED` 的代码默认 false，示例配置为 true。页面复选框可开启或关闭；关闭用于原问题基线。配置缺失、超时或计划不合规都回退原问题，不放宽权限。
- `LLM_REVIEW_ENABLED` 默认 true。必须填写**不同且已开通**的 `LLM_REVIEW_MODEL`。未配置、配置同型号或服务返回同实际型号，均不能通过；保留授权证据、返回安全提示，不交付草稿。false 仅用于明确标记 disabled 的未复核基线，不等于已确认。
- 页面显示 planning/review 的实际状态：supported、unsupported、uncertain、not_configured、same_model_rejected、api_unavailable、disabled、not_reviewed_mock、not_required。supported 是模型辅助判断，不是事实证明。实际型号别名是否真正独立仍需运营方确认，不能仅因字符串不同就保证能力/错误独立。
- `scripts/sync_preview_config.py` 已扩充白名单，可同步这些运行配置，继续不打印凭据；本次没有执行远程同步或部署。

## 输入、输出与预算

| 阶段 | Prompt 版本 | 输入/输出上限 | 单请求调用 |
|---|---|---|---|
| 规划 | query-plan-v1-2026-10-11 | 原问题；3 子问题、3 语义句、8 关键词、2 候选；900 输出 Token | 0/1 次，15 秒网络超时 |
| 生成 | answer-v7-2026-10-11 | 原问题＋Top-5，每段最多 4000 字符；1600 输出 Token | 最多 2 次，30 秒网络超时/次；只有格式失败重试 |
| 审计生成 | audit-answer-v1-2026-10-11 | 最多 20 可见事件、事件 JSON 总计 ≤40000 字符；1600 输出 Token | 0/1 次，20 秒网络超时 |
| 复核 | citation-review-v1-2026-10-11 | 原问题、未交付回答、实际输入证据；最多 24 段；2400 输出 Token | 0/1 次，20 秒网络超时 |

新阶段 JSON 输入总计 ≤60000 字符、HTTP 响应 ≤128 KiB。字符限制不是精确输入 Token 预算；网络超时不是完整链路的 SLA。正常业务最多规划一次＋生成两次＋复核一次（最多 4 次），正常审计最多 2 次；不无限重试。返回安全状态、耗时、模型、参数、Prompt 版本与平台报告的 Token 用量，不保存 Key、原始异常或失败草稿。币种费用和真实链路延迟仍待测。

模型计划字段严格校验，原问题不变；关键词必须出自原问题，扩展实体不能静默替换，显式数字/日期/否定不允许被删除。不同实体的子问题可以分别检索；不清楚的纠错只请求确认。所有分支使用同一 ACL/快照，最多 5 个分支、每路 Top-5，RRF 融合总 Top-5；原问题始终保留。只依据词法保护并不能证明语义完全不变，最终回答仍按原问题和证据核对，路由收益待评测。

复核模型收到 server-defined 的完整段落列表，必须逐段返回 supported/unsupported/uncertain 和精确摘录。服务端核对段落覆盖、实际引用集合和摘录在原输入中存在。**摘录存在仍不能证明语义支持**：同名、数字和状态矛盾需要模型/人工判断。不支持/不确定/不合规/不可用均不展示原草稿。模型自称 insufficient 的未核对事实也不直接展示，改用服务端安全提示。

审计模型只读事件白名单元数据及可见 query/answer 的截断内容，不读任意 extras、旧计划或全库标题；无业务权限时问题/回答/证据脱敏。证据总数可见性遵循脱敏；真实零返回可以记录 returned_evidence_count=0。结果部分截断会由服务端追加范围警告，无匹配不证明从未访问。审计模型只摘要既有安全查询结果，不能代替合法的条件解析。

## 测试与尚未验证项

`tests/test_llm_workflows.py` 和 `tests/test_llm_integration.py` 使用真实本地 Qdrant/SQLite、合成语料及受控 API 返回，验证调用顺序、各路 ACL、模型前后/HTTP 交付撤权、版本变化、完整性异常、脱敏、错误摘录/引用、覆盖缺失、预算、失败降级和零证据。**不证明真实模型遵守 Prompt、规划提高 Recall，或复核错误率可接受。**

本次本机回归：`unittest discover -s tests` 199 项、`pytest tests_part_a` 8 项全部通过；需求同步检查、JavaScript 语法检查与 `git diff --check` 通过。测试中的模型响应由受控替身提供，没有调用真实付费模型，也没有更新 gpushare。

独立复核的 9 个固定合成正反例在 `tests/fixtures/llm_review_cases.json`，含时间、状态、错引、同名、缺引、来源注入与审计脱敏。评测脚本默认 dry-run，无 API 调用：

```bash
.venv/bin/python scripts/evaluate_llm_review.py
# 明确配置不同模型并决定消耗调用额度后：
.venv/bin/python scripts/evaluate_llm_review.py --run-models --config .env
```

输出带分母的漏检/误拒数量、未成功的状态、调用/Token/耗时，不能把 9 个合成用例当生产准确率。真实模型选型、规划开关的固定检索评测、五场景完整验收、新鲜度、来源撤权同步、费用和录制 Demo 仍待完成。当前服务器页面仍是旧版；本机测试通过后也不会自动合并或部署。
