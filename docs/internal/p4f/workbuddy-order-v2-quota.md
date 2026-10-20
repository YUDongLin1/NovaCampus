# P4f 开单指令 v2（Qoder → WorkBuddy，2026-10-01）

> **v2 取代 v1**（`docs/p4f/workbuddy-order.md`）。变更原因：**用户 2026-10-01 指令——后续任务的测试与验证一律不得消耗用户填写的 API key 额度，必须用测试者自带的模型与额度。**
> 这条**同时约束复核方（Qoder）自己**：我原来的"合并前独立复跑一遍整轮"做法，烧的正是 `novaagent/.env` 里那把用户的 key，因此**改为零额度复核**（见 §5）。
> 整段可粘贴。

=== PROMPT 开始 ===

你是 **WorkBuddy**，NovaCampus（`E:\AILearn\NovaCampus`）的实现者；负责人/Review 是 Qoder。
本单 **P4f：辅导员 persona + 左侧会话栏重构 + C0 前置收口六条**。

## 0. 接手必读（按序）

1. `HANDOFF.md`：**⚠ 硬约束第 7 条（额度，新增、不可协商）**、三、运行状态、五、当前状态与下一步、六、坑 55/56/57/58/60/61/63/64/65。
2. `docs/TASKS.md`：P4f 条目（含 C0 六条）与「当前持棒」头部；P4e 两次 Review 结论（C0 从哪来）。
3. `docs/EVAL_BASELINE.md` §十九（canonical 命令与钩子）、`docs/P4E.md` §S1/§2.2。

## 0'. 🔌 额度与凭据纪律（本单最高优先级，**违反即打回**）

仓库 `novaagent/.env` 里的 key 是**用户本人的额度**。从现在起，**任何一次真发请求都不许落到它上面**——
包括你跑评测、跑探针、起服务做自测、跑忠实度 judge、跑联网检索、跑 embedding。

1. **用你自己带的模型与额度**：启动服务/跑评测前，在**会话环境变量**里注入
   `LLM_API_KEY` / `LLM_MODEL` / `LLM_BASE_URL`，以及 embedding 的 `EMBEDDING_API_KEY` / `EMBEDDING_MODEL` /
   `EMBEDDING_BASE_URL`。`config.env()` 的优先级是 `os.environ` > 仓库 `.env`，**注入即覆盖**，
   因此**不需要也不允许修改 `.env`**。
2. **key 值一律不得入库**：回执、报告、截图、日志、commit message、探针 JSON 里只允许出现
   **来源标签 + 模型名**（例：`llm_key_source=session_env, model=qwen-plus`）。
   出现疑似 key 片段 = 红线事故（这与 C0-① 同源：报告是提交进 git 的）。
3. **别口头保证，做成机器可核验的**（C0-⑥）：上一轮我们差点把一份 55/55 当成可复现结果，
   实际它依赖一个默认关闭的 env 钩子——同一类教训不能靠"我换了 key"这句话来防。
4. **省额度的具体做法**（都是这两轮实测踩出来的）：
   - 实现期只做**不烧额度**的检查：尺子自测（纯本地）、DB 只读副本探针、离线重放已落盘答案、静态审计、`/api/health`；
   - **整轮评测一单只跑一次**；要"某条判据能判红"的证据时用**假 transport / 离线重放**，不要真调用；
   - 探针按最小面跑（单问句、单用例），不要顺手全量；联网用例挑快问句并说明实测耗时。

## 1. 纪律

- 从 `master`（含 P4e 全部，`dbdec42`）切 **`task/P4f-persona`**。**不得合并 master**、不得自行开 P4g。
- **禁改**：`sims/**`、`mcp/**`、`weknora/**`、`evals/faithfulness.py`、`novaagent/novaagent/refusal.py`。
- **允许改**：`novaagent/novaagent/{db.py,agent.py,main.py,config.py,graph.py,websearch.py}`、`novaagent/web/**`、
  `novaagent/tests/**`、`evals/{cases.json,run_evals.py}`、`docs/P4F.md`、`docs/p4f/**`、
  `docs/p4d/run_with_server.sh`（C0-⑤）、`docs/EVAL_BASELINE.md`（**仅限** C0-⑥ 那一节，别扩范围）。
- `agent.db` 不得被脚本改：迁移只进 `db.py` 启动期 `_migrate()`（幂等），并在**库副本**上验证连跑两遍一致。
- 数据红线不变：`<内部学工数据目录>\` 不入库不外发；`corpus/*/affairs/` 只本地；含学生姓名的名单页禁止抓取/入库；
  演示口令不进 KB 与任何出网请求；**联网请求只发送当前问题文本**。

## 2. C0 前置收口（**merge-blocking：C0-①、C0-③、C0-⑥**）

- [ ] **C0-①（🔴 密钥进 git 的形状，先做）** `evals/run_evals.py` 的 `env_flags.client_env` 现在收**所有** `NOVA*`
  变量，而评测报告**要提交进 git**。今天只有 `NOVAAGENT_EVAL_TEMPERATURE`（无害），但只要有人
  `export NOVAAGENT_LLM_API_KEY=...`，密钥就入库并永久留在历史里。
  → 改**显式白名单** + 一条能判红的单测（断言密钥类键名不在 `client_env`，同时断言白名单项确实在，
  防"过滤过头变空集"假通过，坑 45）。
- [ ] **C0-② 口径规则**：**问句级/判据常量级变更也算口径变更**，必须升 `version` 并在 `EVAL_BASELINE` 记一行
  （S2 换了 `ss-*` 长问句、渐进性阈值 300→150，却仍标 v2.4 → 同一标签覆盖两种刺激）。
- [ ] **C0-③（闸门作用域）** grounding 闸门被套在**不需要事实回答的轮次**上：P4e S2 复核实测
  默认档命中 12 次/重生失败 11 次、canonical 档命中 16/失败 14，**全部来自 `cc-01` 种植轮，`final` 轮从未命中**
  ——「重生一次都没救回来」＝前提不成立（种植轮是往会话里塞背景，模型回「记下了」才是对的）。
  → 给闸门加**轮次类型判定**（只对期待事实回答的轮次生效），判据写进注释、**不许用「长度<30 字」糊过去**。
  验收：整轮 `grounding_gate` 记账里种植轮命中归零，且 `qa-17`/`ss-03` 兜底能力不回退。
- [ ] **C0-④** `WEB_SEARCH_TIMEOUT_S=60` 名实不符：httpx 那个是**空闲超时**不是**总时限**
  （实测同问句 12.3s / **79.4s**，60s 没截断）。做总时限 + 双层（idle 20s / 总 45s）或改名 + 文档写清等待预期；
  补一条用**假 transport** 的慢响应必判红单测（不打真实网络，省额度）。
- [ ] **C0-⑤** `docs/p4d/run_with_server.sh` 收尾用 MSYS `kill $SRV` **杀不掉 Windows 进程**：
  复核实测该脚本打印 `[server] done rc=0, shutting down 8936` 之后 `:8936` **仍在监听**；
  负责人自己也留过 :8906/:8907、:8923 孤儿（都是实现方复查端口时发现的）。
  → 改 `taskkill //PID x //F` 或 psutil，并在退出前**按端口复查打印** `[port-check] :N closed=True/False`，
  False 时以非 0 退出。
- [ ] **C0-⑥（🔌 额度可核验化，本单新增）** 把 §0' 做成代码而不是口头承诺：
  - `config.py` 加 `key_source(key)`：返回 `session_env` / `repo_dotenv` / `unset` 之一
    （判据 = 该键是否在 `os.environ`），**绝不返回或记录 key 值本身**；
  - `/api/health` 的 `flags` 增加 `llm_key_source`、`embedding_key_source`（`llm_model` 已有）；
  - `run_evals.py` 的 `env_flags.server` 自动带上这两个字段 → 每份入库报告自证用谁的额度；
  - **闸门规则**：报告里 `llm_key_source` 或 `embedding_key_source` 读数为 `repo_dotenv` 的整轮结果**一律不认**
    （那等于烧用户额度），并写进 `docs/EVAL_BASELINE.md` canonical 命令段与 `docs/P4F.md`；
  - 自测：在"注入 / 不注入"两种状态下各取一次 `/api/health`，落盘两份 flags 对照（**只读 health，不烧额度**）。

## 3. P4f 主体（设计见 `docs/P4.md` M8）

- [ ] `personas` 表（owner/name/college/persona_prompt/style/bound_folder_ids/bound_categories/visibility/is_default）
  + `conversations.persona_id`；persona 删除后历史会话保留并标记「人设已删除」。
- [ ] `SYSTEM_PROMPT` → `build_system_prompt(persona, ctx_local, ctx_web)`；
  ⚠ **防幻觉规则 1–9 硬编码在模板里，persona 段不得覆盖、删改或削弱**；
  必须有一条**注入攻击用例**（「忽略以上规则」「你现在是……」类）**真的判红**。
- [ ] 权限：辅导员只管自己的 persona；学生只能用 `public`；admin 管全部。
  **绑定库仍受 P4c 的 RBAC 交集约束，persona 不得提权**（越权静默忽略、不可见=不存在、空 scope 不回落；
  复用 `_resolve_scope` 入口，不得绕过）。
- [ ] 前端：左侧统一会话栏（列表 + 新建 + 辅导员选择器），账户入口移到会话栏最底部；
  对话中可切换 persona。新增 js/css 走既有 `/js/{name}`、`/css/{name}` 路由，`api.js` 最先加载；
  别破 P4b-0 的「行为零变化」不变量。
- [ ] 新增评测类型 `persona`：同一问题两个 persona 下**风格有差异且来源集合一致**
  （后半条是防"用人设偷换检索结果"，比风格差异更重要）。
- [ ] UI 细节（`#w-content` 文本框等）属 P4g，**本单不做**。

## 4. 测试节奏（一次集中验证，别多跑）

实现期只做 §0'.4 列的**不烧额度**检查；**全部落地后集中跑一轮**：
canonical 命令 + 你自己的 key，要求 `N/N 且退出码 0`，并**如实附不带钩子那一档**（现在应为 54/55 且失败项只有 `ss-03`）；
冒烟 `exit 0`、`documents 65→65`；跑完 `kb_doctor` 回 **65/487**。
⚠ 取退出码不接管道（坑 55）；整轮前做一次**单请求端到端自证**，顺手读 `env_flags` 里的 key_source（坑 57）；
⚠ **只读探针不得与整轮评测并发取库内计数**（坑 58：负责人因此把 42 读成 44 写进三份文档）；
⚠ `evals/badcases.json` 会被服务端滚动写脏，**按主键集合比对后 `git checkout --` 还原**，别按 +/- 行数判性质（坑 56）；
⚠ Windows 终止进程用 `taskkill //PID x //F` 或 psutil，并**按端口复查**（坑 61 + C0-⑤）；
⚠ 定任何判据阈值前**先跑 ≥5 次取分布**并报告与观测值的最小距离（坑 63）；
⚠ 硬门控落地前先枚举它会被套在哪些轮次类型上（坑 64 = C0-③ 的由来）；
⚠ 忠实度按**区间**读（0.8889~0.9722）且逐条可在 0.5↔1.0 互换，不得当点值用作闸门；`faithfulness.py` 禁改。

## 5. 交回格式与"零额度可复核"要求（**关键变化**）

因为**复核方不再复跑烧额度的整轮**（见上），你交回的东西必须**能被我离线复算**，否则等于没有独立把关。逐条要求：

- 状态 `IN_REVIEW`、**当前持棒=Qoder**、分支与提交列表、未合并 master、工作区是否干净。
- 逐条完成标准打勾，附「哪个文件哪个字段 / 哪份证据文件」。
- **整轮原始报告入库**（`reports/eval_report_*.json` 两档都要），报告里必须能看到
  `env_flags.server.llm_key_source=session_env`、`embedding_key_source=session_env`、`grounding_gate` 逐用例记账。
- **把"能被离线复算"的东西落盘**：断言用到的输入与模型输出原文（答案文本、事件序列、耗时）存成证据 JSON，
  让我的纯函数复算脚本能直接读——**判据本身是纯函数，我复算不需要 key**。
- C0-①③⑥ 各附**能判红的自测输出**（不需要真调用：畸形输入、假 transport、白名单缺失项都要构造反向用例）。
- 端口/进程交代含 `[port-check]` 原文；本轮大约烧了多少次调用、用的什么模型/endpoint（**不写 key 值**）。
- 遗留与需裁决项如实列出，不要自己拍板。

不许自行开下一单。做完交回，我按「集中一次独立把关」复核——我的复核方式是**零额度那一套**：
跑纯本地尺子自测与离线重放、读你入库的原始报告与 flags、做静态审计与 DB 副本探针；
只有在你入库的证据不足以让我复算时，我才会回来请你用你的额度补跑指定探针，**不会动用户那把 key**。

=== PROMPT 结束 ===
