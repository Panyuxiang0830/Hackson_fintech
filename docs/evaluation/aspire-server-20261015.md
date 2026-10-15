# Aspire 前端与服务器集成验证（2026-10-15）

用户要求：前端分支先提交 PR，不合并 main；以最新 main 与该前端的组合版本部署独立预览，复现 Radar 的 model unavailable，并保留浏览器供人工试用。

## 基线与初次检查

- main：9ad487ee09d1c0772f306c1f01d6e07fc9130413。
- 前端分支：feat/REQ-017-aspire-responsive-ui，原始 head e1f6c77b4df33220e853d0349b07f201db943738，已包含上述 main，没有合并冲突。
- PR #19 已创建为草稿，未合并。前端之外还包含语言、Radar展示及审计可见性适配。
- 初次本机 360 项 unittest 出现 2 项失败、4 项异常；其中两项为本机未安装 requirements-tools.txt 的 mcp 依赖，其余四项在 GitHub CI 复现。
- 四项 Radar 回归的模拟综合响应仍使用旧四字段回答，缺少现已必需的 radar_presentation。修复测试契约，不放宽实际回答、权限或引用校验。补充缺少展示字段时仍安全失败的回归。

## 本机修复后回归

- 按 requirements-tools.txt 补齐 mcp 依赖后，361 项 unittest 通过；pytest 369 项通过、142 个 subtests 通过。
- 22 项 Radar 定向回归通过，保留严格 presentation 契约与最多一次格式重试。

## 部署与实测

已在 gpushare 的独立 previews/aspire-ui-20261015 目录复制内容、身份与审计数据库，Qdrant 读取原已发布快照；原有工具服务和状态保留。模型连接探针 HTTP 200。

浏览器以 Jax 身份使用真实 MiniLM/Qdrant 混合检索和 GLM：
- TitanDB 用途问题 answered，5 条授权证据、2 次模型调用（包含一次可读性格式修正），未调用 Radar。
- ENG-195/PR-135 评审历史 answered，2 条证据、自动调用 Radar 一次，路由＋综合共 2 次模型调用；pending_confirmation，明确只有频道报告，原生状态与事件时间不完整。请求 41e63867-4ebe-46e5-bc56-7245b081ca08。
- 当前服务器没有 SG Batch Payments 文档（全库匹配 0）；首页原稿例题与实际导入语料不对应。

为避免把正常直接回答误读为模型故障，普通 answered 回答显示 Source-based answer；无证据和模型降级分别显示 Insufficient evidence / Model answer unavailable，只有实际 Radar presentation 才显示 Confirmed/Pending confirmation。首页例题改为当前 OrgForge 可检索的 TitanDB 与 ENG-195/PR-135；权限页复查复用首页例题，不再回退到不存在的 SG Batch Payments。页面布局不变，原始设计稿不改写。

这是受限小样本，不代表逐句语义验证或完整模型可靠性验收。

## 安全与接口实测

本轮在独立预览权限副本中检查：
- Jax 与 Ariana 的同题检索结果集合不同。
- Passport 原文接口 HTTP 200，原文 SHA-256 与证据指纹一致。
- 员工调用管理员接口为403。
- 未知实体返回 insufficient，零模型调用。
- 临时撤销 Jax 的 OrgForge 绑定后，搜索零证据、旧原文404、问答确定性安全提示且零模型调用。
- 管理员审计查询的链验证有效，当前无资料权限时问题、回答、证据与历史授权详情均隐藏。
- 操作结束已恢复预览副本原有绑定与限制；权限版本按真实操作增加。原服务权限库未修改。

更新例题和显示文案后再次运行：361项 unittest、369项pytest、142个subtests通过；生成前端构建和JS语法检查通过。CI及最终浏览器交付另核对。

## 最终交付状态

- gpushare 独立预览部署业务版本 5ebce039，地址经本机 SSH 隧道访问 http://127.0.0.1:17866/；原工具服务17864和Qdrant6335保留。内容为原45565篇文档的SQLite备份，Qdrant复用同一已发布真实384维MiniLM快照。
- 最终浏览器确认 Source-based answer 文案生效，Passport可打开真实原文；同一明确多状态问题第二次也自动触发Radar并返回Pending confirmation及两条来源事件，没有模型失败。
- 开启规划的简短评审问题发生 invalid_plan，安全回退原问题后 answered，但模型选择直接回答，没有调用Radar。本轮不把该回退计为规划质量通过，也不承诺每个问题都触发工具。
- PR #19 的代码版本5ebce039已获GitHub validate成功、CLEAN/MERGEABLE；main仍为9ad487e，未合并。
- 本机实际运行报告及截图位于忽略目录 runtime/aspire-ui-validation；服务器日志和复制的权限/审计状态位于独立 previews/aspire-ui-20261015。

收尾时检测到同分支新增 bb2ebb78 / fd5b0a2b，包含 Full answer 展开区和提交材料；已保留并同步静态资源，后端业务代码未变化。fd5b0a2b 的 GitHub validate 亦通过。此记录提交只补充验证文档。
