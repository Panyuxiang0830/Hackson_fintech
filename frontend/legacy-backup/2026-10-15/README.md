# 原版前端备份

2026-10-15 按用户要求备份原版。新版是唯一默认首页；不存在页面内的版本切换。

备份包含 `unified.html`、`unified.css`、`unified.js` 和依赖插图 `onboarding.svg`，对应原 `contextledger/templates/` 与 `contextledger/static/` 中的文件。文件按原始字节复制，`checksums.json` 记录前三项的 SHA-256。恢复时应同时恢复这四个文件，并将 `contextledger/web.py` 的首页路由恢复为渲染 `unified.html`。这份备份不是另一个运行入口。
