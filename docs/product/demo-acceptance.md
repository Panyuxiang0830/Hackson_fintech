# 隔离演示前端验收

关联：REQ-016、REQ-017，复用既有权限、回答与审计要求。工作分支 `codex/REQ-017-unified-integration`，未经用户验收不合并 main。

这是演示模式，不是真实登录。身份切换入口仅在显式启用的回环／SSH 预览中存在；任何能访问该端口的人都可以选择演示管理员，不能公开部署，也不能放入真实公司资料。普通模式默认关闭此入口、拒绝未验证业务请求。界面与审计均明确标记 `isolated_demo`。

## 账号与权限

管理员为独立“ContextLedger 管理员”，不借用数据集员工，默认无来源绑定；管理角色不意味着能读全部原文。六个员工的系统角色均为 member，显式绑定来源身份的 ACL，不通过系统角色伪造来源角色。

gpushare 演示初始化选择如下，绑定依据仅为合成数据演示，不代表真实企业身份核验：

| 系统显示名 | 来源身份 | 部门 |
|---|---|---|
| Jax（演示员工） | orgforge:Jax | 后端工程 |
| Alex（演示员工） | orgforge:Alex | 移动工程 |
| Chris（演示员工） | orgforge:Chris | 产品 |
| Ariana（演示员工） | orgforge:Ariana | 销售／市场 |
| Ben（演示员工） | orgforge:Ben | 测试／支持 |
| Karen（演示员工） | orgforge:Karen | 人力／运营 |

管理员可停用账号、撤销来源绑定、修改角色与密级、增加平台／项目／部门／文档／数据集的本地拒绝。删除拒绝规则不能超出已绑定来源 ACL；新增来源身份绑定可能扩大权限，必须明确确认依据。管理员审计页面可核对事件、用户、请求 ID、provider 与完整性；没有对应资料权限时，问题、回答与证据会脱敏，这是正常行为。

## 初始化与启动

先完成 Part A 导入和集成 Qdrant 索引发布。不要在已有生产／旧安全目录上初始化演示账号；使用新的、位于内容目录之外的 `security-demo`。

```bash
bash scripts/integration.sh --out runtime/part_a --security-dir runtime/security-demo demo-init \
  --bind orgforge=orgforge:Jax --bind orgforge=orgforge:Alex \
  --bind orgforge=orgforge:Chris --bind orgforge=orgforge:Ariana \
  --bind orgforge=orgforge:Ben --bind orgforge=orgforge:Karen

APP_PUBLIC_URL=http://127.0.0.1:17860 BROWSER_LOGIN_ENABLED=false \
  bash scripts/integration.sh --out runtime/part_a --security-dir runtime/security-demo \
  serve --demo --host 127.0.0.1 --port 17860
```

同一目录重复初始化只校验名单，不恢复绑定或本地拒绝。更换名单需另用空目录，不删除旧审计。索引重建不能删除独立安全状态。`serve --host 0.0.0.0` 不允许演示模式；不信任代理提供的客户端地址。

服务器模型配置通过 SSH 安全同步，只传 LLM 与演示白名单配置，不传 Auth0、其他 API Key 或本机应用 Secret。新应用 Secret 独立生成，保存在权限为 0600 的运行时配置；`CONTEXTLEDGER_ENV_FILE` 指向该文件。不要将配置或运行时审计加入 Git。

离线 Embedding 还须指向服务器现有缓存。同步配置时用 `--hf-home /hy-tmp/data_pyx/contextledger-part-a/hf-cache` 显式指定服务器路径，不复制本机 HF_HOME，不重新下载模型。缓存缺失时语义／混合检索拒绝请求，不回退为无权限过滤的全库检索。

## 人工走查

1. 打开 `http://127.0.0.1:17860/`，选择 Jax，点击“切换演示身份”。确认显示 member、权限版本和 orgforge。
2. 搜索 `TitanDB`，点击证据查看原文；切换 Alex 或 Ariana 再搜相同问题，对比实际授权证据 ID，而不是只比答案文字。
3. Jax 提问 `What is TitanDB and what is it used for? 请用中文依据证据回答。`，点击“生成回答”。核对 provider 为 `openai_compatible/glm-5.3-flash`；Mock／mock_fallback 不能算真实 API 验收。展开 `[1] [2]` 对应证据；编号校验不等于逐句语义证明。也可测试“TitanDB 当前有哪些进展和问题？请依据证据回答”：2026-10-07 自动走查时召回多为标题／索引片段，模型拒答，这是仍需评测的召回质量限制，不能算本题质量已通过。
4. 复制回答显示的请求 ID，切换管理员，在审计条件粘贴请求 ID，点击“查询审计与完整性”。核对 answer 事件、用户、provider、permission_epoch、identity_mode 和 integrity.valid。管理员无业务绑定时回答脱敏，不能为了看明文而取消脱敏检查。
5. 管理员选择 Jax。来源身份默认对齐其已有绑定；选择平台拒绝、输入先前实际出现的平台名（例如 slack），点击“增加拒绝规则”。切回 Jax，重新搜索、生成回答和打开先前的对应原文，不应交付被撤销的平台证据；其他员工不受影响。
6. 管理员移除刚加的本地拒绝，再核对恢复仍受原来源 ACL 限制。撤权、恢复及后续查询应在审计链中出现。需要全部撤权时用“撤销来源身份”或“停用账号”。

前端轮询权限变化并清空旧展示，但已交付到用户的内容不能追回。新鲜度只证明相对已知离线快照一致；来源实时同步、完整版本回滚、生产认证与完整质量／规模评测没有因此完成。

## 中文查询与失败回归（2026-10-07）

- 测试 `TitanDB是做什么的` 与 `介绍TitanDB`：中英文边界分词，保留精确实体；Qdrant 仍带权限过滤，重新选择同一授权文档内更有实质内容的分块。
- 测试 `TibanDB是做什么的`：未找到该实体时不强行使用最相近的无关资料、不调用模型；仅从当前授权标题给出相似名称建议，需用户确认，不自动改成 TitanDB 或 TiDB。纯中文语义检索和全面实体理解仍受既有英文 Embedding 限制。
- API 不可用／两次输出校验失败：显示未生成可靠答案，decision=insufficient；不展示未经验证的模型文本，不再把证据首句拼接成正常回答。证据面板仍可打开，审计保留安全的失败原因与 Prompt 版本。
- 问题空白时前端提示输入问题，后端保留相同校验；管理账号无业务读取权时提示切换员工，不再让管理员“联系管理员”。请求中禁用查询按钮，避免重复提交。

正常问答、异常降级与未知实体均需实测；上述行为变化仍留在集成工作分支，用户确认后才合并。
