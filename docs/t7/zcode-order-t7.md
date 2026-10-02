# T7 · 向量层 sqlite → sqlite-vec —— 开单指令（**粘贴给 Zcode**）

> 发单人：Qoder（负责人 / Review）　日期：**2026-10-02**　执行人：**Zcode**
> 分支：**新建 `task/T7-sqlite-vec`，起点 `master` `485748c`**
> （⚠ 历史上误建过的 `task/T7-vec` 已删，别复用那个名字）
> 排期：**等 T11（db 单例连接跨线程）合并之后再开工** —— 本项目**同一时刻只有一个写入者**，
> 主工作树 `E:\AILearn\NovaCampus` 在 T11 期间归 WorkBuddy。拿到这份指令先别动手，等我发「开工」信号。
> **额度：全程零额度。** 评测用的查询向量我（Qoder）会做成 fixture 给你，你**不需要也不要**碰 `.env` 里的 key。

---

## 0. 为什么做这件事（先把定位说清楚，别做成"为换库而换库"）

**诚实的前提**：当前语料只有 `65 篇 / 487 块`，向量检索是「全量 numpy 余弦扫描」，
这个量级下它**不是性能瓶颈**。所以本单的收益**不能只写成"更快"**，要写成三条：

1. **可扩展性**：向量层现在是"把全部向量读进内存"，语料到几千上万块时内存与延迟都会塌；
   `sqlite-vec` 提供 KNN 虚拟表 + 索引，是把检索能力从 demo 推到可用的那一步。
2. **架构一致性**：本项目所有状态都在一个 SQLite 文件里（文档/分块/会话/人设/设置）。
   向量也留在 SQLite 里，**备份、迁移、评测复现**都还是"一个文件"，不引入第二套存储。
3. **简历上的可讲点**：能讲清"为什么从暴力扫描换到 ANN/索引、怎么证明**换完检索结果不变**"，
   这是可验证的工程判断，不是堆技术名词。

⚠ 因此本单**最重要的一件事是等价性证明**，不是速度。任何"结果变了但看起来差不多"的改法都不接受。

---

## 1. 我给你的前置物料（你不需要任何 key）

我会在开工前把下面三样东西提交进 `docs/t7/fixtures/`，你直接用：

| 文件 | 内容 | 用途 |
|---|---|---|
| `chunk_vectors.json` | 全库 487 块的 `{chunk_id, doc_id, dim, vector}`（从现有 `chunks.embedding` 导出） | 建 vec 表 + 回填比对 |
| `query_vectors.json` | **30 条评测问句**的查询向量（含问句原文、`role_min`、期望来源标题） | 离线 A/B，不需要再调 embedding |
| `baseline_topk.json` | 这 30 条查询在**现有 numpy 路径**下的 top-12 结果（`chunk_id` + 相似度） | 等价性基线，你的新实现必须对上它 |

**你要做的第一件事是校验这三样**（写进回执）：块数 == 487、向量维度一致、30 条查询的 top-k 与
现网 numpy 实现**逐条一致**（不一致就说明我的 fixture 或你的读法有问题，**先硬停上报，不要继续**）。

> **fixture 的产出时点**：这三份文件我在**发「开工」信号时**才生成并提交，不在本单下达时生成 ——
> 因为 T11 会改 `db.py`，语料也可能在这期间变动，**提前做出来的基线会过期**。
> 你收到这份指令时 `docs/t7/fixtures/` 里**没有东西是正常的**，别据此判定物料缺失。
> ⚠ 其中 `query_vectors.json` 需要 ~30 次 embedding 调用（走 SiliconFlow，OpenRouter **没有 embedding 入口**），
> 这一笔由我（Qoder）在负责人授权后跑完再入库，**不计入你的零额度约束，也不需要你碰任何 key**。

---

## 2. 范围与做法

### 2.1 依赖
- `sqlite-vec`（`pip install sqlite-vec` 或预编译扩展 + `conn.load_extension`）。
- **必须**：`requirements` 里钉版本；写清 Windows 下扩展文件的实际路径与加载方式；
  离线环境装不上时**硬停上报**（不许自己换成 faiss / hnswlib / sklearn 之类，那是另开单的事）。

### 2.2 `novaagent/novaagent/db.py`
- 新增 vec0 虚拟表（如 `CREATE VIRTUAL TABLE vec_chunks USING vec0(chunk_id INTEGER PRIMARY KEY, embedding FLOAT[<dim>])`），
  维度从数据里取，**不许硬编码猜**。
- 建表 + 回填必须**幂等**：连跑两遍不重复插入、不报错、计数稳定；且**绝不改动/删除** `chunks` 原表。
- 提供 `rebuild_vec_index()`（全量重建）与 `sync_vec_for_doc(doc_id)`（上传/删除文档后同步），
  并与 `kb_upload` / `delete_document` 接上——**向量索引与 `chunks` 不能长期不一致**。

### 2.3 `novaagent/novaagent/rag.py`
- 向量召回层改为**可选走 sqlite-vec**，由开关控制：`NOVA_VEC_ENABLED`（**默认 `0` = 完全走现有 numpy 路径**）。
  这样任何回退都是一行环境变量，而不是回滚代码。
- 扩展加载失败时**必须显式降级并留痕**：`logger.warning` + 返回体/`tool_trace` 里带
  `vec_status="fallback:<原因>"`。**静默降级是本项目明令禁止的**（坑 46：核心逻辑对不等于接线对）。

### 2.4 不许动的东西
`novaagent/novaagent/refusal.py`（拒答硬门控）、`evals/faithfulness.py`、`evals/cases.json` 与一切判据、
`novaagent/web/**`（前端）、`novaagent/novaagent/data/contacts.json`、`.env`（**绝对不许往里写 key**）、
`novaagent/novaagent/agent.py` 的 grounding 闸门与编排逻辑。R@k 的口径（`compute_recall`、`FUSION_TOP_K`、
`RERANK_MIN_SCORE`、`MAX_PER_DOC`、`FINAL_TOP_K`）**一个参数都不许多改** —— 改了就说不清红是谁造成的。

---

## 3. 硬验收标准（逐条要能自证，我会逐条独立复验）

1. **等价性（最重要）**：30 条查询在 `NOVA_VEC_ENABLED=0/1` 两种模式下的 top-12
   **`chunk_id` 集合一致率 = 100%**，相似度数值误差 ≤ `1e-5`（浮点表示差异可接受，排序差异不可）。
   若有不一致，**必须逐条列出差异并解释**（例如 vec 用 L2 归一/未归一的差异），不许一句"精度差异"带过。
2. **端到端指标不回退**：评测默认档 **58/59**、R@k **1.0**、拒答 1.0、隔离 55/55 全部持平
   （基线见 `docs/EVAL_BASELINE.md` §20.8）。**整轮由我跑**（要额度），你不用跑。
3. **迁移幂等**：在**库副本**上连跑两遍建表/回填，表/列/索引/计数三向一致，
   `documents 65 / chunks 487` 分毫不动，**原库零写入**。
4. **索引与数据同源**：上传一篇文档 → vec 表多对应条数；删除该文档 → vec 表同步减少；
   跑完 `--cleanup` 后 `kb_doctor` 回到 `65/487`。
   ⚠ 这条是防 F3 那类事故（上传失败留孤儿）——**建索引失败也要回滚，不许留半套索引**。
5. **降级可见**：故意把扩展路径指错 → 服务必须正常起、检索必须走 numpy、
   且 `vec_status` 明确写着 fallback 与原因；**不许抛 500、不许静默**。
6. **性能读数要诚实**：给出 487 块规模下两种路径的实测延迟对比（各 ≥10 次取分布，报最小/中位/最大）。
   **如果新路径在这个规模下不更快甚至更慢，就照实写**——本单的收益是可扩展性与架构一致性，
   不是这个规模下的速度（见 §0）。不许为了数字好看去挑数据。
7. **反向用例**：等价性断言必须能判红 —— 故意把 vec 表少回填 10 条 → 断言必须红并点名差异查询。
8. **单测全绿 + 现算合计**：现有八个自测（当前 **720 条**）不得减少，新增断言计入
   `tests/_sum_selftest_counts.py` 的现算合计，**不许手抄总数**。

---

## 4. 交回要求

1. **零额度**：不发任何真 LLM / embedding / 联网请求。自查用**假 key 护身符**：
   `export LLM_API_KEY="ZERO-QUOTA-PROTECTOR-not-a-real-key"`（`config.env()` 里 os.environ 优先于 `.env`，
   注入即覆盖，任何意外真调用会拿到 401 而不是扣费）。fixture 已经够你做完全部验证。
2. 命令与**退出码**写进回执；取退出码**不要接管道**（`cmd > log 2>&1; echo $?`，坑 55）。
3. 起过的服务端口**按端口属主 PID 杀净并复查端口已关**（Git Bash 的 `kill` 杀不掉 Windows 进程，坑 61；
   用 `taskkill //PID <pid> //F` 或 psutil 按端口找属主）。
4. 回执写进 `docs/TASKS.md` 的 T7 段，顶部持棒字段与 `HANDOFF.md` 台账同步为 **IN_REVIEW / 持棒 = Qoder**。
5. **不确定就硬停上报**：sqlite-vec 还在实验期、Windows 支持、维度/距离度量语义、与现有 RRF 融合层的接缝
   —— 任何一处与本单描述不符，**停下来问，不要按猜测实现**（本项目靠这个纪律躲掉过好几颗雷）。

---

## 5. 交付节奏（一次交回，别拆小单）

本项目已经验证过「每张小单都要付一轮完整复跑成本」不划算，所以：
**一个分支、一次交回**，交回内容 = 代码 + 自测 + 等价性报告 + 性能读数 + 反向用例证据。
中途有阶段性发现（例如 vec0 的距离度量与现有余弦不等价）请**立刻在回执里单独记一条**，
不要憋到最后，也不要顺手改判据来"让它过"。

---

## 6. 附：给 Zcode 的上下文（30 秒读完）

- 项目：`E:\AILearn\NovaCampus`，「智枢 Agent」——高校学工场景的 RAG + LangGraph 编排 + RBAC + 评测闭环。
- 分工：**Zcode / WorkBuddy 实现，Qoder 负责拆解、下发与独立复验**；规则在 `docs/COLLAB.md`，
  单一事实源是 `docs/TASKS.md`，教训清单在 `HANDOFF.md`（**动手前至少读坑 39/45/46/52/55/56/61/72/73/81/82**）。
- 现状：基线 **v2.5 / 59 用例**，默认档 58/59、R@k 1.0、忠实度 0.9444(llm)、拒答 1.0；
  八个自测 720 条；P4f（persona + 提权防护）与 P5（左侧单栏外壳 + 辅导员页 + 内置头像）刚合并进 master。
- 检索现状：`rag.py` 混合召回 = numpy 余弦 + FTS5/BM25 → RRF 融合（`FUSION_TOP_K=12`）→
  SiliconFlow rerank（`RERANK_MIN_SCORE=0.3`）→ `MAX_PER_DOC=2` → `FINAL_TOP_K=7`。
  **本单只替换"向量召回"这一层**，融合与重排序一律不动。
- 协作变更：P4f/P5 期间实现人是 WorkBuddy；**T7 起你（Zcode）回到实现人位置**，
  但**主工作树同一时刻仍只允许一个写入者**，务必等 T11 合并后再开工。
