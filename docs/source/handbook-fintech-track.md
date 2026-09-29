# FinTech Track Handbook 要求基线

> 来源：用户提供的 Hackathon Handbook 中 “The FinTech Track - Aspire” 摘录。
> 入库日期：2026-09-29。
> 版本说明：摘录中未显示 Handbook 版本号或发布日期；若比赛邮件或提交表出现更新，以更新后的官方材料为准。

## 选定案例

本项目只选择以下一个案例：

> The Internal Brain – Building a Context-Aware Enterprise Knowledge System with RBAC, Security Logging & Audit Trail

Handbook 明确要求每队只选择一个案例，并在 Presentation 开头写明所选案例。

## 产品硬性能力

以下内容在 Challenge、`must` 条款或 “What the Solution Should Solve” 场景中有明确依据，作为项目的强制产品需求：

1. 集成 Confluence、Jira、Slack、Google Drive 四类异构来源，不能抹平各来源不同的权限语义。
2. 查询时识别用户身份和权限，在内容进入 LLM 前完成权限过滤。
3. 权限撤销后，后续查询不得继续返回旧权限下可见的内容。
4. 跨平台检索、排序和上下文组装必须对每条证据分别执行权限控制。
5. 数据更新必须在有界且可预测的窗口内进入答案；Handbook 给出的量级为数分钟至约一小时。
6. 审计记录必须防篡改、完整且可查询，覆盖身份、查询、检索文档 ID、最终回答、时间和逐文档授权决定。
7. LLM 必须降低幻觉、训练记忆泄漏和无证据补全的风险。

## 必须可演示的五个场景

Handbook 要求提交材料为每个场景提供 worked example：

1. 带来源引用的统一自然语言问答；
2. 数据新鲜度；
3. 无权限用户的负面案例，且不能通过元数据暗示受限内容存在；
4. 权限实时撤销；
5. 合规人员进行审计查询。

这些能力分别映射到 `project/requirements.json` 中的 REQ-001 至 REQ-009。

## 交付材料的解释边界

摘录包含 “The Solution Should Include”：

- live demo walkthrough；
- architecture / trust-boundary diagram / design trade-offs；
- complete source code through a GitHub repository。

但摘录结尾同时说明所列 features 是 guidance，且目前没有掌握登录后提交表的完整字段。因此团队会准备上述材料，但在进一步核实前，不把下列细节写成官方硬性要求：仓库是否必须公开、视频格式与时长、在线部署链接、Pitch Deck 页数、正式报告、指定腾讯产品和具体合规格式。

相关待确认项统一记录在 `docs/source/submission-open-questions.md`。

## 明确排除的模板污染

Handbook 摘录中的 “Help patients”“medications”“self-care”等医疗健康表述与 FinTech Internal Brain 案例不一致，明显属于其他赛题的模板内容。本项目不把该段作为需求，也不据此实现医疗功能。
