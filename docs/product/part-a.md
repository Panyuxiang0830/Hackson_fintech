# Part A：离线数据与检索

对应 REQ-014（团队工程决定）。`contextledger/` 提供可运行的数据导入、文档处理、SQLite 存储、向量索引和 Flask 检索演示；现有 `src/`、Streamlit 问答与审计流程继续独立运行。

## 当前数据范围

以下是 2026-10-05 本地完整运行的记录，不是上游数据集全部规模。原始数据和生成索引通过命令下载、重建，不提交到 Git。

| corpus | 来源与范围 | 文档 | chunks |
|---|---|---:|---:|
| `orgforge` | OrgForge 的 Confluence、Jira、Slack artifacts | 4,086 | 10,292 |
| `enterpriserag` | EnterpriseRAG 四来源；Slack 均匀抽取 3,000 个会话 | 39,414 | 279,144 |
| `privacy_camille_nike` | PrivacyBench 合成工作区，485 个 Slack 会话和 17 个 Drive 文件 | 502 | 964 |
| `privacy_grace_deere_company` | PrivacyBench 合成工作区，546 个 Slack 会话和 17 个 Drive 文件 | 563 | 1,014 |
| `publicjira_jira` | Public Jira 导出流中前 1,000 个工单，非随机样本 | 1,000 | 1,682 |
| 合计 | 五个 corpus 分开存储和检索 | 45,565 | 293,096 |

数据来源：

- [OrgForge](https://huggingface.co/datasets/aeriesec/orgforge)：合成企业记录，角色、频道、私聊和模拟任职时间来自上游资料。
- [EnterpriseRAG-Bench](https://huggingface.co/datasets/onyx-dot-app/EnterpriseRAG-Bench)：覆盖 Confluence、Jira、Slack、Google Drive；当前导入文件没有原生逐文档 ACL，演示使用明确标注的来源级角色策略。
- [PrivacyBench](https://huggingface.co/datasets/TonicAI/Privacy-Bench)：CC-BY-4.0 合成数据。下载两个工作区的 Slack 导出、Drive 原文件及身份别名资料，身份资料不进入文本索引。34 个 Drive 文件包括 20 PDF、6 DOCX、4 XLSX、4 CSV。
- [The Public Jira Dataset](https://zenodo.org/records/15719919)：CC-BY-4.0 真实公开工单。使用 HTTP Range 读取 ZIP/gzip/mongodump 的前 1,000 条工单，只下载约 2.8 MiB；保留 1,469 条评论、1,799 条 changelog histories 和工单关联。该来源不包含私有项目权限，不作为私有 Jira ACL 的验证数据。

`manifest.json`、`supplemental-report.json` 记录实际数量、补充来源版本、抽样规则、校验和及导入时间。基础 HF 数据下载使用默认上游 revision，补充 PrivacyBench 在下载开始时固定到一个 commit；上游更新后重新下载可能产生不同数量。

## 安装和运行

向量后端当前验证于 Linux x86_64、支持 AVX2 的 CPU、Python 3.10。需要 Git、C++17 编译器和 OpenMP；CPU 可以运行，CUDA 可加速 embedding。绑定使用 `-march=native` 编译，应在目标机器重新构建，不能跨机器复制 `.so`。

在仓库根目录执行：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install torch==2.6.0 --index-url https://download.pytorch.org/whl/cpu
.venv/bin/python -m pip install -r requirements-part-a.txt
.venv/bin/python scripts/setup_part_a_vectors.py

.venv/bin/python -m contextledger build --out runtime/part_a
.venv/bin/python -m contextledger augment --out runtime/part_a
.venv/bin/python -m contextledger vectors --out runtime/part_a
.venv/bin/python -m contextledger check --out runtime/part_a
.venv/bin/python -m contextledger demo --out runtime/part_a --port 7860
```

打开 <http://127.0.0.1:7860>。默认只监听本机。数据集下拉框选择公司，Person 选择身份；OrgForge 支持 day 0–60。预设按钮覆盖语义搜索、私聊、离职后拒绝、来源权限、补充数据以及工作区外用户。工单详情展示状态、时间、评论和变更数量；文件详情展示格式与导出来源链接。

首次运行需要联网下载数据和模型。此次本地 `runtime/part_a` 约 2.1 GiB，HF 下载缓存另计。`build` 会重建指定输出目录；补充数据已经存在时，继续使用 `augment`。不要对运行中的服务执行 `build`。

`augment` 默认导入两个 PrivacyBench 工作区和 1,000 个 Jira 工单，可指定范围：

```bash
.venv/bin/python -m contextledger augment --out runtime/part_a \
  --privacy-world camille_nike --privacy-world grace_deere_company --jira-limit 1000
```

重复导入相同内容保持文档数量和向量文件不变；变化的 corpus 单独替换并删除其旧向量目录。随后执行 `vectors`，并重启 `demo` 以加载更新后的索引。尚未提供实时增量同步。

## 索引和检索

```text
来源记录 / 原文件
  -> source-specific cleanup / chunking
  -> canonical.sqlite（原文、元数据、ACL、chunks、FTS5）
  -> all-MiniLM-L6-v2（384 维，单位长度）
  -> Faiss IVF 聚类
  -> 每个 corpus 的 8-bit RaBitQ IVF
  -> 候选文档 -> ACL / 任职时间检查 -> 返回结果
```

Confluence 按章节处理；其他来源使用带重叠的字符窗口。chunk 长度通常为 1,200–1,600 字符，模型仍受自身输入 token 上限约束。长 chunk 的尾部可能没有进入 embedding，完整内容仍保存在原文与 FTS 中。PDF 当前提取文本层，未实现扫描件 OCR。

向量以 float32 保存在磁盘用于构建；查询加载量化索引和 ID 映射，不进行原始向量 reranking。单位向量的内积对应余弦相似度。当前参数为：

| corpus | 向量数 | IVF 桶数 | nprobe |
|---|---:|---:|---:|
| EnterpriseRAG | 279,144 | 1,024 | 128 |
| OrgForge | 10,292 | 128 | 128 |
| PrivacyBench camille | 964 | 30 | 30 |
| PrivacyBench grace | 1,014 | 31 | 31 |
| Public Jira | 1,682 | 52 | 52 |

每次召回最多 80 个向量候选，按文档去重、过滤后最多显示 8 篇。Hybrid 使用 SQLite FTS5 与向量结果做 reciprocal rank fusion。有限候选窗口和后置权限过滤可能导致授权文档召回不足，尚未测量完整 benchmark recall。

```text
runtime/part_a/
  raw/<corpus>/<source>.jsonl
  raw/<privacy-corpus>/files/<native-file>
  canonical.sqlite
  manifest.json
  vectors/meta.json
  vectors/<corpus>/ivf.index
  vectors/<corpus>/rows.sqlite
  vectors/<corpus>/embeddings.f32
  vectors/<corpus>/status.json
  check-report.json
```

## 权限边界

Part A 是离线检索演示，使用可选择的模拟身份，未提供生产认证、LLM 回答或审计链集成。其 ANN/FTS 候选召回后再验证 ACL；不代表完成 REQ-002 要求的检索前过滤。将其接入正式问答流程前，必须完成检索前授权、身份服务、权限变更同步与审计联动，见 [ADR-0002](../decisions/ADR-0002-part-a-offline-benchmark.md)。

PrivacyBench 的 Slack 使用导出成员列表；Drive 使用 user/domain/anyone 权限，未解析的 group 权限拒绝访问。未把文件作者自动视为有权访问者。公开 Jira 使用独立 public reader 身份，明确标记没有原生私有 ACL。

每次返回内容和直接打开都会校验身份所属 corpus 及 ACL。公开 API 不返回被过滤的候选数量；切换身份、日期或数据集时清除已显示的内容，旧异步响应不能恢复旧结果。拒绝打开和不存在的文档统一返回 404。

## 验证

不下载业务数据、不构建向量即可运行 adapter 单元测试：

```bash
.venv/bin/python -m pip install -r requirements-part-a-test.txt
.venv/bin/python -m pytest -q tests_part_a
python3 scripts/project_sync.py --check
python3 -m unittest discover -s tests -v
```

完成全量构建后运行 `contextledger check`；完整五数据集的浏览器回归需要保持 demo 运行：

```bash
.venv/bin/python -m pip install playwright==1.52.0
.venv/bin/python -m playwright install chromium
.venv/bin/python scripts/check_part_a_ui.py --url http://127.0.0.1:7860 --out runtime/part_a
```

浏览器报告和截图保存在 `runtime/part_a/ui-evidence/`。检验包含三种搜索模式、四种原文件格式、工作区外拒绝、跨 corpus 隔离、默认任职日期、切换身份清理、晚到搜索/文档响应，以及手机布局。此次本地结果为 8 个 adapter 单元测试、44 项集成检查、36 项页面/API 检查通过；机器可读汇总见 [part-a-validation.json](part-a-validation.json)。
