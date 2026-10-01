# ContextLedger MVP v0 开发规格

> 版本：v0  
> 日期：2026-09-28  
> 目标：先完成一个可运行、可演示、可测试的最小闭环，再逐步增加真实连接器、时序冲突检测与高级评测。
>
> 本文是团队内部产品规格，不代表官方提交格式。官方要求以 `docs/source/handbook-fintech-track.md` 和 `project/requirements.json` 为准。

## 1. MVP 的唯一目标

证明下面这条链路真实成立：

```text
选择员工身份
-> 输入自然语言问题
-> 在检索前执行权限过滤
-> 只使用允许访问的证据
-> 生成带引用的回答
-> 保存审计日志
```

MVP 不追求“企业万能知识大脑”，只证明以下三个核心价值：

1. 同一个问题，不同员工得到不同但正确的答案；
2. 无权限文档不会进入模型上下文；
3. 每次回答都能解释“用了哪些证据、为什么允许访问”。

## 2. Demo 故事

业务故事：**SG Batch Payments v2.3 上线与事故调查**。

统一问题：

> SG Batch Payments v2.3 是否已经正式上线？最近失败事故的原因是什么？我们现在能否向客户确认服务已经恢复？

四种身份：

| 身份 | 部门 | 可见范围 | 预期结果 |
|---|---|---|---|
| Alice | Engineering | 技术设计、Jira、事故日志、公开政策 | 得到技术根因和发布状态 |
| Bob | Operations | 客户影响、SOP、对外话术、正式发布状态 | 得到运营答案，但看不到敏感实现 |
| Carol | Compliance | 审批、控制项、政策、正式发布状态 | 得到合规证据，但看不到无关工程细节 |
| Dave | Contractor | 仅公开/普通内部材料 | 敏感问题被拒绝或只返回低敏感信息 |

## 3. MVP 数据

先准备 12–16 条人工审核过的合成记录，不追求规模。

建议组成：

- 3 条 Jira：需求、上线审批、事故修复；
- 4 条 Slack：上线通知、错误猜测、事故讨论、恢复确认；
- 3 篇 Confluence：功能说明、运行手册、事故复盘；
- 3 份 Drive 文档：合规政策、上线审批、客户沟通模板；
- 2 条 Release Registry：部署与恢复事件。

每条记录必须包含：

```json
{
  "id": "jira-001",
  "source": "jira",
  "title": "Batch Payments v2.3 Release Approval",
  "content": "...",
  "created_at": "2026-09-20T09:00:00+08:00",
  "updated_at": "2026-09-20T09:30:00+08:00",
  "classification": "confidential",
  "allowed_departments": ["engineering", "compliance"],
  "allowed_roles": ["engineer", "engineering_manager", "compliance_officer"],
  "project": "payments-sg",
  "status": "approved"
}
```

第一版只实现：

- `allowed_departments`
- `allowed_roles`
- `classification`
- `project`

暂不实现复杂上下级继承和地区监管规则。

## 4. MVP 页面

使用一个页面完成演示：

### 左侧：身份

- 当前用户下拉框；
- 显示部门、角色、项目和 clearance；
- 提供 Alice、Bob、Carol、Dave 四个固定用户。

### 中间：提问与回答

- 问题输入框；
- 三个预设问题按钮；
- 回答正文；
- “证据不足”或“权限不足”的明确状态。

### 右侧：Evidence & Audit

- 本次使用的证据；
- 来源、标题、更新时间、敏感级别；
- 为什么允许访问；
- 被权限层排除的文档数量，只显示数量，不泄漏标题；
- request ID 和审计记录。

## 5. MVP 请求流程

```text
1. UI 提交 user_id + question
2. IdentityService 在请求时重新读取当前用户属性
3. PolicyEngine 对全部文档做确定性过滤
4. FreshnessService 排除已知源版本更新但索引尚未同步的文档
5. Retriever 只在允许且未过期的文档里检索
6. AnswerService 将允许的证据交给 LLM
7. LLM 返回答案和引用编号
8. 系统校验引用只能来自允许且未过期的证据
9. AuditService 写入完整事件、前序哈希和事件哈希，并更新 head checkpoint
10. UI 展示回答、引用、权限摘要和审计链状态
```

安全不变量：

> 未授权或已知过期的文档不能出现在 Retriever 候选、LLM Prompt 和引用结果中。普通请求者只能看到拒绝数量；逐文档允许/拒绝决定只进入受保护的合规审计记录。

## 6. 推荐技术栈

为了尽快完成第一版：

- Python 3.12；
- Streamlit：单页 Demo UI；
- dataclasses：用户、文档和请求模型；
- JSON：模拟用户和知识数据；
- Python 内存检索：第一版使用关键词/TF-IDF；
- JSONL + SHA-256 hash chain：append-only 审计日志；
- unittest：权限、泄漏、篡改、审计查询和新鲜度测试；
- LLM Adapter：支持 `mock` 与一个 OpenAI-compatible API。

选择 Streamlit 的原因：

- 一两天内能形成完整交互；
- 不需要同时维护前后端；
- 适合黑客松早期验证；
- 后续如果 UI 成为短板，再迁移到 React/Next.js。

第一版不需要：

- PostgreSQL；
- Vector Database；
- 微服务；
- Kubernetes；
- 多 Agent 框架；
- 真正的 Slack/Jira OAuth；
- Lamport/Vector Clock；
- 完整企业登录系统。

## 7. 代码结构

```text
hackson/
├── app.py
├── README.md
├── requirements.txt
├── .env.example
├── data/
│   ├── users.json
│   └── documents.json
├── src/
│   ├── models.py
│   ├── identity.py
│   ├── freshness.py
│   ├── policy.py
│   ├── retrieval.py
│   ├── answering.py
│   ├── audit.py
│   ├── audit_query.py
│   └── service.py
├── tests/
│   ├── test_audit.py
│   ├── test_audit_query.py
│   ├── test_policy.py
│   ├── test_permission_freshness.py
│   ├── test_no_leakage.py
│   └── test_end_to_end.py
└── runtime/
    ├── audit-v2.jsonl
    └── audit-v2.head.json
```

## 8. 团队内部最小验收标准

MVP 完成必须同时满足：

### 功能

- 可以切换四个用户；
- 可以输入自由问题；
- 可以得到带引用的答案；
- 同题不同身份结果不同；
- 无权限时明确拒绝或只回答允许部分；
- 每次请求产生完整且可验证的审计记录；
- Compliance 可以按自然语言或结构化条件查询审计事件；
- 权限撤销对下一次请求立即生效；
- 已知过期版本不会进入检索。

### 安全

- Contractor 的检索结果中不出现 restricted 文档；
- Contractor 的 LLM Prompt 中不出现 restricted 内容；
- 返回引用只来自允许文档；
- 被排除文档只显示数量，不能显示标题；
- 修改或删除审计事件会导致完整性验证失败；
- 权限测试全部通过。

安全的篡改演示使用临时日志，不会修改真实运行记录：

```bash
python3 scripts/demo_audit_tamper.py
```

### 可演示性

- 新电脑按照 README 可以启动；
- 无 API Key 时使用 mock answer 仍可完整演示；
- 配置 API Key 后使用真实 LLM 总结；
- 团队目标是在三分钟内完成一次核心链路 Demo；这不是已确认的官方演讲时长。

## 9. 暂时不做什么

以下能力全部推迟，防止 MVP 失控：

- 真实第三方 SaaS Connector；
- 复杂部门层级和上下级权限；
- Temporal-Authority Conflict Engine；
- 逻辑时钟；
- 自动同步和文档更新；
- 向量检索和 Knowledge Graph；
- 管理后台；
- 多轮会话记忆；
- 完整 Prompt Injection 防护；
- 云端正式部署。

## 10. 迭代路线

### v0：权限感知问答闭环

- 合成数据；
- 四个身份；
- 权限先过滤；
- 带引用回答；
- 审计日志。

### v0.1：真实 LLM 与基础评测

- 接入一个模型 API；
- 建立 20–30 个 ground-truth 问题；
- 测试回答、引用和拒绝行为。

### v0.2：检索增强

- Embedding / Hybrid Search；
- 文档切片；
- reranking；
- 引用质量评测。

### v0.3：冲突检测

- 文档版本；
- authoritative source；
- 业务状态机；
- Temporal-Authority Conflict Engine；
- 再评估是否加入 Vector Clock。

### v0.4：安全红队

- Prompt injection；
- 多轮拼接泄密；
- 权限撤销；
- 会话缓存泄漏；
- 审计日志脱敏。

### v0.5：真实连接器与展示优化

- 选择一个真实 Connector；
- 改进 UI；
- 添加 ROI 页面；
- 根据最终提交表决定是否制作 Demo 视频和 Pitch Deck；当前先积累演示素材。

## 11. MVP 开发顺序

严格按以下顺序开发：

1. 数据模型；
2. 合成用户和文档；
3. Policy Engine；
4. 权限单元测试；
5. Retriever；
6. Answer Service；
7. 审计日志；
8. Streamlit UI；
9. 端到端测试；
10. 接入真实 LLM。

不要从 UI 或多 Agent 开始。核心风险是权限是否真的在检索前生效。

## 12. 第一轮 Demo 脚本

1. 选择 Alice（Engineer），询问统一问题；
2. 展示技术根因、Jira 和事故复盘引用；
3. 切换 Bob（Operations），重复相同问题；
4. 展示客户状态和 SOP，说明工程机密未进入上下文；
5. 切换 Dave（Contractor），再次提问；
6. 系统拒绝敏感部分；
7. 打开 Audit 区域，展示三个请求的角色、允许证据数和拒绝结果。

这条链路跑通后，MVP v0 即完成。
