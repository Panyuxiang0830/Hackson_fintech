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

独立服务器预览和真实模型诊断进行中，结果补充于此。不得以未完成记录宣称通过；原索引、权限库、审计和工具服务保留。
