# 聊天延迟对照

2026-10-14，REQ-018 / `chat_latency_experiments`，team_decision。只做隔离实验，不更改 Tailscale 在线服务或 ADR-0004 已确认的复杂问题 high 默认。真实模型、检索、权限与发布边界沿用 [聊天评测](chat.md)。

## 方法

```bash
.venv/bin/python scripts/evaluate_chat_latency.py \
  --source runtime/deploy/tailnet \
  --out runtime/chat-latency/NEW-UNIQUE-RUN \
  --env-file /absolute/private/model.env \
  --qdrant-url http://127.0.0.1:16339 --repeats 2
```

只允许固定的17份合成聊天 fixture。内容库和身份通过 SQLite backup 冻结到新目录，审计另建；原生 Qdrant collection 只读复用。MiniLM CPU，规划关闭，固定同一模型、temperature和当前引用／版本门闩。完整请求通过隔离回环 HTTP 执行，逐次计时检索、每个模型请求与工具展开；服务端格式修复、失败、拒答都保留。第一轮 A/B/C、第二轮 C/B/A，避免将先后服务波动直接当作参数收益。

三组为当前提示+high、增加简单事实直接回答提示+high、相同候选提示+low。6个案例、2轮，共36个观测：实名事实、无名称追问、双来源冲突、待审批、未知实体和越权。输出 `protocol.json`、原始 `results.jsonl` 和按案例/配置分组的 `summary.json`。每个模型请求记录输入hash、请求档位、实际模型、用量和耗时，不记录Key或隐藏推理正文。

`low`不是固定推理token数。实际效果取决于模型/提供方；OpenRouter公开目录对DeepSeek V3.2列出reasoning支持，但不列具体支持的effort档位。不能把通用文档中的百分比分配直接当作该模型保证。[OpenRouter reasoning文档](https://openrouter.ai/docs/guides/best-practices/reasoning-tokens)。`exclude=true`只是隐藏推理正文，仍可能执行推理，并不能用于提速。

## 实测与边界

首轮36个观测已完成，原始记录位于 `runtime/chat-latency/20261014-interleaved/`，审计链有效。需要分别核对事实/引用和工具行为：原始探测一度把预算冲突的Radar调用视为强制，通过已足够的两个来源直接回答因此被记为失败；当前协议没有要求每个冲突都强制工具调用。原始文件保留，统一重评分另存，不能覆盖或把工具策略探测当成答案错误。

原基线在新一轮中也能对无名称日期问题直接回答约3秒，并有一次不必要的证据不足；不能用昨天单次58秒与今天候选2秒直接声称29倍优化。新增提示让预算冲突稳定多走一轮工具、耗时上升，并出现一次漏引事实来源，不采用该提示作为线上默认。

固定复杂业务综合输入的 high/low/none 及严格 JSON 候选补充对照已完成，共14个阶段观测。它排除工具选择与检索，使用合成OrgForge业务材料与常量fixture向量冻结当前授权资料；该阶段耗时不能称为完整HTTP请求或生产检索表现。复杂关联/因果、正式状态/来源报告、修订/时间缺口仍需人工核对；小样本不能证明通用质量不下降。

## 分阶段结果

36次完整HTTP对照中，热态检索大多24～30ms，实际Radar工具约19～25ms；耗时主要在模型请求。首次基线检索包含MiniLM冷启动，因此不把首题差异当作提示词优化收益。所有观测和失败仍计入耗时分母。

统一事实／引用／版本评分为基线11/12、提示+high 11/12、提示+low 12/12；每组包含4个安全控制观测。原始评分32/36、移除非权威“冲突必须Radar”假设后的重评分34/36分别保存。省略名称问题基线有一次返回证据不足，固定夹具评分未通过；提示+high有一次漏引额度来源，不能推广为一般语义准确率。

预算冲突本轮基线直接回答3.57～4.24秒，候选提示+high走两次模型18.31～28.09秒，提示+low为12.95～20.73秒。加规则会改变工具路由，不仅影响简单事实；该提示未部署。

### 固定最后综合阶段

| 输入 | 请求档位 | 严格交付 | 阶段耗时（含已有格式重试） |
| --- | --- | --- | --- |
| 客户反馈→修复→收尾，37份资料 | high | 2/2 | 33.00～37.48秒 |
| 同一37份资料 | low | 2/2 | 31.31～34.81秒 |
| 同一37份资料 | none（实验） | 2/2 | 11.44～12.70秒 |
| 复盘／分区数，45份资料 | high | 1/2 | 36.06～80.54秒 |
| 同一45份资料 | low | 1/2 | 60.66～114.97秒 |
| 同一45份资料 | none（实验） | 1/2 | 13.35～25.15秒 |
| 同一45份资料 | high + JSON schema及参数路由 | 0/2 | 65.67～86.42秒 |

none实验通过实例属性覆写进行；生产配置校验仍不接受none，未改默认。每档只有两次；high/low为最多2个并发调用，none/schema运行每案只有1个在途请求，提供方路由未固定。输入和系统指令首轮hash相同，但这些样本不能证明仅推理档位带来相同幅度的线上稳定收益。模型格式修复后的提示不同，重试单独记录hash。

严格交付只检查当前格式／引用协议。人工阅读仍发现：部分high和none答案将部署消息说成已独立确认；none答案把两次不同根因处理描述为连续演变，或把不同阶段分区数直接称为确定冲突。low也有过度归因或遗漏来源支持的风险。37份资料中none虽更快，但尚未证明通用质量不下降；45份样例格式失败直接阻止全局采用。

JSON schema候选保留原验证并要求provider参数支持；两次都因invalid_json被安全降级，不能只根据目录支持就宣称该路径已可靠。路由和并发也与基线有差异。[官方结构化输出文档](https://openrouter.ai/docs/guides/features/structured-outputs)明确支持按endpoint而非仅模型判断，strict实施也因provider而异。

复现固定综合阶段：

```bash
.venv/bin/python scripts/evaluate_radar_latency.py \
  --out runtime/chat-latency/NEW-SYNTHESIS --env-file /absolute/private/model.env
# none及JSON schema是实验候选，不是部署设置
.venv/bin/python scripts/evaluate_radar_latency.py \
  --out runtime/chat-latency/NEW-NONE --env-file /absolute/private/model.env --efforts none
.venv/bin/python scripts/evaluate_radar_latency.py \
  --out runtime/chat-latency/NEW-SCHEMA --env-file /absolute/private/model.env \
  --cases recurrence --efforts high --schema
```

## 当前结论

优先减少不必要的工具展开和正文／关系重复，并提高大输入格式交付稳定性；再对不需要复杂推断的综合输入验证关闭推理的快路径。流式显示能改善看到首字的等待，但当前完整回答会在权限、版本及引用检查通过后交付，不能为展示速度提前放出未通过检查的事实。

本轮保留候选和未成功结果，不修改线上提示、推理档位或发布门闩。完整请求与固定阶段分开报告；后者常量向量只用于冻结材料。总体50个观测是开发排查，不是未见测试集或容量验收。HTML逐题报告在本机 `runtime/chat-latency/report-20261014.html`，固定输入、源码副本、诊断、语义阅读边界与原始失败都保留。
