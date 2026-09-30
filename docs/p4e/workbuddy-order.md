# P4e 开单指令（Qoder → WorkBuddy，2026-09-30）

> 复制下面整段到 WorkBuddy 的新会话即可。收件人一律写 **WorkBuddy**（2026-09-30 起接替 Zcode 作实现者）。

=== PROMPT 开始 ===

你是 **WorkBuddy**，NovaCampus（`E:\AILearn\NovaCampus`）的**实现者**。负责人是 Qoder。
本单 **P4e：联网搜索开关 + 来源分区标注 + C0 前置收口两条**。P4d 已由 Qoder 第二回复核通过并合并 `master`（`bb6e78b`）。

## 0. 接手必读（按序，别跳）

1. `HANDOFF.md` — 事实与坑清单。**至少读「三、运行状态」「五、当前状态与下一步」「六、坑 39/50/54/55/56」**。
2. `docs/TASKS.md` — 本单规格（搜「### P4e」），**单一事实源**。
3. `docs/P4.md` M7 + §六（合规红线）。
4. `docs/EVAL_BASELINE.md` §十六 — 复核方记账，**C0 两条的证据与修法约束都在这里**。
5. `docs/p4d/evidence/review/qa12_attribution.json`、`rind07_premise.json` — 你不用重跑，直接读。

## 1. 纪律（违反即打回）

- **单一持棒**：本单持棒方是你。**不得合并 `master`**、不得自行开 P4f、不得动 `docs/TASKS.md` 里别人的条目（只准回填本单条目与交接回执）。
- **分支**：从 `master`（`bb6e78b`）切 `task/P4e-web-search`。WorkBuddy 自己那棵 `C:/Users/<user>/WorkBuddy/Worktrees/` 树**只读**，实现走主工作树。
- **禁改（白名单外一律不碰）**：`sims/**`、`mcp/**`、`weknora/**`、`evals/faithfulness.py`、`novaagent/novaagent/refusal.py`。
- **允许改**：`novaagent/novaagent/{websearch.py(新),graph.py,agent.py,config.py,db.py,main.py}`、`novaagent/web/**`、`novaagent/tests/**`、`evals/{cases.json,run_evals.py}`、`docs/P4E.md`、`docs/p4e/**`。
- **`agent.db` 不得被脚本改**：迁移只能写进 `db.py` 的启动期 `_migrate()`（幂等加列/加表），并在库副本上验证跑两遍结果一致。

## 2. C0 前置收口（**先做这个，merge-blocking**）

合并后的 v2.1 基线**带着一个已知红 `qa-12`**，评测退出码恒 1。留着它，「退出码非 0 就阻塞」这条闸门会退化。

### C0-① `qa-12` 融合层截断漏召 —— **真修产品，禁止改用例改绿**

实测断点（复核方逐层实测，证据 `docs/p4d/evidence/review/qa12_attribution.json`）：

| 层 | doc9「EVAL-研究生奖学金评定办法」 |
|----|-----------------------------------|
| 向量 | **第 6 位**（0.6809）—— 找到了 |
| 关键词 | **未进 top20**（问句「奖助学金/评审」，doc9 正文只有「奖学金/评定」） |
| 融合 | **未进 `FUSION_TOP_K=8`**（8 槽被两篇本科生办法的块占满） |
| rerank | **根本没送到** |
| 最终 | 3 条全为本科生办法 → 答案**错误否定断言**「研究生未在知识库覆盖」 |

- ⚠ **禁止动 `RERANK_MIN_SCORE`**：断点在它之前，动它既修不好这条，还会破坏 P4a 拒答门控与 F2 现场。
- 允许修法（任选，须给 A/B 数据）：① **融合截断前**做 per-doc 多样化（现在 `MAX_PER_DOC=2` 在 rerank **之后**才生效，这就是结构性根源）；② 扩 `FUSION_TOP_K`（注意延迟与 C2 质量信号既有数值的联动）；③ `TERM_EXPANSION` 补「奖助学金 → 奖学金|助学金」+ 把**学段词**纳入改写维度；④ 生成侧配套：**context 里有来源时不得输出「未在知识库覆盖」这类否定断言**，要么据实作答、要么明确区分「库内确无」与「未召回到」。
- **验收**：重跑 `docs/p4d/review_qa12_attribution.py`（只读库副本，不脏树）→ 目标块必须进最终 sources；`qa-12` 转 PASS；**矩阵 8/8、`intent`/`rewrite`/`scoped_qa`/`refusal_indomain` 全不回退**（改融合层最容易碰坏 rewrite 链，这条必须实测）。

### C0-② `rind-07` 去掉宽词断言（坑 54）

`expect_absent_keywords` 里 `证明` 在 student 可见块出现 **44 块**、`录取` **14 块**（「因病休学需医院诊断证明」这类**正当引用**都在），而 `饭卡/调档/交回/退卡/提档` 是 **0 块**。C0-① 把检索增强后，`rind-07` 会**必然**被自己判成「夹带无据断言」。

- 二选一（给理由）：换成零命中具体事项词；或改**共现判据**（`证明/录取` 仅与「录取/报到/调档」同现才算夹带）。
- **不得削弱检测力**：修完仍要保留 ≥3 个零命中具体词，并在 `docs/p4d/probe_ruler_selftest.py` 加一条**反向用例**（含「需医院诊断证明」的正当引用答案 → 必须 PASS）。
- 顺手把该用例 `note` 的证据口径改准：现写「13 词在 65 篇**标题**中 0 命中 → 真的域内无据」，准确说法是「标题层 0 命中；正文层有 `钥匙/空调/档案/录取` 巧合命中，但全库『交回/退还/退卡/提档/调档/档案转递』皆 **0 块**、7 项诉求逐条无一可答 → **语义层**无据」。

## 3. P4e 主体完成标准

- [ ] **先实测再接线**：现有 `llm.py` 的 OpenAI 兼容模式即使 `enable_search=true` 也**不返回 `search_info`**（只回 `usage.plugins.search.count=1`）。→ 落码前先用**一条最小请求**复验 DashScope 原生协议 `POST /api/v1/services/aigc/text-generation/generation` + `search_options={forced_search, search_strategy:"turbo", enable_source:true, enable_citation:true, citation_format:"[<number>]"}` 是否真回 `output.search_info.search_results[{index,site_name,title,url}]`，把请求/响应骨架落盘 `docs/p4e/evidence/`。**若与记录不符 → 硬停上报，不要按猜测实现**。
- [ ] 联网开关**默认关闭**；用户级默认 `user_settings.web_search_enabled` + 单次请求覆盖；UI 上明确可见当前状态。
- [ ] 本地 `[1..n]` 与联网 `[W1..Wk]` **分区注入 + 分区渲染**：不得混用编号；联网条目须显示站点名并标注「未经本校核实」；引用编号越界走 P4a 既有剥离。
- [ ] 搜索超时/失败 → **降级为仅本地** + 明确提示「联网搜索不可用」，不得静默吞掉（坑 46/47：兜底必须可观测，trace 里记 `web_error`）。
- [ ] 新增评测类型 `web_grounded` ≥2 条：**开** → 库内无据但公网有答的问题须含 `[W1]` 且来源 URL 可点；**关** → 同一问题必须走 P4a 拒答模板（这条是「开关真的起作用」的唯一证明，坑 48：没有对照的差异等于没做）。
- [ ] `retrieval_trace` 扩展记录联网节点（调用与否、耗时、结果条数、错误），前端来源区可展开看到分区。

## 4. 合规红线（**C 级，违反即打回，不接受"我漏了"**）

1. **联网请求只发送「当前问题文本」这一个字符串**。库内文档内容、chunk 正文、会话历史、系统提示词、学生个人信息、`contacts.json` 内容——**一律不得出网**。
   - 尤其注意：查询改写（P4d 的 `TERM_EXPANSION` / rewrite 节点）产出的**改写串**若含从语料里带的片段，也不能发给公网。发出去的每个字段都要能回答「这个字符串是不是只来自用户本轮输入」。
2. 请求/错误日志**不得记录问题以外的任何字段**；落盘证据里若含问句，必须是构造的公开知识问句，**不得是真实学工问句**。
3. `E:\<internal-affairs-dir>\` 的真实学工数据永不入库/上传；`corpus/*/affairs/` 只本地不提交；含学生姓名的公示/名单页禁止抓取或入库。
4. 演示口令（`admin123/counselor123/student123`、Grafana `admin/simsadmin123`）仅限本地演示，**不得进入 KB 或任何公网请求**。

## 5. 测试节奏（用户 2026-09-30 明确定的口径）

- 实现期**只做针对性最小检查**：相关单条断言、纯本地秒级自测（如 `probe_ruler_selftest.py`）、单条问句的 A/B。**不要中途复跑整轮评测**。
- **全部落地后集中跑一轮**：完整评测（v2.1 = **48 用例**）+ 冒烟。这轮是**你唯一一次整轮**，也是我在合并前独立复跑的对照，所以：
  - 必须 **48/48 且退出码 0**（C0-① 没清掉红，本单不可能过闸门）；
  - 冒烟 `documents 65 → 65` 守恒；
  - 隔离断言 ok（41+ 个带会话用例全量核对）。
- ⚠ **取退出码时不要把命令接在管道后面**（`cmd | tail; echo $?` 取的是 `tail` 的状态，我这轮就被这招差点骗过去，坑 55）。要么 `cmd > out.txt 2>&1; echo $?`，要么 `set -o pipefail` / `${PIPESTATUS[0]}`。
- ⚠ 整轮评测会让**服务端**写脏 `evals/badcases.json`（`fabricated_ref.history` 有 50 条滚动上限）。交回前**按主键做集合比对后 revert**，别把它当交付物提交（坑 56）。
- 忠实度**按区间读**（0.9444~0.9722），并且**逐条会在 0.5↔1.0 互换**（两轮独立整轮实测：`qa-05`、`qa-07` 互换而聚合值相同）。**不得把忠实度当点值用作闸门**，也不得为它改 `faithfulness.py`（禁改）。

## 6. 服务与取证注意

- `:8900` 当前是**你（WorkBuddy）起的评测态实例**（`NOVAAGENT_EVAL_TEMPERATURE=0`）。要新实例就 `bash docs/p4d/run_with_server.sh <自己的端口> <命令>`，起停收进同一条命令（Git Bash 无 `setsid`，`nohup &` 起的会随命令结束被回收）。
- **不要用命令行子串匹配杀进程**（会连自己杀掉，坑 37）；只终止自己 `Popen` 的 PID。
- 截图/页面证据：MCP 截图写不进 E 盘，用 `docs/p4b0/after_evidence.py` 那套 CDP 自起无头 Chrome 的路子，收尾用 `Browser.close` + 自己 Popen 的 PID。

## 7. 交回格式（回执写进 `docs/TASKS.md` 本单条目下）

- 状态置 `IN_REVIEW`、**当前持棒=Qoder**、分支名与提交列表、**未合并 master**、工作区是否干净。
- 逐条完成标准打勾，**每条附「哪个文件的哪个字段/哪份证据文件」支撑**（不接受口头结论；`exit=0` 要说明怎么测的）。
- C0-① 附 `review_qa12_attribution.py` 复跑前后对照；C0-② 附 `probe_ruler_selftest.py` 新反向用例结果。
- 集中验证一轮的 `reports/eval_report_*.json` 路径 + 汇总数字（含退出码）。
- **遗留与裁决项如实列**，不要自己拍板（P4d 那轮你把 6 项全部上交裁决，这个做法我认可，继续保持）。
- 你起的额外端口/进程请自己关净，**不要动别人的实例**，回执里写清关了哪些、留了哪些。

## 8. 已知坑（本单最可能踩的）

- **坑 46**：LangGraph 裸 `dict` 作状态 schema 会丢键；降级分支必须 `logger.exception`。**框架级接线必须端到端（HTTP）实测**，进程内函数调用盖章不算。
- **坑 47**：prompt 里的 JSON 示例花括号在 `str.format` 下要写双花括号；兜底默认值必须可观测。
- **坑 49**：新增早返回分支要逐条核对跳过了哪些副作用（落库 / trace / 硬门控 / 会话历史）——联网降级很容易变成"绕过落库"。
- **坑 48**：任何增强都要有能显出差异的 A/B 对照并落盘，开关类功能必须留 env 开关。
- **坑 22/39**：新代码路径必须被评测真的走到、断言必须能判红。新加的每条断言配一条「它该 FAIL 时确实 FAIL」的反向用例。
- **坑 38**：改规格/用例集合时做**新旧双向 diff**，防止静默丢条目。

不许自行开下一单。做完交回，我按「集中一次独立把关」复核。

=== PROMPT 结束 ===
