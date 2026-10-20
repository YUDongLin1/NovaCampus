# P4b 开单指令（粘进 Zcode 新会话）

> 由 Qoder 于 2026-09-30 生成。规格正文以 `docs/TASKS.md` 的 **P4b 条目（C1~C10）** 为唯一事实源。
> **本单是本阶段工作量最大的一单，也是唯一"从零建数据模型"的一单**：`conversations` 表现在根本不存在。
> ⚠ 若你的日额度中途用尽：**不要硬撑**，把当前可验证单元 commit（前缀 `P4b:`）并在回执写清
> "已做到哪一步 / 下一步从哪个函数开始 / 哪些验收还没跑"，Qoder 接受半成品交接。

=== PROMPT 开始 ===

你是 **Zcode**，NovaCampus 项目（`E:\AILearn\NovaCampus`）的实现者。**当前持棒=Zcode**，现在下发 **P4b：会话与上下文管理（多轮 + 65% 压缩 + 左侧会话列表）**。

前四单已由 Qoder Review 通过并合并：P3b `2234fc8`、P4a `827e1ae`、P4a-1 `5399a5e`、**P4b-0 `e947259`（前端已拆完，你可以直接在多文件布局上干活）**。

按序做：

1. 读 `docs/TASKS.md` 头部「当前持棒」确认是你，读 **P4b 条目**（目标 / 已实测现状 / 白名单 / 黑名单 / C1~C10 / 验收命令）。
2. 读 `docs/P4.md` §M4（数据模型、预算与压缩、API、边界、评测）与 §五（通用验收口径）、§六（合规红线）。
3. 读 `docs/P4B0.md`（前端拆分后的布局与静态路由规则）与 `HANDOFF.md` §六 踩坑清单——本单特别相关的是：
   坑 4（heredoc 破坏三引号/SQL，**改文件一律用 Write 写补丁脚本**）、坑 5（GBK 控制台）、坑 8（`NO_PROXY`）、
   坑 10（**改代码/改 .env 必须重启进程**，`restart` 不重读环境变量）、坑 11（FTS rebuild）、
   坑 16（qa-08 轮换波动，单轮 FAIL 先查是检索还是采样）、坑 17（落盘≠入库）、坑 18（claim→字段）、
   坑 22（**新增能力必须配"能测出它失败"的用例**）、坑 23（smoke 污染 KB）、坑 29（取证先于清理）、
   坑 30（后端契约改了要查消费端）、坑 33（**探针取到非空才允许落盘**）。
4. 切分支：`git checkout -b task/P4b-conversation-context`（从 master `e947259` 切）。

## 第 0 步：BEFORE 基线（先取证，再动代码）

起服务：`cd novaagent && NO_PROXY="127.0.0.1,localhost" NOVAAGENT_EVAL_TEMPERATURE=0 .venv/Scripts/python.exe -m uvicorn novaagent.main:app --port 8900`

在**改动之前**把现状留痕到 `docs/p4b/evidence/before/`，至少包含：

- `db_schema.txt`：`PRAGMA table_info(messages)` 全字段 + `select count(*) from messages` + 按 `user_id` 分组计数 + `conversations` 表**不存在**的证据（`select name from sqlite_master where name like 'con%`）。
- `no_history_proof.txt`：同一会话里连问两问（第二问用代词指代第一问的实体，例如先问「研究生休学要哪些材料」再问「那**它**需要导师签字吗」），把两次 `/api/chat` 的 `answer` 与请求体一起落盘——**这就是本单要修的失守点**（现状第二问必然指代失败或答非所问）。要留**能复现的 curl/python 命令**。
- `api_calls.txt`：`grep` 出前端全部 `api('...')` / `fetch('...')` 调用点清单（P4b-0 的 `before/api_calls.txt` 是 20 条，本单要新增会话相关调用，验收时按"只增不减"对账）。
- 五条路径的 DOM 断言 + 截图（登录 / 问答 SSE+来源 / KB 列表+分块弹窗 / 周报 / 设置），命名与 `docs/p4b0/evidence/before/` 对齐，便于跨单比较。
- ⚠ **探针纪律（Qoder 复核 P4b-0 时抓到的真实缺陷）**：断言脚本必须"**取到非空才落盘**"——上一单的 `before/02_student_main.json` 记了 `kb_rows: 0`、`04` 记了 `rows: []`，实测分别是 **42** 和 **3**，探针在页面还没渲染完就抓了空值。写探针时先 `await` 到目标元素出现，再断言"条数 > 0"，取不到就报错而不是写 0。

## 已实测的现状（别按猜测做，这些数字我 2026-09-30 亲自查过）

- `sqlite_master` 里**没有** `conversations` 表；`messages` 只有 `id/user_id/role/content/created_at` 五列，**没有 `conversation_id`**。
- `messages` 共 **2588 条**，其中 `user_id=3`（counselor）占 **2374 条**——绝大多数是历次评测与冒烟写入的。
- `agent.py` 的 `chat_for()`（211 行）与 `chat_stream_for()`（255 行）里 `messages = [system, 当前问题]`（225 / 281 行），**从不注入历史**。
- `main.py:527` 已有 `GET /api/conversations?limit=`，但它返回的是**该用户扁平的最近消息**，不是会话。
- `config.py:56 MODEL_CANDIDATES` 各候选**没有 `ctx` 字段**。
- 前端已是多文件：`web/index.html`(168 行骨架) + `web/css/theme.css` + `web/js/{api,ui,chat,kb,weekly}.js`；`main.py` 的 `/css/{name}`、`/js/{name}` 是**通用只读路由**，**新增 js/css 文件不必再改 `main.py`**，只需在 `index.html` 按依赖顺序加 `<script src>`（`api.js` 必须最先）。

## 本单的三个硬设计约束（我作为负责人定的，不要自行改方向）

1. **评测隔离优先**：加了历史注入之后，若 `run_evals.py` 仍复用同一会话，**用例之间会互相污染上下文**，v1.7 基线立刻失去可比性（这是本单最大的隐性风险）。要求：每个评测用例**各自新建会话**（或显式传"不注入历史"），并在 C7 里用断言证明"跑完 36 用例后各用例会话互不串上下文"。**不得为了让评测过而关掉历史注入。**
2. **迁移不得删数据，但也不得淹没 UI**：2374 条历史按 `user_id` + 相邻间隔 >30min 切分成历史会话；**迁移出来的会话一律 `archived=1`**，前端列表默认只列未归档、另给「显示归档」开关。理由：不删用户数据是红线，但把上千条评测记录铺进左侧栏会把产品体验做坏。
3. **压缩是"摘要 + 原文可回溯"，不是"删原文"**：`conversation_summary` 存压缩结果，`messages` 原文永久保留；压缩调用失败 → **降级为截断最早消息并在前端明确标注"已截断"**，绝不静默丢内容。`COMPRESS_PROMPT` 必须要求保留**数字 / 日期 / 条款号 / 未决事项 / 对象代称**（丢数字就等于丢事实）。

## 边界（越界即打回）

- **只准动**：`novaagent/novaagent/{db.py,agent.py,main.py,config.py,llm.py}`、`novaagent/web/{index.html,js/**,css/**}`（建议新增 `web/js/conversations.js`，别把会话栏逻辑再挤进 `chat.js`）、`novaagent/tests/**`、`evals/{cases.json,run_evals.py}`、`docs/P4B.md`（新）、`docs/p4b/evidence/**`
- **禁改**：`novaagent/novaagent/refusal.py`（P4a 硬门控**只可调用、不得削弱**）、`evals/faithfulness.py`（judge 口径一变基线就不可比）、`corpus/**`、`sims/**`、`mcp/**`、`weknora/**`、`novaagent/data/agent.db*`（**不许用脚本直接改库**，迁移必须走 `db.py` 的启动迁移代码）
- ⚠ 本单**禁止引入任何新依赖**（不加 tokenizer、不加前端框架、不加公网 CDN）。token 一律用 `ceil(chars/1.6)` 估算，并在 `docs/P4B.md` 里**明确标注为估算值**。
- ⚠ 前端**不得新增权限判断**（延续 P4b-0 的 C2）：会话可见性一律后端按 `user_id` 过滤，越权访问别人的 `conversation_id` 必须返回与"不存在"相同的表现（沿用「不可见=不存在」约定，不泄露存在性）。

## 完成标准（C1~C10，逐条自评）

- **C1 数据模型与迁移**：`conversations` / `conversation_summary` 建表、`messages.conversation_id` 加列；**迁移前后 `select count(*) from messages` 完全相等**（证据：迁移前后各一份 `db_schema.txt` + 计数），且迁移代码幂等（重启两次不重复切分）。
- **C2 多轮真能用**：第 0 步那条"代词指代"失守问句，改后**第二问答案正确指代第一问实体**；before/after 两份证据同名配对。
- **C3 上下文预算**：`MODEL_CANDIDATES` 带 `ctx`；`CONTEXT_BUDGET = ctx*0.65`；未超预算完整保留（时间正序），超预算才压缩。给出**实测数字**：注入前后各多少 token（估算）、预算多少。
- **C4 压缩保真**：构造超预算历史，断言 `compressed=true` 且**历史里的关键数字/日期仍出现在答案中**（至少 3 个不同数字，逐个列出出处消息 id）。
- **C5 SSE 与前端**：新增 `{"type":"context","used","budget","compressed"}` 事件；前端占用条可见且数值与事件一致；切换会话时**中止进行中的 SSE**（`AbortController`），实测切走后无残留 delta 写入旧会话。
- **C6 会话 CRUD**：list / create / rename / archive / delete + messages 分页；删除级联删消息与摘要（**只删该会话的**，别的会话计数不变，给对账表）；标题默认取首问前 20 字。
- **C7 评测隔离**：36 用例各用独立会话；跑完断言"用例 A 的历史不出现在用例 B 的上下文里"（打印两个会话的 message id 集合，交集为空）。
- **C8 零回归**：v1.7 基线不回退——**36/36、R@k ≥0.9412、拒答 1.0、`refusal_indomain` 6/6、`kb_hidden` 3/3**。⚠ 忠实度**三轮实测为 0.9706 / 1.0 / 0.9412，中位 0.9706**（P4b-0 复核补齐的口径），逐轮摆动属**已裁决移交 P4d 的 judge 学段声明盲区**，不要当回归去"优化"，更不要为指标删掉学段声明。
- **C9 冒烟与 KB 守恒**：`smoke_test.py` 全过（GBK 控制台 exit 0），跑完 `documents` **65→65**、`chunks` **487→487**；新增会话/消息不得污染 KB。
- **C10 证据入库对账**：`git diff --name-status master...HEAD` 与 `docs/P4B.md` 引用的每个证据文件**逐条对上**，并 `git check-ignore -v` 排查静默排除（坑 17 已在 P3a 抓过一次、P4b-0 复核又确认了一次例外规则是真的必要）。

## 验收命令

```bash
cd /e/AILearn/NovaCampus && export NO_PROXY="127.0.0.1,localhost"
# 起服务(改代码/改 config 后必须重启进程,坑 10)
cd novaagent && NOVAAGENT_EVAL_TEMPERATURE=0 .venv/Scripts/python.exe -m uvicorn novaagent.main:app --port 8900
# 迁移与计数守恒
/d/anaconda3/python.exe -c "import sqlite3;c=sqlite3.connect('novaagent/data/agent.db');print('messages',c.execute('select count(*) from messages').fetchone()[0]);print('conv',c.execute('select count(*) from conversations').fetchone()[0]);print('no_cid',c.execute('select count(*) from messages where conversation_id is null').fetchone()[0]);print('kb',c.execute('select count(*) from documents').fetchone()[0],c.execute('select count(*) from chunks').fetchone()[0])"
# 多轮代词指代(第 0 步同一条问句)
/d/anaconda3/python.exe -c "import httpx;N='http://127.0.0.1:8900';t=httpx.post(N+'/api/login',json={'username':'counselor','password':'counselor123'}).json()['token'];H={'Authorization':'Bearer '+t};import json;cid=httpx.post(N+'/api/conversations',json={'title':'probe'},headers=H).json()['id'];a=httpx.post(N+'/api/chat',json={'question':'研究生申请休学需要提交哪些材料?','conversation_id':cid},headers=H).json();b=httpx.post(N+'/api/chat',json={'question':'那它需要导师签字吗?','conversation_id':cid},headers=H).json();print(json.dumps({'q1':a['answer'][:80],'q2':b['answer'][:160]},ensure_ascii=False))"
# 评测与冒烟
PYTHONIOENCODING=gbk novaagent/.venv/Scripts/python.exe evals/run_evals.py
PYTHONIOENCODING=gbk novaagent/.venv/Scripts/python.exe novaagent/tests/smoke_test.py
# 边界自查
git diff --name-only master...HEAD | grep -vE "^novaagent/(web/|novaagent/(db|agent|main|config|llm)\.py)|^novaagent/tests/|^evals/(cases\.json|run_evals\.py)|^docs/" && echo "[FAIL] 越界" || echo "[PASS] 仅在白名单内"
```

## 交付

每完成一个可验证单元就 commit（前缀 `P4b:`）；回填「交接回执」（分支/提交/diff 摘要/**迁移前后计数对账**/C1~C10 逐条自评/before-after 同名证据清单/**实测 token 数字**/遗留问题/需要 Qoder 决策的点），置 `IN_REVIEW`、`当前持棒=Qoder`。

## 不要做的事

不要顺手做 P4c 的文件夹与 `@` 指定库、不要做 P4d 的 LangGraph 编排、不要做 P4f 的 persona（`conversations.persona_id` **建表时留列即可**，本单不实现人设逻辑）；不要改 `RERANK_MIN_SCORE` / SYSTEM_PROMPT 的防幻觉规则；不要为了压缩效果去删 `messages` 原文；不要合并 master；不要动 WorkBuddy 工作树；不要把 `<内部学工数据目录>\` 真实学工数据或 `corpus/*/affairs/` 内容带进代码、文档、日志或任何网络请求。环境输出与已知事实矛盾 → **硬停上报**，不要绕过去。

=== PROMPT 结束 ===
