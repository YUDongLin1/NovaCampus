# P4E · 联网搜索开关 + 来源分区标注（含 S1 流式收口）

> 分支 `task/P4e-websearch-main`，实现者 WorkBuddy，复核 Qoder。**未合并 master**。
> 本单 = P4e 主体（M-A/M-B/M-C/M-D/M-E）+ **S1 流式收口**（merge-blocking，先做）。
> 基线：`evals/cases.json` **v2.4 / 55 条**（v2.3 的 48 + `stream_sse` 3 + `web_grounded` 4，口径变更）。

---

## 一、S1 流式收口（M4 缓冲回归的真修）

### 1.1 事实（复核方 2026-09-30 实测，本轮复现）

M4 的 grounding 闸门为了「不发一段再撤回」，把 `/api/chat/stream` 改成 **delta 全量缓冲、判完闸门再下发**。
本轮在**旧实现上先跑了一遍**（`docs/p4e/evidence/stream_sse_before.json`）：

| 用例 | 旧实现实测 |
|---|---|
| ss-01 | `TTFB=2992ms, E2E=3064ms, span=73ms, deltas=21` → 21 个 delta 全挤在最后 73ms |
| ss-02 | 收到首个 delta 才断开时，**服务端已生成并落库** → 残留 1 条 user + 1 条 assistant（**根本没有中断窗口**） |
| ss-03 | 无 `grounding_retry`（旧实现没有这个事件） |

`span = E2E - TTFB` 是「渐进性」的客观度量：真流式应当接近整段生成耗时，全缓冲则趋近 0。

### 1.2 修法：早窗提交（`_StreamGate`）

**判定与下发解耦**：

- delta **默认直接放行**；只在「早窗」内 —— 尚未出现可核查事实（`[n]` 或数字）**且**累计生成不足 `N` 字 —— 暂缓；
- 出现首个可核查事实 **或** 累计满 `N` 字 → 立即补发，之后一律逐段下发；
- **整段生成完仍零可核查事实** → 才走一次重生（判据、重生次数、`ctx_info.grounding_gate`、不许静默兜底，**一条都没弱化**）。

**已下发的文字不假装没发生**：必须重生时先发一条显式事件
`{"type":"grounding_retry","released_chars":N,"n_sources":k}`，前端把初稿折进 `.gate-draft` 块
（保留可见、弱化）并插入「（初稿未给出可核查依据，已重新组织答案如下）」状态行，重生结果另起一段。
重生改为 `llm.chat_stream` **逐段下发**（不再是「一个 delta 承载全文」）。

**N 为什么取 80**：可核查事实在据实作答时几乎总在首句内出现，本项目 qa 答案首句 40~120 字 → 80 字让
「首个事实」大概率落在窗口内；最坏情况也只憋住 1~2 句而非整段 200~400 字。60/80 两档实测见下表。

### 1.3 三档延迟对照（`docs/p4e/evidence/stream_latency_*.json`，warmup1 + 连测3 取中位）

同一问句「研究生申请休学需要提交哪些材料？审批流程又是怎样的？」，每档独立端口独立实例：

| 档位 | env | TTFB 中位 | E2E 中位 | **span 中位** | delta 中位 | 检索段中位 |
|---|---|---|---|---|---|---|
| **全缓冲**（M4 旧行为） | `NOVA_GROUNDING_EARLY_WINDOW_CHARS=0` | 3380.6ms | 3452.0ms | **88.9ms** | 21 | ~1050ms |
| **早窗 80**（默认） | `=80` | 2786.6ms | 3092.0ms | **305.4ms** | 25 | ~970ms |
| 早窗 60（N 取值对照） | `=60` | 2810.5ms | 3267.8ms | **457.3ms** | 27 | ~1270ms |
| **关闭**（无闸门，M4 之前） | `NOVA_GROUNDING_GATE=0` | 2355.5ms | 3001.6ms | **638.8ms** | 27 | ~950ms |

相对 P4d 记录的检索基线 **TTFD 2161ms**：早窗档 +625.6ms、全缓冲档 +1219.6ms、关闭档 +194.5ms。

**如实读数**：
- 早窗档把 **span 从 88.9ms 提到 305.4ms（3.4×）**，TTFB 从 3380.6ms 降到 2786.6ms（−17.6%）→ 真流式恢复；
- 但**仍未回到关闭档**（span 638.8 / TTFB 2355.5）。差的那 ~430ms 是闸门的**真实代价**：
  本问句答案仅 110~140 字，80 字窗口覆盖了答案的大半，首个可核查事实出现得偏晚。
  答案越长，窗口占比越小，早窗档会越接近关闭档 —— 这是窗口机制的固有性质，不是缺陷。
- 全缓冲档的 span（88.9ms）与复核方独立实测的 36ms 同量级，**相互印证**。

### 1.4 自动化覆盖（`stream_sse`，先红后绿）

| 断言 | 内容 | 旧实现 | 修复后 |
|---|---|---|---|
| ① | 事件序列 `sources → context → delta* → [grounding_retry → delta*] → done` | FAIL（含 0/3 连带失败） | PASS |
| ② | delta 事件数 > 1（只有一条＝整段下发） | **PASS**（21 条，未能判红） | PASS |
| ③ | `E2E − TTFB ≥ 300ms` | **FAIL**（73ms / 79ms） | PASS（918ms / 1213ms） |
| ④ | 客户端中途断开 → 本轮 user 消息回滚 | **FAIL**（无中断窗口） | PASS（会话消息数 0） |
| ⑤ | 命中闸门 → 出现 `grounding_retry`，且落库答案 == 重生后版本 | **FAIL**（无该事件） | PASS |

⚠ **对单据预期的一处如实更正**：单据写「确认 ②③ 确实 FAIL」，实测 **② 在旧实现上是 PASS**
（旧实现有 21 个 delta，只是全挤在最后 73ms）——「delta 数 > 1」这条防的是「整段合成一个 delta」，
**防不住「21 个 delta 集中下发」**。真正判红的是 ③（span）。故 ③ 的阈值不能按单据原文的「> 0」
（旧实现也有 73ms > 0），取 **300ms**：关闭档实测 638.8ms、早窗档 305.4ms、全缓冲档 88.9ms，
300ms 能把三档干净分开且留有余量。

**两份输出**：
- 红：`docs/p4e/evidence/stream_sse_before.json`（0/3）
- 绿：`docs/p4e/evidence/stream_sse_after.json`（3/3）
- 两者**过同一把尺子**：`docs/p4e/probe_stream_sse.py` 直接 `import run_evals` 复用 `run_stream_case`
  （坑 59：改进后的断言必须和原断言过同一把尺子）。

**⑤ 为什么需要 env 钩子**：闸门自然命中率约 20%（qa-17 实测 2/10），靠真实模型命中会让断言空跑。
故加 `NOVA_GROUNDING_STREAM_FORCE_UNGROUNDED=1`（默认关、仅流式首版、重生仍走真实 LLM）——
**这是本单新增的测试钩子，属需裁决项**（见 §五）。另外
`docs/p4e/probe_stream_gate_unit.py` 用桩件在**库副本**上进程内驱动 `chat_stream_for`，
12 条断言（U1~U7）**确定性**全过，不依赖任何钩子。

---

## 二、P4e 主体

### 2.1 协议事实（与单据假设不符，已由双方独立实测确认）

单据（M7）假设原生 `text-generation + search_options` 回
`search_results[{index,site_name,title,url}]`。**该契约不成立**，四入口全矩阵实测见
`docs/p4e/evidence/WEBSEARCH_PROTOCOL_HARDSTOP.md`：

| 入口 | 结果 |
|---|---|
| 原生 `text-generation` + `search_options` | 参数被忽略，无 `search_info` |
| 兼容 `chat/completions` + `enable_search` | 检索真执行（prompt_tokens 29→2092）但来源**静默丢弃** |
| **兼容 Responses API + `tools=[web_search]`** | ✅ 回来源，但每条**只有 `{type,url}`** |

**本轮新增一条协议事实（单据与硬停报告都未记录）**：
必须加 `tool_choice={"type":"web_search"}` 才**强制**检索。实测 `qwen-flash`：

| 问句 | 不加 tool_choice | 加 tool_choice |
|---|---|---|
| ISO 4217 人民币代码（静态知识） | `web_search_call` 不出现，`src=0` | `src=10` |
| 杭州明天天气（时效类） | `src=9` | — |

另测无效（同为 `src=0`）：`forced_search` 放顶层 / 写在 tool 里 / `search_options`。
即：**静态知识题不加 tool_choice 就等于没开联网**。

### 2.2 M-A 引用语义：为什么是「分区展示 + 整段级标注」，不是 `[W1]` 角标

上游每条来源只有 `{type,url}`，且正文**零 `[n]` 角标、零内联 URL、`annotations` 为空**
→ **不存在「哪句出自哪条 URL」的映射**。若由我方自建「第 k 句 ↔ 第 k 条 URL」的对应关系，
那是**用假精确换好看**：用户在界面上看到一个可点的引用，审计/面试时却答不出「凭什么说这句出自这条」。

因此定稿（理由存档于此）：

- 联网来源 **单独分区**列出真实 URL（可点、可核）；
- `site_name` 由 `urlparse(url).netloc` **推导**，条目带 `site_name_derived=True`，
  UI 明确标注「站点名由 URL 推导（上游只返回 URL）」；
- `index` 由我方按 `action.sources` **原序**分配，`ref` 用 `W1..Wk`，**仅作列表编号**，
  与本地 `[1..n]` **分区不混**；
- **不得**把 `[W<n>]` 绑定到具体句子；
- 改为**整段级声明**「⚠ 本节含公网检索内容，未经本校核实；涉及本校具体政策、流程与办理口径的，
  请以学校官方文件为准。」——由**代码注入**（`agent.WEB_DECLARE`），不靠模型自觉（同 P4a C8 手法）。

**实测证明这条红线不是纸上谈兵**：wg-01 首轮模型就写出了 `[W3]`（尽管 `WEB_CONTEXT_BLOCK`
明令禁止），反向断言当场判红 → 与 P4a 同源教训「prompt 挡不住，必须落代码」，
故新增 `agent.strip_web_citations()`（非流）+ `_StreamRefFilter(drop_web=)` （流内）双路径剥离，
并记 `ctx_info["web_citations_stripped"]` 保持可观测。
剥离会让评测的反向断言在产品路径上恒绿，故另配
`docs/p4e/probe_web_citation_ruler.py`（11 条全过）证明**这把尺子能判红**（R4/R5b）。

### 2.3 M-B 开关

- **默认关闭**（`config.WEB_SEARCH_ENABLED` 默认 False）；
- 优先级：**单次请求覆盖（`body.web_search`）> 用户级默认（`user_settings.web_search_enabled`）> 全局默认**；
- 迁移只写在 `db.py` 启动期 `_migrate()` 内（幂等），`docs/p4e/probe_db_migration.py` 在**库副本**上
  连跑两遍 schema/数据逐字段一致（8 条断言全过），既有用户默认 `''`（= 未设置 → 回落全局「关」，不误开）；
- UI：composer 内开关，**当前状态可见**（「开 / 关」文字），改动即持久化为用户级默认；
  `/api/me/settings` 的 GET 暴露 `web_search_enabled`。

### 2.4 M-C 降级可观测

联网只是**本地拒答后的补充通道**：本地有据时**不出网**（既省调用，也更合规）。
超时/失败/零来源 → 维持拒答并在确定性模板后追加「（已尝试联网检索，但本次联网搜索不可用或未返回结果…）」。
`ctx_info` 恒记四个字段：`web_called / web_ms / web_n_sources / web_error`
（另加 `web_enabled / web_fallback / web_unavailable / web_citations_stripped`）。
失败一律 `logger.warning`，**不静默兜底**（坑 46/47）。

⚠ **超时默认 60s 的实测依据**：强制 `tool_choice` 的联网耗时方差极大 —— 同一问句两次
12.3s / 79.4s；另测 DOI 问句 68.4s、CPI 4.9s、GDP 8.3s、VAT 6.0s。用例问句因此也挑了实测快的。

### 2.5 M-D 评测：开/关对照（`web_grounded` 4 条，v2.4 新增）

| 用例 | 开关 | 断言 |
|---|---|---|
| wg-01 | 开 | `web_called=True`、联网来源 ≥1 且 URL 可点、`site_name_derived` 为真、含整段级声明「未经本校核实」、命中 GDP/国内生产总值 |
| wg-02 | **关** | 同一问句走 P4a 确定性拒答模板（指纹「系统模板生成」）、**绝不发起联网请求** |
| wg-03 | 开 | 同上（第二条构造问句：CPI / 居民消费价格指数） |
| wg-04 | **关** | 同 wg-02 |

四条**都带反向断言**：正文不得出现逐句绑定的 `[W<n>]` 角标（命中即 FAIL）。
问句一律构造的公开知识题（校园框定型），**不是任何真实学工问句**。
实测 4/4（`docs/p4e/evidence/web_grounded_probe.json`）。

⚠ **问句为什么要加校园框定**：纯域外问法「ISO 4217 标准里人民币的三字母代码是什么？」
被意图分类器判为 `chitchat` → 走 `direct` 直答，**根本到不了「本地拒答 → 联网」这条链**
（实测 `intent='chitchat', retrieval_skipped=True`）。加校园框定后 `intent=retrieval`、
本地检索无据，联网通道才生效。这条限制本身是**需裁决项**（见 §五）。

### 2.6 M-E 合规红线（C 级）

`docs/p4e/probe_web_compliance.py` —— **读代码追**，不是测功能：

- 抓 `httpx.AsyncClient.post` 拿**实际发出的请求体**；
- L1 直接调 `websearch.search()`；L2 走完整 `agent.chat_for(..., web_search=True)`，
  且**预先埋好**会话历史（含姓名/学号/手机号样式的个人信息）、库内来源、contacts、系统提示词；
- 断言：顶层键 == `{model, input, tools, tool_choice}`；`input` **逐字等于**当前问题文本；
  请求体每个字符串值里**不含**库内 chunk 片段 / 会话历史 / 系统提示词 / 联网区块模板 /
  个人信息埋点 / `contacts.json` 内容；日志不得记录问题以外的字段。

实测 **21 条全过**，含：
- L2a 本地有据 → 新增联网请求 **0 次**；
- L2c 开关关闭 → 新增联网请求 **0 次**；
- E6 **反向**：把库内 chunk 塞进 `input` → 同一把尺子必须判红（证明尺子不空转）；
- E6b 干净请求体 → 判绿（无假阳性）。

⚠ 尺子本身修过一次：`json.dumps` 会把 chunk 里的 `\n` 转义成 `\\n`，导致含换行的样本**永远匹配不上**、
尺子静默空转（坑 45 同形状）。现改为递归比对**字符串原值**。

---

## 三、证据索引

| 文件 | 内容 |
|---|---|
| `docs/p4e/evidence/stream_sse_before.json` / `_after.json` | 流式先红（0/3）后绿（3/3） |
| `docs/p4e/evidence/stream_latency_{full,early80,early60,off}.json` | 四档延迟对照（含逐次样本） |
| `docs/p4e/probe_stream_gate_unit.py` | 进程内桩件 12 条断言（库副本，确定性） |
| `docs/p4e/probe_stream_sse.py` / `probe_stream_latency.py` | 复用 `run_evals` 同一把尺子 |
| `docs/p4e/evidence/web_grounded_probe.json` | 开/关对照 4/4 |
| `docs/p4e/evidence/web_compliance.json` | 合规：实际请求体逐字段落盘 |
| `docs/p4e/probe_web_compliance.py` / `probe_web_citation_ruler.py` / `probe_db_migration.py` | 三个纯本地探针 |
| `docs/p4e/patch_*.py` | 每处代码改动的精确补丁脚本（带 count 断言，可复跑） |

---

## 四、纪律自查

- 禁改项 `sims/**`、`mcp/**`、`weknora/**`、`evals/faithfulness.py`、`novaagent/novaagent/refusal.py`
  → `git diff --numstat master..HEAD --` 对这五项**为空**。
- 判定落代码不落 prompt（S1 闸门、`[W<n>]` 剥离、整段级声明注入均为代码）。
- 断言失败必须影响退出码；反向断言配「它该 FAIL 时确实 FAIL」的自测。
- 取退出码不接管道（坑 55）；整轮后 `evals/badcases.json` 按主键集合比对再 `git checkout --`（坑 56）。
- agent.db 只由 `db.py` 启动期 `_migrate()` 改，探针一律用**库副本**。
- 端口起停与复查见回执（坑 61 姿势）。

---

## 五、遗留与需裁决项（未自行拍板）

1. **`NOVA_GROUNDING_STREAM_FORCE_UNGROUNDED` 测试钩子**：为了让 stream_sse ⑤ 必然被执行而加
   （默认关、仅流式首版）。若不接受"生产代码里留测试钩子"，替代方案是把它挪成
   `docs/p4e/` 下的进程内桩件（已有 `probe_stream_gate_unit.py`），评测侧 ⑤ 退化为
   「闸门命中 ⇔ retry 出现」的一致性断言（也会恒绿但证明力弱）。**请裁决**。
2. **联网对「域外闲聊类问句」不生效**：被意图分类器判为 `chitchat` 的问句走 `direct` 直答，
   联网开关打开也不会触发。要覆盖需扩意图类别（如新增 `web_fact`），会动 `INTENT_PROMPT`
   与既有 intent/rewrite 用例 —— **建议下单一并做，本单未做**。
3. **联网耗时方差极大**（同一问句 12.3s / 79.4s），超时 60s 仍有偶发降级风险；
   `web_grounded` 用例问句已挑实测快的（GDP/CPI），但整轮时长会随网络波动。
4. **P4e C0 遗留**：`docs/p4e/evidence/QA12_E2E_DISCREPANCY.md` 状态已过时（记的是 qa-17 待裁决、
   47/48），M4 落地后已转绿，本单**未改写历史纪要**，需指令确认是否改写成事后复盘。
5. `reports/eval_report_*.json` 按既有纪律不入库（评测运行产物）。
