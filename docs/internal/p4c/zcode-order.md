# P4c 开单指令（粘进 WorkBuddy 会话）

> 由 Qoder 于 2026-09-30 生成。规格正文以 `docs/TASKS.md` 的 **P4c 条目（C1~C9）** 为唯一事实源。
> ⚠ 本单起实现者是 **WorkBuddy**（Zcode 日额度用尽，用户 2026-09-30 变更分工）——回执署名写 WorkBuddy。
> ⚠ 测试节奏按用户要求调整：**实现期只跑针对性最小检查，功能全落地后再集中跑一轮完整评测+冒烟**。

=== PROMPT 开始 ===

你是 **WorkBuddy**，NovaCampus 项目（`E:\AILearn\NovaCampus`）的实现者。**当前持棒=WorkBuddy**，现在下发 **P4c：KB 文件夹 + `@` 指定检索范围 + 学段元数据**。

前序均已合并 master：**P4b 会话与上下文管理 `0499a89`**（第一回被打回 5 条、修复后第二次把关通过——它的教训见下）、P4b-0 前端拆分 `e947259`、P4a-1 `5399a5e`、P4a `827e1ae`、P3b `2234fc8`、P3a `b8245c2`。

按序做：

1. 读 `docs/TASKS.md` 头部「当前持棒」确认是你，读 **P4c 条目**（目标 / 已实测现状 / 白名单 / 黑名单 / 三个硬设计约束 / C1~C9 / 测试节奏）。
2. 读 `docs/P4.md` §M5（数据模型、API、检索 scope、`@` 语法、F3 学段、边界、评测）与 §五（通用验收）、§六（合规红线）。
3. 读 `HANDOFF.md` §六 踩坑清单，本单特别相关：**坑 33**（探针"取到非空才落盘"——P4b-0 复核刚抓到两条取空值的基线）、**坑 39**（断言不判红=没有断言；新代码路径必须被评测真的走到——P4b 第一回就是栽在这）、**坑 40**（评测集扩型是口径变更要记账：现在是 **v1.8 = 40 用例**，看到 40/40 才是满通过）、**坑 17**（落盘≠入库）、**坑 18**（claim→字段）、**坑 22**（新能力要配能测出它失败的用例）、**坑 30**（后端契约改了要查消费端）、**坑 37**（杀进程/查服务归属：命令行子串匹配会自杀；服务归持棒者）、**坑 4/5/8/10**（heredoc、GBK、`NO_PROXY`、改代码要重启）。
4. 切分支：`git checkout -b task/P4c-kb-folders`（从 master `0499a89` 切）。

## 第 0 步：BEFORE 基线（先取证再动代码）

起服务：`cd novaagent && NO_PROXY="127.0.0.1,localhost" NOVAAGENT_EVAL_TEMPERATURE=0 .venv/Scripts/python.exe -m uvicorn novaagent.main:app --port 8900`

留痕到 `docs/p4c/evidence/before/`，至少：

- `db_schema.txt`：`PRAGMA table_info(documents)` 全列（实测**没有** `folder_id`/`audience`）、`folders` 表**不存在**的证据、`documents 65 / chunks 487` 计数。
- `search_signatures.txt`：`rag.search(query, min_rank)`、`rag.search_with_quality(query, min_rank)`、`db.all_chunks_for_search(min_rank)` 三个当前签名与行号（本单要给它们加 scope，改前先留底）。
- `kb_page_probe.json` + 截图：KB 页现状（分类下拉 + 文档表格），**探针必须断言取到非空**（如 `kb_rows>0`）才落盘。
- `no_scope_proof.txt`：同一问句在全库检索下的 `sources` 与 `top_score`（本单要对照"指定库后来源全属该库"，没有这个基线就没法证明 scope 生效）。

## 三个硬设计约束（我作为负责人定的，不要自行改方向）

1. **RBAC 优先于 scope**：`@` 指定的 folder 若该角色无权见，**静默忽略**，沿用「不可见 = 不存在」约定（对齐 `db.get_document()` 与 P4b 的会话越权处理）——响应里**不得泄露该 folder 是否存在**。
2. **`@xxx` 绝不能混进 `question` 文本**：前端解析后 `question` 与 `scope` **分离传参**。`@` 残留进问句会同时污染 embedding 与 FTS，而 P4d 的查询改写正要靠干净的问句做术语展开。C4 要给出**后端实际收到的请求体**作为证据。
3. **`@` 指定的库为空 → 明确提示，绝不静默回落全库检索**：回落等于把用户没授权范围的内容答出去，属安全事故。

## 边界（越界即打回）

- **只准动**：`novaagent/novaagent/{db.py,rag.py,agent.py,main.py,config.py}`、`novaagent/web/{index.html,js/**,css/**}`、`novaagent/tests/**`、`evals/{cases.json,run_evals.py}`、`docs/P4C.md`（新）、`docs/p4c/evidence/**`
- ⚠ `agent.py` 本单**只准做一件事**：把 `scope` 从 API 透传到 `rag.search_with_quality()`。P4b 刚交付的 `history_gate_hit`、可采信池、上下文构建与压缩逻辑**一行都不许改**（要改先在回执提出）。
- **禁改**：`novaagent/novaagent/{refusal.py,llm.py}`、`evals/faithfulness.py`（judge 口径一变基线就不可比）、`corpus/**`、`sims/**`、`mcp/**`、`weknora/**`、`novaagent/data/agent.db*`（**不许脚本改库**，迁移走 `db.py` 启动代码）
- **零新依赖**：不引前端框架/构建工具/公网 CDN；新增 js/css **不必**改 `main.py`（`/js/{name}`、`/css/{name}` 是通用只读路由），只需在骨架按依赖顺序加 `<script src>`，`api.js` 必须最先。
- **前端不得新增权限判断**（延续 P4b-0 C2 / P4b C6）：可见性一律后端按 `role_min` + scope 取交集。

## 完成标准（C1~C9，逐条自评；细节见 TASKS.md）

- **C1** 三处 schema 落地 + **迁移不删数据**（迁移前后 `documents`/`chunks` 计数相等）+ **幂等**（重启两次不重复建表/赋值）
- **C2** 文件夹 CRUD/层级/重命名/移动/批量移动；同层重名拒绝；**删除非空文件夹默认拒绝**
- **C3** `rag.search(query, min_rank, scope=None)`；给出**三输入对照表**：全库 / 指定正确 folder / 指定越权 folder 下的 `sources` 与 `top_score`
- **C4** `@` 多选在前端解析、`question` 与 `scope` 分离；断言后端收到的 `question` 无 `@` 残留（贴请求体）
- **C5** `audience` 可标注可筛选；学段敏感问题无 hint 时**默认追问**（不猜）
- **C6** KB 页改「文件夹树 + 文档列表」，样式沿用「学术水墨 × 朱砂印」主题变量
- **C7** 新增 `scoped_qa` ≥2 条用例，**断言必须能失败且失败影响退出码**（坑 39）
- **C8** **v1.8 = 40 用例**零回归（40/40、R@k ≥0.9412、拒答 1.0、`refusal_indomain` 6/6、`kb_hidden` 3/3、四类新路径用例全过、隔离断言 ok）。⚠ 忠实度中位 0.9706 属已裁决移交 P4d 的 judge 学段声明盲区，**不得为指标删声明**；`qa-08`/`qa-02` 是**在案波动用例**，单轮失败按坑 16 判性质（查是检索还是采样），别乱调
- **C9** 冒烟 exit 0、`documents 65→65`、`chunks 487→487`；证据全部 `git diff --name-status` + `git check-ignore -v` 对上（坑 17）

## 测试节奏（用户 2026-09-30 明确要求）

实现期**只跑针对性最小检查**：相关单测、单条 API 断言、迁移计数对账。**C1~C7 全部落地后集中跑一轮**完整评测 + 冒烟即可，**不要每完成一个单元就复跑全套**（P4b 那轮你跑了三轮评测，其实一轮就够，省下的时间用来把证据写扎实）。Qoder 合并前会独立做一次集中把关。

## 交付

每完成一个可验证单元就 commit（前缀 `P4c:`）；回填「交接回执」（分支/提交/diff 摘要/**迁移前后计数对账**/C3 三输入对照表/C4 请求体实测/C7 新用例清单与"它能不能失败"/集中评测那一轮的结果与退出码/遗留清单/需 Qoder 决策的点），置 `IN_REVIEW`、`当前持棒=Qoder`。**回执请放在 P4c 规格条目之后**（P4b 那次插在规格中间把两条规格挤散了）。

## 不要做的事

不要顺手做 P4d 的 LangGraph 编排与查询改写；不要动 `RERANK_MIN_SCORE`、`MAX_PER_DOC`、SYSTEM_PROMPT 防幻觉规则；不要单独调 `MAX_PER_DOC`（T10 实测 =1 会挤出关键块）；不要合并 master；不要动 `C:/Users/<user>/WorkBuddy/Worktrees/` 那棵树（只读）；不要把 `<内部学工数据目录>\` 真实学工数据或 `corpus/*/affairs/` 内容带进代码、文档、日志或任何网络请求；杀进程别用命令行子串匹配（坑 37）。环境输出与已知事实矛盾 → **硬停上报**。

=== PROMPT 结束 ===
