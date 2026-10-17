# Architecture 文档索引 / Architecture index

ContextLedger 的架构文档按关注点分组。先看总览，再按链路深入；
难以逆转的决策见 [ADR 列表](../decisions/)，完整项目地图见 [docs/README.md](../README.md)。

Design documents grouped by concern. Start with the overview, then follow
the pipeline; hard-to-reverse choices live in the [ADRs](../decisions/).

## 总览 Overview

| 文档 | 内容 |
| --- | --- |
| [integration-plan.md](integration-plan.md) | 两套实现的现状盘点与统一集成目标架构 |
| [unified-integration.md](unified-integration.md) | 集成版实际实现边界、配置、启动与人工验收 |
| [functional-packages.md](functional-packages.md) | `contextledger/` 功能分包布局、模块职责与主链路（REQ-012） |

## 摄取与索引 Ingestion & indexing

| 文档 | 内容 |
| --- | --- |
| [index-and-freshness.md](index-and-freshness.md) | 索引分工、内容版本、新鲜度与安全索引发布 |
| [source-and-agent-interfaces.md](source-and-agent-interfaces.md) | Jira / Slack / Confluence / Drive 只读适配、来源权限快照、MCP stdio 与工具凭据 |

## 权限 Permissions

| 文档 | 内容 |
| --- | --- |
| [permission-interfaces-v2.md](permission-interfaces-v2.md) | 五种确定性权限接入模式与统一契约（Slack / 项目 / 密级 / 部门 / POSIX） |
| [ADR-0007](../decisions/ADR-0007-permission-provider-contract.md) | 多模式权限接入的 Proposed 架构决策 |

产品侧权限说明：[project-permissions](../product/project-permissions.md) ·
[resource-permissions](../product/resource-permissions.md) ·
[demo-acceptance](../product/demo-acceptance.md)

## 检索与回答 Retrieval & answering

| 文档 | 内容 |
| --- | --- |
| [query-planning.md](query-planning.md) | 受限问题规划、FTS/Qdrant 分流与纠错确认 |
| [llm-workflows.md](llm-workflows.md) | 规划 / 审计 / 回答的有界模型链路、配置预算与安全检查 |

## Decision Radar

| 文档 | 内容 |
| --- | --- |
| [decision-radar-v1.md](decision-radar-v1.md) | 最终方案：内部自动工具调用、实体展开、事实可靠性与四案例回放 |
| [decision-radar-validation.md](decision-radar-validation.md) | 实施与验证：接口兼容、实验与剩余质量限制 |
| [radar-reasoning-comparison.md](radar-reasoning-comparison.md) | Radar 综合阶段的推理模型比较与路由 |
| [ADR-0004](../decisions/ADR-0004-decision-radar.md) | Accepted 的自动内部 Radar 工具决策 |

## 审计 Audit

| 文档 | 内容 |
| --- | --- |
| [audit-query-flow.md](audit-query-flow.md) | 合规审计查询流程与时间条件 |

产品侧：[audit-console-v2-plan](../product/audit-console-v2-plan.md)（四区审计工作台）

## 部署与预览 Deployment

| 文档 | 内容 |
| --- | --- |
| [tailnet-preview.md](tailnet-preview.md) | 私有 Tailscale 浏览器试用的入口、安全边界与常驻服务维护 |

## 架构决策记录 Decisions (ADRs)

| ADR | 决策 |
| --- | --- |
| [ADR-0001](../decisions/ADR-0001-repository-as-source-of-truth.md) | Git 仓库为唯一事实源 |
| [ADR-0002](../decisions/ADR-0002-unified-entry-and-trusted-identity.md) | 统一入口与可信身份 |
| [ADR-0003](../decisions/ADR-0003-tool-first-and-deferred-browser-login.md) | Tool 优先，浏览器登录延期 |
| [ADR-0004](../decisions/ADR-0004-decision-radar.md) | Decision Radar 内部自动工具 |
| [ADR-0005](../decisions/ADR-0005-source-adapters-and-mcp.md) | 来源适配、宿主模型优先 MCP 与凭据边界 |
| [ADR-0006](../decisions/ADR-0006-functional-packages.md) | 按功能分包 |
| [ADR-0007](../decisions/ADR-0007-permission-provider-contract.md) | 多模式权限接入契约（Proposed） |
