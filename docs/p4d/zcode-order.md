# P4d 开单指令（粘进 WorkBuddy 会话）

> 由 Qoder 于 2026-09-30 生成。规格正文以 `docs/TASKS.md` 的 **P4d 条目** 为唯一事实源。
> ⚠ **本单是 P4 全线唯一带"硬指标"的一单**：措辞命中率 `3/8 → ≥6/8`，复跑矩阵给数值，**不接受口头说改善了**。
> ⚠ 测试节奏按用户要求：**实现期只跑针对性最小检查，功能全落地后集中跑一轮**。

=== PROMPT 开始 ===

你是 **WorkBuddy**，NovaCampus 项目（`E:\AILearn\NovaCampus`）的实现者。**当前持棒=WorkBuddy**，现在下发 **P4d：LangGraph 检索编排 + 查询改写重试**。

前序均已合并 master：**P4c KB 文件夹与 `@` scope `5611c16`**、P4b 会话与上下文管理 `0499a89`（你上一单，第一回被打回 5 条、修复后通过）、P4b-0 前端拆分 `e947259`、P4a-1 `5399a5e`、P4a `827e1ae`、P3b `2234fc8`。

按序做：

1. 读 `docs/TASKS.md` 头部「当前持棒」确认是你，读 **P4d 条目**（含我上轮结转进来的两条必办）。
2. 读 `docs/P4.md` §M6（图结构、意图判定、质量信号、改写策略、状态持久化）与 §2.8（**F2 检索崩塌的实测证据**）。
3. 读 `docs/CASE_STUDY.md` §3——这一节是你这单的背景故事，也是简历素材：**我最初把根因写成"长问句导致崩塌"，被自己 later 的变体矩阵证伪**（7 字崩、16 字崩、48 字的多子句书面句反而通过，崩塌与长度**不单调**）。**不要重犯同类直觉归因**：任何归因先用 `evals/diag_retrieval.py` 逐层打印（向量 / 关键词 / 融合 / rerank）再下结论。
4. 读 `HANDOFF.md` §六，本单特别相关：**坑 27**（真实措辞打崩检索的完整机制与铁律）、**坑 22/39**（新能力要配能测出它失败的用例；断言必须判红）、**坑 45**（空集假通过——断言要同时断言"取到了东西"，我这轮自己连踩三次）、**坑 41**（压缩摘要会把用户自述假事实洗成可采信证据）、**坑 33/17/18**、**坑 37**（进程归属）、**坑 4/5/8/10**。
5. 切分支：`git checkout -b task/P4d-graph-rewrite`（从 master `5611c16` 切）。

## 第 0 步：BEFORE 基线（本单基线就是那个矩阵）

起服务：`cd novaagent && NO_PROXY="127.0.0.1,localhost" NOVAAGENT_EVAL_TEMPERATURE=0 .venv/Scripts/python.exe -m uvicorn novaagent.main:app --port 8900`

- **复跑 `evals/query_variant_matrix.py`**，把输出落盘 `docs/p4d/evidence/before/variant_matrix_before.txt`。**期望仍是 3/8**（「学平险」0.8875、「学校有学平险吗」0.8065、「多子句书面全称」通过；「学平险在哪里买」0.1007、「学生平安保险是否由学校统一办理？」0.0194、学生原句 0.1136 等归零）。**跑出来若不是 3/8，硬停上报**——说明基线已变，先对齐再动手。
- `evals/diag_retrieval.py` 对至少 3 条失败问句做**逐层归因**（向量排名 / 关键词命中 / 融合位次 / rerank 分），落盘 `before/retrieval_diag.txt`。**要能证明"向量层本已排到前列、是 rerank + 一刀切阈值把它放大成零来源"**，这是本单立论基础。
- `before/faithfulness_baseline.txt`：记 v1.9 忠实度两轮实测值（**0.9412 / 0.9412**，低于 v1.8 中位 0.9706 一档）。本单结束时必须**一并观察**它，不得让它继续下滑而无人记录。

## 本单的四条硬要求

1. **硬指标：`evals/query_variant_matrix.py` 命中率 3/8 → ≥6/8**，且**必须包含学生原句**。改完复跑矩阵，`after/variant_matrix_after.txt` 与 before 同名配对、逐条列出每条问句改前改后的 rerank 分与命中与否。**不接受"明显改善"这类无数字表述**（坑 18）。
2. **只用 LangGraph 做状态机编排**：LLM 仍走 `llm.py`(httpx)、向量仍走 numpy 内存余弦，**不引入 langchain 的模型/向量/retriever 封装**。图：`intent →(chitchat/time/meta) direct_answer` / `→ retrieve → grade ─达标→ generate / ─不达标→ rewrite → retrieve`（`MAX_REWRITE=2`）`→ refuse_with_exit`（**复用 P4a 硬门控，不得削弱**）。问时间/日期类**不调 LLM**（正则 + `datetime` 直答）；意图判定超时/失败 → **降级为默认走检索**（路由挂了不能不答）。
3. **检索必须复用 P4c 的 scope 解析入口**：`_resolve_scope`（main 层）是越权静默忽略的唯一实现点，graph 内任何检索调用都必须走它解析出来的 scope，**不得绕过它直接 `rag.search(scope=...)`**——否则 P4c 刚守住的「不泄露存在性 / 空库不回落」会被旁路。请为这条写一条断言（越权夹经 graph 路径仍然 404 同表现 / 仍不外泄）。
4. **P4b 结转两条**：① `COMPRESS_PROMPT` 产出的摘要**逐条标注来源**（助手有据 / 用户自述未经核实），或摘要只压有据内容——现状是用户自塞的假事实会随历史进摘要、再作为"可采信池"成员被复述（坑 41，`c4_compress_fidelity_v2` 就是这条通道的演示：7341 元只存在于用户自塞背景资料，真实语料是硕士 7200 元/生·学年）；同时把 `cc-01` 的埋点改成**助手有据来源**，否则"压缩保真"与"不背书用户断言"会一直互相拉扯。② 改写上线后**重估 `history_gate_hit` 的"回指命中"档**（现规则：含它/该/此 + 1 个 2-gram 或 2 个单字即放行，偏宽），改写后的问句应能直接命中知识库，减少对历史通道的依赖。

## 改写策略（主次分明，别乱枪打鸟）

- **主力：意图归一 + 术语展开**（学平险 ↔ 学生平安保险 ↔ 意外伤害保险理赔；实测这是 F2 崩塌主因，**与句子长短无关**）。
- 辅助：去情境噪声（对应 F1 拒答失守场景）、学段限定（可接 P4c 的 `audience`）、拆子问题。
- **rerank 阈值要评估并书面记录**：`RERANK_MIN_SCORE=0.3` 是否改分级（top1 单判 / top1 与 top2 差值判定），或"标题命中核心术语时保底候选"，让"排序不佳"不再被放大成"完全无来源"。
- **禁止单独调 `MAX_PER_DOC`**（T10 实测 =1 会挤出关键块）。
- `db.fts_search()` 整句短语匹配失败后回退的 2-gram 计次是否加停用词过滤（现状"学校/我们/这项"等通用词把无关块顶榜），**书面评估**。
- 顺带处理遗留：`qa-09`（离校请销假）R@k 长期 0.0。

## 边界（越界即打回）

- **只准动**：`novaagent/pyproject.toml`（新增 `langgraph`）、`novaagent/novaagent/{graph.py(新),agent.py,rag.py,config.py,db.py,main.py}`、`novaagent/tests/**`、`evals/{cases.json,run_evals.py,query_variant_matrix.py,diag_retrieval.py}`、`docs/P4D.md`（新）、`docs/p4d/evidence/**`
- **禁改**：`novaagent/novaagent/refusal.py`（P4a 硬门控**只可调用、不得削弱**）、`evals/faithfulness.py`（judge 口径一变基线就不可比）、`novaagent/web/**`（本单纯后端 + 评测；若 graph 必须暴露前端字段，先在回执提出）、`corpus/**`、`sims/**`、`mcp/**`、`weknora/**`、`novaagent/data/agent.db*`
- **依赖安装**：`langgraph` 走 PyPI（清华源/官方源 Qoder 实测均 200 可装）。**装完把实际版本与传递依赖写进 `docs/P4D.md`**；不许顺手升级其它包。
- ⚠ `cases.json` 若要改，**只准新增用例、不得改动既有用例的断言字段**（P4c 那次 494 删/560 增只是序列化差异，我做了语义级比对才确认安全——你这次也请保持"旧用例逐字段不动"，我会同样核）。

## 完成标准（逐条自评，细节见 TASKS.md P4d 条目）

- **C1** 图落地（intent/grade/rewrite/refuse 分支齐备），**闲聊与时间类实测毫秒数**：闲聊路径首字延迟显著低于检索路径，普通问答不劣化——给对照表
- **C2** `rag.search` 返回质量信号 `{top_score, n_above_threshold, fused_candidates}`，`grade` 判定 `top_score≥0.3 且 n_above_threshold≥2`（可配）；**返回结构形状不得破坏 P4c 的 scope 语义**
- **C3** 新评测类型 `intent`（断言 `retrieval_trace.skipped=true`）与 `rewrite`（口语化长问句断言发生改写且最终命中）；**每条断言必须非空前置 + 失败判红**（坑 45/39）
- **C4** **矩阵 ≥6/8**（本单硬指标，见上）
- **C5** 书面记录三项：分级阈值取舍、FTS 停用词过滤取舍、`qa-09` 处理结果
- **C6** 零回归：**v1.9 = 43 用例**不回退（43/43、R@k ≥0.9412、拒答 1.0、`refusal_indomain` 6/6、`kb_hidden` 3/3、`scoped_qa` 3/3、四类 P4b 新路径用例全过、隔离全量 ok）；**忠实度中位一并观察**（若继续下滑必须解释并记账，不得沉默）；⚠ 若你扩了用例集，**必须同步 `cases.json` 的 `version` 字段 + `EVAL_BASELINE` + `HANDOFF` 三处口径**（坑 40；P4c 就发现该字段长期停在 v1.7 没跟着升）
- **C7** 冒烟 exit 0、`documents 65→65`、`chunks 487→487`；**探针与证据脚本一律与证据同批 commit**（P4c 的"`.tmp` 探针未入库"别再犯，坑 17 新形态）
- **C8** 评测隔离与 `conversation_id` 语义不被破坏（graph 化后每用例仍独立会话）

## 测试节奏

实现期只跑：`evals/diag_retrieval.py`（逐层归因）、`evals/query_variant_matrix.py`（矩阵，这是你的主指标，可以多次跑，它很快）、新增用例的 targeted 检查。**完整评测 + 冒烟只在全部落地后集中跑一轮**。Qoder 合并前独立把关一次。

## 交付

每完成一个可验证单元就 commit（前缀 `P4d:`）；回填「交接回执」，**放在 P4d 规格条目之后**（P4b 那次插在规格中间把两条规格挤散了）；内容含：分支/提交、diff 摘要、**矩阵改前改后逐条对照**、C1 延迟对照表、C3/C4 断言"能不能失败"的说明、集中评测那轮结果与退出码、忠实度观察、遗留清单、需 Qoder 决策的点。置 `IN_REVIEW`、`当前持棒=Qoder`。

## 不要做的事

不要顺手做 P4e 的联网搜索、不要动前端、不要改 `refusal.py` 或 `RERANK_MIN_SCORE` 之外的既有阈值来"凑矩阵数字"（改阈值必须书面记录取舍理由并复跑完整评测，否则是把问题藏起来）；不要合并 master；不要动 `C:/Users/<user>/WorkBuddy/Worktrees/` 那棵（只读）；不要把 `E:\<internal-affairs-dir>\` 真实学工数据或 `corpus/*/affairs/` 内容带进代码、文档、日志或网络；杀进程先查父进程链归属（坑 37）。环境输出与已知事实矛盾 → **硬停上报**。

=== PROMPT 结束 ===
