# Decision Radar 业务材料 fixture

从固定 OrgForge 合成数据修订选择四个开发案例的业务材料，来源修订、完整源文件哈希、案例原生编号与记录数见 `manifest.json`。来源包括语料导出与 snapshot 的 Jira 描述／评论／最终状态、PR 描述／评审／最终状态、Slack、客户工单和复盘文档。它们是真实数据集记录，不是真实公司数据。

模型输入只经过业务字段允许列表。禁止 facts、ground_truth、causal_chain、recurrence_of、recurrence_gap_days 和评测答案字段；业务正文中的复发标签和当事人说法保留为来源报告。来源 date/day/timestamp 的不一致不校正。源定位和哈希可追溯。

ACL 为明确构造的工程／支持权限分组，不代表原平台 ACL。文本照常存储，查询时按可见编号展开；不用评测真值构造关系。完全相同的文本在工具展开时去重，同一源资源的不同表示或转发不作为独立支持。

```bash
.venv/bin/python scripts/radar_demo.py --output runtime/radar-replay-new
# 可选：读取现有 .env，默认以不带编号的项目名/业务词提问；产生 API 用量
.venv/bin/python scripts/radar_demo.py --output runtime/radar-live-new --live-llm
```

输出目录必须不存在。脚本使用真实本地 SQLite/Qdrant、常量 fixture 向量和显式权限，不重写现有 Part A 索引或身份。真实模型选项验证模型调用；常量向量不代表生产 Embedding 检索效果。

回放分三个观测阶段，原生最终正文没有初始历史时不提前暴露，未知状态变更时间保留为空。观测正文修订是重构实验记录，不能当作来源原生版本历史。当前实现以整快照发布阻断读取，失败后保持阻断；尚未实现生产细粒度增量发布。

带编号的回归问题可使用 --questions ids；默认 --questions names。名称实测使用真实模型翻译检索短语、英文关键词召回和真实关联工具，常量向量不作为语义检索质量证据。默认 RADAR_MAX_DOCUMENTS=120，可在40–300范围配置；达到其他轮数、扫描或正文预算仍会提示部分覆盖。
