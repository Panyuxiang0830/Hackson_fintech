# 功能分包重构（REQ-012）

本轮是目录与测试组织重构，不是新的权限算法或数据库迁移。工作基线为 main `bf57bebf` 加四来源/MCP 分支 `f590ba83`；保留现有前端与服务。

## 目标

```text
contextledger/
  application/  统一请求编排
  access/       身份、来源 ACL、撤权与工具凭据
  ingestion/    适配、解析、清洗、分块
  storage/      原文、版本、发布锁与更新任务
  retrieval/    FTS、向量与过滤
  answering/    回答、受限模型阶段与证据 DTO
  radar/        查询时业务演变工具
  audit/        审计记录、哈希与查询解析
  interfaces/   Web、MCP、CLI 与页面资源
  evaluation/   固定样例、排序、回放与延迟测量
tests/          与功能包对应的小样本测试
fixtures/       固定业务回放资料（不是旧 JSON 运行数据）
scripts/        命令入口及独立运维/项目工具
```

`data/documents.json`、`data/users.json` 和旧 Streamlit 演示专用链路将退出本轮；不会删除未跟踪的大数据，或服务器的原文、向量、身份、审计状态。共享回答与审计边界继续回归；测试数量变化必须解释其来自旧链路删除还是新增覆盖。

迁移后会在本文件补齐兼容入口与实际回归结果。真实模型、来源平台及生产环境验证不由目录重构回归替代。
