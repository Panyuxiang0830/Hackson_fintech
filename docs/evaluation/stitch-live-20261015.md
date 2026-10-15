# Stitch 定稿前端真实模型冒烟测试

日期为2026-10-15，代码基线为 c7a7967。用户更新本机私有 .env 中的密钥后，NUS 网关实际生成接口返回200；配置为 openai_compatible / glm-5.3-flash。密钥未写入报告、日志或版本库。本地预览已改为读取当前项目的 .env。

## 本次范围

使用已定稿前端、实际浏览器点击、真实同源 /api/ask 与 /api/doc、当前员工身份和本地导入 OrgForge 资料（143条）。没有替换服务器或模型响应。浏览器请求选择 keyword 模式、planning=false；现有预览的二维向量属于测试夹具，本轮不评测语义向量召回、真实来源同步或规划收益。没有修改现有资料或员工权限。

| 场景 | 结果 | 端到端耗时 | 模型调用 |
| --- | --- | --- | --- |
| What is ENG-195 intended to do? | answered；5条授权证据；英文回答 | 3.856秒 | 2次，首次分段校验失败后格式修正 |
| ENG-195 / PR-135 review history, ticket and merge states, remaining confirmation | answered；14条授权证据；Pending confirmation | 25.401秒 | 3次，包括路由、综合及一次综合格式修正 |
| NonexistentProbeZXQ731 approval status | insufficient；空证据、无引用 | 0.210秒 | 0次 |

两项生成回答的实际 provider 均为 openai_compatible/glm-5.3-flash，未使用 mock_fallback。共5次应用模型调用，用量17994 tokens（普通回答4691、Radar13303），包括格式修正；不含独立连接探针。没有价格信息，不推算金额，也不从两条生成样本计算稳定p95。

## 回答与证据检查

普通回答识别出 ENG-195 的 SwiftUI telemetry dashboard 工作。Radar 区分当前工单 Done、PR merged、未知状态切换时间、未证实的生产部署，以及未确认关闭的知识缺口。上述是模型根据本次有界资料生成的判断，不是独立事实背书。

两项生成回答的引用编号均属于当前授权证据；均从实际界面打开 Evidence Passport，/api/doc 返回200且 available=true；原文哈希与问答证据哈希相等，并重新计算正文SHA-256核对。页面无JavaScript异常。未知实体正常拒答，未调用生成模型。引用编号和哈希检查不证明每一句话的语义正确性。

首次失败被保留：普通回答 readability_validation_failed，Radar invalid_output；均由既有一次格式修正机制完成，没有另跑成功样本替换失败记录。完整的原始回答、诊断、token用量、请求ID、证据版本和截图位于本机忽略目录 runtime/live-llm-20261015/，results.json 为本次三项结果。browser-test.cjs 只调整实际请求的检索模式，使用 route.continue，不提供模拟响应。

## 复现

先配置本机 .env 的 LLM_PROVIDER、LLM_BASE_URL、LLM_MODEL、LLM_API_KEY，并启动当前隔离预览。浏览器使用当前员工查询上述原问题，关闭Query planning，测试脚本以keyword请求实际API；不要用名称不同的首页示例问题替代ENG-195资料。普通对话不继承上一题实体。

本轮不更改已定稿的页面设计，也不将冒烟结果标记成完整质量、向量检索、企业权限或生产验收。
