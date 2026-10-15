# 提交报告

英文源文件为 [main.tex](main.tex)，在线编辑：[Overleaf](http://100.95.217.41:8080/project/6acfa935daa040638ee5bd56)。使用 LuaLaTeX，正文 Linux Libertine、标题 Linux Biolinum、代码 Inconsolata。

报告覆盖 Handbook 用户、痛点和五个场景，重点介绍 Decision Radar、Security Lens、Evidence Passport。恢复时间线为虚构示意；评测采用冻结基线 `952881f`，数据见 [实测记录](../evaluation/submission-20261015.md) 与 [汇总](evaluation/metrics.json)。完整逐题记录保存在原始实验目录，汇总保留其文件哈希。

`assets/workspace-latest-en.png` 为当前前端的英文页面，回放13 October的 `approval-0-en` 回答和引用。截图版本与采集方式见同名JSON；没有新增模型调用。`assets/cover.png` 为1920×1080封面。真实开发聊天附件仍需至少三份。

编译：

```bash
cd docs/submission
latexmk -lualatex -interaction=nonstopmode -halt-on-error main.tex
```
