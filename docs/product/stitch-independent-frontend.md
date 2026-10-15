# Stitch 独立前端

2026-10-14 用户要求直接使用提供的 HTML 新建前端，并保留现有页面。新版现作为唯一默认首页 `/`，也可访问 `/static/stitch/index.html`。原版文件完整备份到 `frontend/legacy-backup/2026-10-15/`，新版不提供原版切换入口；API 保持兼容。

## 原稿与构建

`frontend/stitch/source/` 保留用户 `stitch_aspire_fintech_landing_page v2` 文件夹里的原始 `code.html`，文件名对应原页面文件夹。桌面五页的原始 HTML SHA-256 保存在 `contextledger/interfaces/static/stitch/source-manifest.json`；原稿文件和生成入口同时入库，便于核对来源。

`frontend/stitch/build.cjs` 直接导入搜索首页、Decision Radar、Evidence Passport、Security Lens 和 Audit Trail 的 `<main>`，沿用原稿 DOM 与 Tailwind 类。共用原首页的侧栏和顶部栏，页面之间在同一前端内切换；ID 增加页面前缀，避免冲突。生成的 UI 不加载旧前端样式。原稿字体、Material Symbols 和图片整理成本地资源；Tailwind 使用原 HTML 内的配置编译，符合应用既有 `script-src 'self' / style-src 'self'` 约束。

重建命令：

```powershell
cd frontend/stitch
npm ci
npm run build
```

生成结果已经纳入仓库，正常启动现有 Flask 服务后即可访问，无需现场安装 Node 依赖。首次重建需从原稿资源 URL 下载字体和图片，后续复用本地文件。`responsive.css` 只适配原稿固定桌面外壳、移动端顶部横向导航及变长业务文本。

## API 接入

`contextledger/interfaces/static/stitch/app.js` 只负责将真实数据填入原稿的数据位置：

- 身份与数据集使用 `/api/session`、隔离 Demo 身份接口和 `/api/corpora`。
- 提问复用 `/api/ask`，内部 Radar 仍由后端自动决定；普通回答或格式降级不推测业务 Confirmed 状态。
- Confirmed / Pending confirmation 读取服务端 `radar_presentation`。只有 pending 时显示待确认卡；未知事件时间仍写 Unknown。
- 证据在当前页面内切换到 Passport，调用 `/api/doc` 重新检查授权；文本使用 `textContent`，原文外链仅允许 HTTP(S)。不可访问时清理旧来源与回答，显示中性提示。
- 管理员页面复用用户、来源主体和权限修改接口；前后计数表示实际来源绑定数，不是命中证据数。不会执行原 HTML 中模拟撤权的脚本。
- 审计页面使用 `/api/audit`。被服务端标记为 redacted 的事件不显示或导出旧问题、回答、证据与 Radar 摘要。

所有写请求携带当前 CSRF；角色入口使用服务端会话。结果仅保留在当前页面内存，身份／权限版本变化、页面隐藏和服务端访问拒绝会清理旧结果。原稿里的 Verified、置信度、p95、密码学签章、模拟工单与示意统计不会当作真实 API 结果。原稿插图仍是示意素材。

## 检查

```powershell
python -m unittest tests.interfaces.test_stitch_frontend -v
cd frontend/stitch
npm run verify
```

浏览器检查默认读取本机 `http://127.0.0.1:17860` 的新静态前端，API 使用专门 fixture，不修改真实员工权限。可通过 `STITCH_BASE_URL` 指定服务，通过 `STITCH_BROWSER_PATH` 指定浏览器。检查涵盖 pending/confirmed、原文安全显示、来源访问拒绝、身份切换清理、真实接口契约下的撤权／恢复、审计脱敏／导出，以及 320–1600px 的 13 个视口／断点。

## 2026-10-15 显示审查修复

- Passport 整段原稿时间线占位已清空，包括旧 Jira／Runbook 节点；移除固定 `Rev 04-B`、示例哈希和没有接口依据的治理卡。事件数量来自当前响应，选中来源标题来自实际原文。
- 技术详情统一使用 `hidden` 属性，不保留冲突的 `.hidden` 类；展开／折叠同时更新 `aria-expanded`，浏览器检查验证真实可见性。
- 1023px 及以下的 Passport 是全屏证据面板，直接显示所选来源；背景导航不可操作。关闭或 Escape 返回结果页并恢复引用焦点；Tab 保持在面板内。不同来源的异步响应具有独立序号，关闭或切换来源后旧响应不会覆盖当前面板。
- 768–1199px 使用紧凑侧栏与顶栏；权限页交付状态标签可以换行。手机保留顶部横向导航，压缩重复信息，示例问题排在使用引导前；原版入口已按最新要求移除。
- 时间线默认显示前 4 条，`Show all` 可展开全部；完整事件数量始终可见。长标题限制两行，完整标题在 Passport 和悬停提示中可读；证据列表限制高度并可滚动，授权记录不从响应中丢弃。
- 审计请求 ID 缩略显示，支持复制完整值；事件和审计时间显示为明确标注的 SGT（Asia/Singapore / UTC+08:00），原时间值保留在悬停提示和 JSON 导出中。未知或不带明确时区的时间不自动猜测。
- 手机关闭、引用、身份选择等点击目标约 44px；提问按钮显示禁用与加载状态，错误和操作提示放在当前页面内容内。

新增回归验证技术详情可见性、占位数据清理、4／全部事件切换、小屏证据直接显示与键盘焦点、迟到的原文响应、按钮加载与内联错误、完整 ID 复制，以及 768／820／900px 等边界下顶栏控件在屏幕内。长原文场景另外检查面板滚动后底部按钮可实际点击，防止 flex 压缩造成内容相互覆盖。原稿文件与原 unified 前端仍保留。

本轮本机真实 API 冒烟请求能返回授权证据、打开原文、读取管理员权限与脱敏审计；模型回答请求返回 `mock_fallback`，界面明确保留“未生成可靠模型答案”的提示。这是当前模型服务限制，不能把 fixture 的 Confirmed/Pending 检查当作真实模型质量验收。

## 2026-10-15 用户截图修正

Audit Trail 筛选控制台使用容器宽度驱动的网格，字段含英文标签，手机按组堆叠；时间提示表示所有已记录时间，不冒充尚未实现的筛选器。Query planning 是可访问的开关，直接发送 `/api/ask` 的 planning 布尔参数；默认沿用服务配置，用户选择不会被会话轮询覆盖，浏览器只保存这一非敏感偏好。服务未配置时开关不可用。

主要操作按钮保持单行，并根据实际可用宽度调整字号，不裁剪按钮含义。删除五页中文设计注释卡，演示身份采用英文显示别名；原始证据及审计导出保持原文，避免伪造译文。How to explore an answer 使用用户提供的本地 vectorized.svg.svg，按比例完整展示。

原 unified 前端文件不改写；备份附 SHA-256 清单。默认路由直接提供新页面，不加载旧前端资源。验证新增规划开关的实际请求参数与轮询保持、英文界面、审计输入可读宽度，以及放大字号下按钮单行和无截断。

## 2026-10-15 问题分层、下拉菜单与切换动效

问题卡使用浅蓝背景、蓝色文字和左侧强调边，与白底的判断和回答卡区分；Radar 和 Passport 使用同一问题样式。移除 Isolated demo 展示标识，实际身份和 API 权限检查保持原行为。数据集、Query planning 与 Ask 控件高度统一为44px。

所有 select 使用圆角、主题绿色选中态与焦点环。支持 appearance: base-select 的浏览器将原生菜单渲染成圆角浮层，仍保留原生键盘和辅助技术行为，超出空间时由浏览器翻转位置；不支持的浏览器保留原生菜单和已美化的触发控件。没有新建一套手工模拟的下拉组件。

动效参考 [Emil Kowalski animate Skill](https://github.com/emilkowalski/skills/blob/main/skills/animate/SKILL.md) 及其 RECIPES。用已有浏览器 WAAPI，只动画 transform 和 opacity。进入 Radar 使用200ms strong ease-out 淡入上移，Passport 使用250ms drawer 曲线从右侧短距离滑入；返回 Radar 从左侧短距离淡入。Passport 背景判断降低强调，桌面自动把证据面板带入阅读位置并转移焦点；移动端保持全屏证据和键盘焦点约束。按钮按下反馈120ms。

切换取消未完成动画，权限清理和返回即时执行，不延迟内容隐藏，也不保存旧页面图像。reduced motion 只保留100ms轻微淡入；键盘触发直接切换。浏览器验证覆盖搜索区高度、问题与回答配色差异、两种页面动画、焦点转移、减少动态效果和快速关闭，并复用13个屏幕宽度回归。截图保存于工作区 output/contextledger-polish-20261015，仅为受控示意数据。

## 2026-10-15 合并最新 main 并适配功能分包

用户已确认当前视觉版本定稿。合并前本地检查点为 b9186fa，纳入的 main 为 9ad487e（PR #18），当前工作分支仍为 feat/REQ-017-aspire-responsive-ui，不推送或部署远端。

静态资源整体迁到 contextledger/interfaces/static/stitch，构建输出、测试和文档按新路径更新；根路由由 interfaces/web.py 提供同一新版页面。HTTP /static/stitch 与现有 API 路由保持兼容；旧前端归档仍在 frontend/legacy-backup/2026-10-15。保留 main 的功能包、来源故障隔离、ACL 当前依据与历史区分、MCP 工具和语言/工具参数校验。冲突合并保留 radar_presentation 展示结构，并将综合提示词与主分支的因果/时间/工具约束合并，Prompt 版本记为 answer-v11-2026-10-15。

/api/session 新增可选布尔 demo_auto_entry，前端只在服务器显式开启且为隔离 Demo 时自动选择员工；普通模式不自动进入身份。证据折叠技术详情显示当前 ACL provenance、来源观察时间、来源修订和未验证的人工来源引用，历史依据不会冒充当前依据。关闭来源或切换身份后，迟到的请求错误不能清掉新结果。引用原稿和旧版本快照关闭 Git 换行归一化，以便跨平台保持已有 SHA-256。

验证范围：57项相关 Python 检查通过（回答、Radar综合/集成、身份边界、新前端文件和工具API）；另3项新 Flask 契约检查通过（默认入口/资源、实际搜索问答/原文、撤权和审计脱敏）。浏览器通过13个宽度、动效/焦点、减少动态效果、规划开关、ACL追溯字段、迟到409、复制和脱敏导出检查；这些使用受控fixture，不调用付费模型或同步真实来源。

更大范围回归在 Windows 遇到既有平台限制：resource 模块、os.O_NOFOLLOW，以及原生 fcntl。临时本地预览/检查启动器使用 portalocker 提供文件锁兼容，测试清理前收集未释放的SQLite连接；不把该环境替代当作Linux同步安全验收，也不跳过失败测试来报告全量通过。生产Linux全量测试和真实模型质量未由本轮代替。
