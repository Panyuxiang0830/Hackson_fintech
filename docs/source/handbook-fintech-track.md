# FinTech Track Handbook 要求基线

> 来源：用户提供的 Hackathon Handbook 中 “The FinTech Track - Aspire” 摘录。
> 入库日期：2026-09-29。
> 版本说明：2026-10-15 已复核用户提供的完整43页PDF，第14–20页为FinTech案例，第37页为提交要求；PDF未显示明确版本发布日期。提交字段详见 [最新核对](submission-requirements-20261015.md)。

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

## 2026-10-15：目标用户与痛点的完整 Handbook 依据

第14页给出Aspire赛道背景；第15–16页描述Company A的企业知识场景：Confluence超过50个空间及12,000页、Jira超过30个项目、Slack超过200个频道，以及共享/个人Google Drive。约30%的工作周用于找资料是赛题给定估计，不是ContextLedger节省时间的实测结果。

明确用户包括事故响应/后端工程师、初级员工、外部承包商、管理员和合规人员。项目/运营同事是从项目状态、审批和跨来源讨论场景合理延伸的受众，不冒充已经完成用户访谈。痛点是资料与上下文分散、来源权限语义不一致、更新/撤权后旧状态继续影响答案、无依据补全及缺乏可重建的审计证据。

报告依第18–19页逐项提供统一问答、新鲜度、无权限不泄漏、撤权和审计的worked example，遵守第14页开头声明唯一案例的要求。第37页已确认的标题、简介、四部分说明、至少3份真实开发聊天及16:9封面，不再列为未知。视频为Optional，如提交应为5–8分钟；项目链接亦为Optional。
