# 新鲜度测评框架

关联 REQ-018，测量 REQ-004 的更新可见性。借鉴 ANNchor 的在线 Recall 与 chasing 查询评测，计分独立于索引机制。REQ-018 保持 in_progress：本框架不代表完整回答、安全和规模评测均已完成。

## 快速运行

在仓库根目录使用现有集成环境：

```bash
# 默认：24 个固定案例，三种检索模式，三个回放方案；使用本机缓存的 MiniLM。
bash scripts/freshness_eval.sh run --out runtime/freshness

# 不依赖模型缓存的计分／集成冒烟；fixture Embedding 不能作为语义质量证明。
bash scripts/freshness_eval.sh run --embedding fixture --out runtime/freshness-smoke

# 固定工作负载，可将实际 OrgForge 原文作为背景。
bash scripts/freshness_eval.sh generate \
  --orgforge-db /absolute/path/to/part_a/canonical.sqlite \
  --out runtime/freshness-workload.json
bash scripts/freshness_eval.sh run --workload runtime/freshness-workload.json \
  --sync-delay-ms 500 --out runtime/freshness-orgforge
```

打开输出目录中的 `report.html`。`report.json` 保存口径、范围、完整分母、运行配置和分组统计；`curves.csv` 为曲线数据，`visibility.csv` 为观测可见性；`results.jsonl` 保留原始观测，`scored.jsonl` 和 `failures.jsonl` 可逐题复核。所有运行时输出均位于 Git 忽略目录。

默认例子有新增、修改、删除、撤回、显式回滚、迟到交付六类，每类四个案例，横跨四种来源。每次变化按固定年龄安排 chasing 查询，并配对查询一个未变化资源；另含未授权身份与静态终点。所有题目、时点和 gold 在创建后冻结。

默认资料是合成企业一致性案例。`--orgforge-db` 只以只读方式提取离线原文背景；其上添加的状态变化、gold 与 ACL 是受控反事实，并非 OrgForge 原生标准答案或真实连接器权限。报告记录原始文档 ID、背景哈希和这个边界。

## 核心计分

每条证据的身份是 `(corpus, doc_id, version, content_hash)`。Gold 在查询的**计划发出时点**按独立来源事件流确定，不读取服务端索引状态。查询时间相同时先应用来源事件，再计分查询。

```text
Version Recall@K(q,t) = 命中的当前授权 gold 版本数 / 该题 gold 版本数
```

每题先算比例，再对所有已发出的可回答题求平均。文档 ID 相同而版本过旧不得命中；宣称版本正确但内容哈希不同也不得命中。Top-K 先截断，重复证据占用结果槽位但不增加命中。额外返回的未来、旧版、已撤回／删除、未授权和不可验证证据单独记录。

并列报告普通文档 ID Recall：两者的差距直接揭示“文档 ID 找到了，但证据版本过旧”。不能把这个差距自动解释为全部同步损失，检索排序和回放配置仍会影响版本 Recall；完全同步的参考运行帮助评估同一问题的可检索性。

以下结果不会从分母删除：

- 已知 gold 尚未同步；
- 拒答、不可用、错误、超时；
- 返回少于 K 条，或只命中部分 gold；
- 外部结果 JSONL 中缺失的已发出查询。

Gold 为空时必须显式标记 `expect_empty=true`，验证来源删除／撤回或该身份无授权目标证据。该类题不参与 Recall 的除法，单独统计正确空结果率。服务不可用不算成功拒答。报告同时列可用率，避免全部拒答得出“没有旧证据”的虚假成功。

## 来源时间与服务状态分开

工作负载 JSON 保存不可变 `revisions`、来源 `events`、预定 `queries` 和 `horizon_ms`。来源事件定义业务真值；`delivery_delay_ms` 定义受控交付延迟。迟到的交付可以把旧内容重新写入回放服务，但不能回写来源 gold。回滚则是新的显式来源事件，可选回以前的内容版本。

查询含身份、数据集、目标文档、问题、时间、固定 gold 和空结果标签。加载时会独立重算来源状态并验证标签，错误的 gold、重复 ID、内容哈希不一致、非法时间和未来初始化都会被拒绝。

内置方案均在独立临时目录、独立身份／审计库和 Qdrant local engine 中调用当前 `UnifiedService.search`：

| 方案 | 作用 |
|---|---|
| `current_snapshot` | 来源交付写入临时 Canonical Store，按设定延迟触发整快照发布；保留现有未就绪阻断，测出召回与可用性影响 |
| `fully_synced` | 同一检索、模型与权限检查，来源变化立即发布；作为完全同步参考，不能冒充语义 gold |
| `stale_snapshot` | 始终服务初始快照的负对照；确认旧版本不能依靠相同文档 ID 得分 |

回放发布只用于评测，不新增生产同步／版本控制机制，不修改正式数据、部署或运行中的 Qdrant。内置服务固定返回最多八个文档，因此内置运行 `K=8`；外部计分可用 `--k` 指定其他预算。

`--clock logical` 是默认确定性事件回放：500 ms 等时间属于设定参数，不是实测生产同步延迟。实际本地检索调用耗时另列，Embedding 在回放前预计算。`--clock wall` 按计划时间运行，并记录排队／发出滞后与包含该滞后的端到端耗时；当前驱动按顺序调用，不能声称多线程吞吐或原生 Qdrant 服务 HNSW 性能。默认 MiniLM 仅加载本地缓存，不自动下载模型，不自动回退 fixture。

阶段严格分开：

- `online`：查询时点不晚于最后一个来源事件；
- `recovery`：事先固定、位于来源流结束后的恢复探针；不合并到在线成绩；
- `static_undrained`：最后来源事件时点的独立静态题，不强制完成维护后再测。

超过既定 horizon 的维护任务不会执行，报告记录待完成任务数。恢复探针是预定工作负载的一部分，不因某方案较慢而动态延长。可见性只报告探针分辨率下首次完整命中和从某探针起后续观测一致的时间；没有观测到的情况记为 censored，不删除。该数据不是精确同步计时或超过观测窗口的稳定性保证。

## 接实际服务与外部结果

真实采集器可以按同一工作负载发查询，再输出 JSONL。每条结果必须保存精确的 workload 哈希、query ID、arm、mode、计划时间、status 与 hits：

```json
{"workload_sha256":"<workload.sha256>","query_id":"case-01-chasing-100","arm":"actual_service","mode":"hybrid","at_ms":200,"status":"ok","hits":[{"corpus":"freshness_eval","doc_id":"FreshLedger01","version":"v2","content_hash":"<sha256>"}],"latency_ms":12.5}
```

`generate` 输出的摘要有 workload 哈希；计分器以冻结 JSON 的规范化内容独立计算它。证据需要服务端实际版本和内容哈希，不从预期答案补填。不要把真实账号、凭据或未经授权资料写进测试集。

```bash
bash scripts/freshness_eval.sh score \
  --workload runtime/freshness-workload.json \
  --results runtime/actual-results.jsonl \
  --arms actual_service --modes hybrid --k 10 \
  --out runtime/freshness-actual
```

重复结果、未知查询、workload 哈希／时点不一致、非法计时均拒绝。缺失结果作为 miss 补全全部已发出题目。命令失败会先写 `status=failed`，旧报告不能被当作新一次成功运行。

也可用 `run --adapter package.module:factory --arms adapter fully_synced` 接入自定义回放适配器。Factory 接收 `(workload, isolated_directory, encoder)`，返回实现 `receive(event)`、`publish()`、`search(query, mode)`、`close()` 的对象；`search` 返回 `status` 与真实 `hits`。适配器负责自己的测试身份与隔离状态，运行器不携带生产凭据。

## 检查

```bash
PYTHONPATH=.:tests .venv/bin/python -m unittest test_freshness_eval -v
.venv/bin/python scripts/project_sync.py --check
.venv/bin/python -m unittest discover -s tests -v
```

回归覆盖同 ID 旧版本、错误哈希、未来证据、删除／撤回、权限、重复槽位、多证据、缺失结果、不成功的拒答、错误分母、版本回滚、迟到交付、在线／恢复／静态分离、负对照和离线重算一致性。生成回答正确率、逐句引用支持、真实来源发现时间、LLM 费用和完整规模压力仍需独立扩展测量。

## 2026-10-12 验证记录

- 首轮全项目 102 项 unittest 通过，需求同步与 diff 检查通过；推送前另补重复版本生效的独立可见性统计与资源 ID 含分隔符的回归。
- MiniLM CPU、Qdrant local、24 个 OrgForge 原文背景上的受控案例：336 道固定查询 × 三种检索 × 三个方案，共 3,024 条观测，完整保留分母；离线重算得到相同分组结果。
- 在线 hybrid chasing 的可回答题有 91 道。完全同步参考的版本 Recall@8 为 100%；旧快照负对照的普通 ID Recall 为 73.63%，版本 Recall 为 0%。延迟发布回放的版本 Recall 为 42.86%，同时暴露整快照阻断与迟到交付问题。500 ms 是设置的发布延迟，这些数字验证框架对版本与可用性损失的敏感性，不能当作线上新鲜度或总体 RAG 正确率。
- 墙钟模式另跑一个合成案例、126 条观测，验证实际调用计时与发出滞后字段；该冒烟不证明并发吞吐或生产更新时效。
- 推送前接入远程最新分支后，179 项主测试及 8 项独立 Part A 测试通过，17 项新鲜度回归包含重复版本再次生效与分块 ID 冲突修复；重新执行 MiniLM 的 3,024 条回放观测，并核对实现哈希与完整结果离线重算。
