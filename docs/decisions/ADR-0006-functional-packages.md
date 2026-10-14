# ADR-0006：按功能组织源码和测试

- 状态：Accepted（用户于 2026-10-14 确认）；实现和回归在独立工作分支，不自动合并。
- 关联需求：REQ-012/functional_package_refactor；沿用 REQ-001 至 REQ-020 的行为与安全边界。

## 决策

1. `contextledger` 是唯一业务包，按 application、access、ingestion、storage、retrieval、answering、radar、audit、interfaces、evaluation 分组。旧 `src` 的共享代码迁入对应包，不把业务实现堆进 scripts。
2. scripts 保留薄命令入口和独立运维/项目管理工具；排序、回放、评分等实现归入 evaluation。已公开的 CLI 命令保留兼容入口，共用同一实现，不复制代码。
3. tests 按功能组织；保留 unittest 递归发现和 pytest。Part A 的 autouse 测试分词器只影响其原有测试范围。
4. 删除旧 JSON 与 Streamlit 专用链路；共享回答 DTO、模型边界、审计哈希/解析仍保留。核心测试构造小样本，不读取已删除的 data。已有运行时内容、权限和审计数据库不迁移、不清空。
5. 目录重构不改变权限算法、模型配置、协议、数据库/向量格式；四来源/MCP 工作分支功能一并保留在本次工作分支，未完成的真实来源/企业认证验收仍未完成。

目录和回归范围见 [功能分包说明](../architecture/functional-packages.md)。
