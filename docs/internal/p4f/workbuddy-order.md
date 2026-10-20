> ⚠ **本文件已被 v2 取代（2026-10-01）——请看 `docs/p4f/workbuddy-order-v2-quota.md`**：用户指令「后续任务的测试与验证不得消耗我的 API key 额度，用测试者自己的模型和额度」改变了本单的凭据与复核方式，v1 的 §2/§4/§5 已不完整。**不要粘 v1。**

# P4f 开单指令（Qoder → WorkBuddy，2026-10-01）

> 背景：**P4e 已整体合并 `master`**（联网开关 + 本地/联网来源分区 + S1 流式恢复 + S2 尺子与可审计性），基线 **v2.4 / 55 用例**。
> 本单 = **P4f 辅导员定制（persona）+ 侧边栏重构**，外加 **C0 前置收口五条**（P4e 复核期间攒下的，含一条红线形状）。
> 整段可粘贴。

=== PROMPT 开始 ===

你是 **WorkBuddy**，NovaCampus（`E:\AILearn\NovaCampus`）的实现者；负责人/Review 是 Qoder。
本单 **P4f：辅导员 persona + 左侧会话栏重构 + C0 前置收口五条**。

## 0. 接手必读（按序）

1. `HANDOFF.md`：三、运行状态；五、当前状态与下一步；**六、坑 55/56/57/58/60/61/63/64**（都是最近两天新增、本单直接相关）。
2. `docs/TASKS.md`：P4f 条目（M8 设计要点）与「当前持棒」头部；P4e 的两次 Review 结论（理解 C0 从哪来）。
3. `docs/EVAL_BASELINE.md` §十九：canonical 命令与「为什么必须带钩子」；`docs/P4E.md` §S1/§2.2。

## 1. 纪律

- 从 `master`（当前含 P4e 全部）切 **`task/P4f-persona`**。**不得合并 master**、不得自行开 P4g。
- **禁改**：`sims/**`、`mcp/**`、`weknora/**`、`evals/faithfulness.py`、`novaagent/novaagent/refusal.py`。
- **允许改**：`novaagent/novaagent/{db.py,agent.py,main.py,config.py,graph.py,websearch.py}`、`novaagent/web/**`、
  `novaagent/tests/**`、`evals/{cases.json,run_evals.py}`、`docs/P4F.md`、`docs/p4f/**`、`docs/p4d/run_with_server.sh`（C0-⑤ 用）、
  `docs/EVAL_BASELINE.md`（**仅限** C0 记账需要的那一节，别再扩范围）。
- `agent.db` 不得被脚本改动：迁移只写进 `db.py` 启动期 `_migrate()`（幂等加表/加列），并在**库副本**上验证连跑两遍结果一致。
- **绝对红线不变**：`<内部学工数据目录>\` 真实学工数据永不入库/上传；`corpus/*/affairs/` 只本地不提交；
  含学生姓名的公示/名单页禁止抓取或入库；演示口令（admin123/counselor123/student123、Grafana）不得进 KB 或任何出网请求；
  **联网请求只发送当前问题文本**（C0-① 就是把这条的形状补严）。

## 2. C0 前置收口（P4e 复核攒下，**merge-blocking：C0-① 与 C0-③**）

- [ ] **C0-①（🔴 红线形状，先做）** `evals/run_evals.py` 的 `env_flags.client_env` 现在收集**所有** `NOVA*` 环境变量，
  而**评测报告是要提交进 git 的**。今天实测只有 `NOVAAGENT_EVAL_TEMPERATURE`（无害），
  但只要有人按惯例 `export NOVAAGENT_LLM_API_KEY=...`，密钥就会被写进入库报告并永久留在历史里。
  改成**显式白名单**（只收 `NOVA_GROUNDING_*`、`NOVA_GRAPH_ENABLED`、`NOVA_MAX_REWRITE`、`NOVA_FUSION_TOP_K`、
  `NOVAAGENT_EVAL_TEMPERATURE` 这类非敏感项），并补一条**能判红**的单测：
  构造一个含 `NOVAAGENT_LLM_API_KEY` 的环境，断言它**不出现**在 `client_env` 里（同时断言白名单项确实在，防"过滤过头"变成空集假通过）。
- [ ] **C0-②** 口径规则落地：**问句级/阈值级变更也算口径变更**。`ss-*` 问句在 S2 被换成长问句、渐进性阈值 300→150，
  但 `version` 仍写 v2.4 → 同一个标签现在覆盖两种刺激。本单起：改 `question`、改任何 `STREAM_MIN_SPAN_MS` 类判据常量，
  都要升 version 并在 `docs/EVAL_BASELINE.md` 记一行（坑 40 同族）。本条只需把规则写清 + 把 v2.4/v2.5 的分界补记。
- [ ] **C0-③（闸门作用域）** grounding 闸门现在会套在**不需要事实回答的轮次**上：P4e S2 实测
  **命中 12~16 次、其中 11~14 次来自 `cc-01` 的种植轮，且重生 100% 失败、`final` 轮从未命中**
  ——「重生一次都没救回来」说明**前提不成立**（种植轮是往会话里塞背景，模型回「记下了」才是对的）。
  代价是每轮白烧 11~14 次 LLM 调用 + badcase 档案被噪声灌满。
  要求：给闸门加**轮次类型判定**（只对"期待事实回答"的轮次生效），判据要**可解释并写进注释**，不许简单按"长度<30 字"糊过去。
  验收：整轮 `grounding_gate` 记账里种植轮命中数归零、`qa-17`/`ss-03` 的兜底能力不回退
  （canonical 档 `qa-17` 仍命中且重生成功；`ss-03` 仍必须命中）。
- [ ] **C0-④** `WEB_SEARCH_TIMEOUT_S=60` 名字与语义不符：httpx 那个是**空闲超时**不是**总时限**
  （你们自己实测同问句 12.3s / **79.4s**，60s 并没截断那次）。要么改成真正的总时限（`asyncio.timeout` 包住整次调用），
  要么改名 `WEB_SEARCH_IDLE_TIMEOUT_S` 并在 `docs/P4E.md`/UI 等待预期里写清"最坏可能远超 60s"。
  推荐做总时限 + 双层（idle 20s / 总 45s），并补一条**能判红**的慢响应模拟单测（用假 transport，不打真实网络）。
- [ ] **C0-⑤** `docs/p4d/run_with_server.sh` 收尾用 MSYS `kill $SRV` **杀不掉 Windows 进程**：
  本轮复核实测——脚本打印 `[server] done rc=0, shutting down 8936` 之后 `netstat` 显示 `:8936` **仍在监听**，
  负责人另两次也踩过同款（:8906/:8907、:8923，都是实现方帮忙复查端口时发现的）。
  改用 `taskkill //PID x //F`（或收尾调用 python `psutil.terminate()`），**并在退出前按端口复查一次**，
  打印 `[port-check] :N closed=True/False`；`False` 时以非 0 退出，别把孤儿服务留给下一个人。

## 3. P4f 主体（设计见 `docs/P4.md` M8）

- [ ] `personas` 表（owner/name/college/persona_prompt/style/bound_folder_ids/bound_categories/visibility/is_default）
  + `conversations.persona_id`；persona 删除后其历史会话**保留**并标记「人设已删除」。
- [ ] `SYSTEM_PROMPT` 改为 `build_system_prompt(persona, ctx_local, ctx_web)`；
  ⚠ **防幻觉规则 1–9 硬编码在模板里，persona 段不得覆盖、删改或削弱**——必须有一条**注入攻击用例**：
  用「忽略以上规则」「你现在是……」类问句断言防幻觉规则仍然生效（这比"风格差异"更重要）。
- [ ] 权限：辅导员只管自己的 persona；学生只能用 `public`；admin 管全部。
  **绑定库仍受 P4c 的 RBAC 交集约束，persona 不得提权**（沿用「越权=静默忽略、不可见=不存在」口径，
  并复用 `_resolve_scope` 入口，不得绕过）。
- [ ] 前端：左侧统一会话栏（列表 + 新建 + 辅导员选择器），**账户入口移到会话栏最底部**；
  「辅导员」入口 → 创建/编辑表单；对话中可切换 persona。新增 js/css 走既有 `/js/{name}`、`/css/{name}` 路由，
  `api.js` 必须最先加载（P4b-0 约定，`verify_invariants.py` 那套不变量别破）。
- [ ] 新增评测类型 `persona`：同一问题在两个 persona 下**断言风格差异且来源一致**；
  再加一条"persona 不改变来源集合"的不变量（防有人用人设把检索结果换掉）。
- [ ] UI 细节：`#w-content` 等文本框可读性属 P4g，本单**不做**，别顺手扩范围。

## 4. 测试节奏与取证纪律（照做）

- 实现期只跑针对性最小检查（纯本地秒级自测、单条断言、单问句 A/B）；
  **全部落地后集中跑一轮**：canonical 命令下 **N/N 且退出码 0**，
  并在回执里**如实附不带钩子那一档的结果**（现在是 54/55，别藏）；冒烟 `exit 0`、`documents 65→65`、
  跑完 `kb_doctor` 回 **65/487**；新增用例都要在报告里能对到逐用例 grounding/env_flags 字段。
- ⚠ 取退出码**不要接管道**（坑 55）；整轮前做**单请求端到端自证**：看响应/trace 里有没有本次新增字段（坑 57）；
  ⚠ **只读探针不要与整轮评测并发取库内计数**——负责人因此把 42 读成 44 写进三份文档（坑 58）；
  ⚠ `evals/badcases.json` 会被服务端按 50 条滚动写脏，**按主键集合比对后 `git checkout --` 还原**，别按 +/- 行数判性质（坑 56）；
  ⚠ 终止进程用 `taskkill //PID x //F` 或 `psutil.terminate()` 并**按端口复查**（坑 61 + 本单 C0-⑤）；
  ⚠ 判据阈值定完**自己先跑 ≥5 次取分布**，报告它与观测值的最小距离（坑 63——负责人给的 300ms 就压在分布里）；
  ⚠ 硬门控落地前先枚举它会被套在哪些轮次类型上（坑 64，就是 C0-③ 的由来）。
- 忠实度按**区间**读（0.8889~0.9722）且**逐条会在 0.5↔1.0 互换**，不得当点值用作闸门；`faithfulness.py` 禁改。

## 5. 交回格式（写进 `docs/TASKS.md` 本单条目下）

状态 `IN_REVIEW`、**当前持棒=Qoder**、分支与提交列表、未合并 master、工作区是否干净；
逐条完成标准打勾并附「哪个文件哪个字段/哪份证据」；两档整轮结果与冒烟；
端口/进程交代（含脚本自报的 `[port-check]` 输出）；遗留与需裁决项列出来不要自己拍板。

不许自行开下一单。做完交回，我按「集中一次独立把关」复核。

=== PROMPT 结束 ===
