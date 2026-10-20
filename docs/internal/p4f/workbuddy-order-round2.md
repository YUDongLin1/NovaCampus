# P4f 第 1 回 Review → 打回必修三条（零额度）· 开单指令（粘贴给 WorkBuddy）

> 发单人：Qoder（负责人 / Review）　日期：**2026-10-01**
> 分支：**继续用 `task/P4f-persona`**（不新建分支、不合并 master）
> 完整复核报告：`docs/p4f/review_qoder_p4f_round1.md`（含 §6 集中验证最小档实测）
> **本单一分钱额度都不要花**（硬约束第 7 条）。集中验证由 Qoder 用**专用测试 key** 在你交回之后跑，你不需要 key。

---

## 0. 先说清楚：不是实现质量不行，是「验证」这件事还没发生

你交回的 401 条断言（63+124+99+20+33+62）我在**假 key 护身符**环境里逐条复跑，实得 **402 条全过**、且没有任何一条报鉴权错 ——
这同时证明了你的零额度纪律是真的。我自己另写了 **41 条断言**（`docs/p4f/review_qoder_p4f_zeroquota.py`），
迁移幂等 / persona 不提权 / prompt 防覆盖 / 新判据能判红也能判绿 / absent 词全库零命中 /
cases.json 逐 id 语义 diff / 左侧栏真机走查 —— **全绿**。

卡合并的三件事里，**「集中验证没发生过」这一条我已经用专用测试 key 补做掉了**（结果见 §7，
`pf-01/02` 与 `pf-inject-01` 在真实模型上全过 —— 也就是说你的主判据与注入防御是站得住的）。
剩下的就是下面三条必修，**都在测试与记账侧，一分钱额度都不用花**。

---

## 1. 必修三条（都在测试与记账侧，**不碰产品代码**）

### ① 🔴 `novaagent/tests/probe_port_check.py` 的额度断言**极性反了**

第 66-67 行：

```python
if src == "session_env":
    failed.append("本次进程带着会话环境变量 key(C0-⑥:该轮结果不认),证据链须重走")
```

它把**合规**跑法（注入会话 key、不碰 `.env`）判为失败，把**花用户额度**的跑法判为通过 ——
与硬约束第 7 条正好相反。同批的 `probe_health_keysource.py:106-124` 写的是**正确极性**，
两个自相矛盾。实测证据：`docs/p4f/evidence/review/run_c0_05_with_session_keys.txt`
（注入会话 key 跑 `:8947`，health 五项字段全在、`[port-check] closed=True`，却 `[RESULT] 4/5` + 退出码 1）。

**改法（两件事）**：
- 把该断言翻成 **`repo_dotenv` 才记一笔「该轮不认」**；`session_env` 视为合规。
  或者更干净：这个探针**只管端口与 flags 可读**，额度档位交给 `env_flags` 记账，别在一个探针里兼两个裁判。
- 第 26 行 `BASE = "http://127.0.0.1:8900"` 是**我自己的服务**（现在归 WorkBuddy 占着），
  不带 `--base` 就会去审别人的进程（坑 57 同源）。改成**不传 `--base` 就报错退出**，别留默认值。

**必须新增一条能判红的断言**（否则改完还是没人知道它到底会不会红）：
构造 `flags={"llm_key_source": "repo_dotenv"}` 与 `"session_env"` 两种假 health 响应，
断言前者被标注/判红、后者**不判红**。判据函数请抽成**纯函数**（吃 dict 出结论），
这样复核方可以离线重放，不必真起服务。

### ②  LLM 炸点只盖住了一半 —— 流式用例可能**静默烧钱**

`novaagent/tests/test_p4f_persona.py:90-96` 的 `install_llm_probe` 只替换 `chat_for`；
而第 501 行有一条 `POST /api/chat/stream`，它走的是 **`chat_stream_for`**。
现在没花钱，是因为 `persona_scope_empty` 短路恰好在 LLM 之前返回 ——
**一旦短路回归，这条自测会去刷用户的 key，而不是当场测试红。**

**改法**：`install_llm_probe` 里再加一个 `chat_stream_for` 版炸点（**异步生成器**，
被 `async for` 取第一个元素时就 raise `LlmCalled`），并在 `finally` 里复位。
再加一条断言：**故意把 `_resolve_persona` 的短路标记去掉**（或 monkeypatch 掉
`_persona_scope_empty_response`），跑那条流式用例，断言**测试当场红** ——
证明这个炸点真的有拦截力，而不是「今天恰好没走到」。

### ③ 🟡 记账与证据不同步（C0-② 这条规则要作用在自己身上）

- `docs/EVAL_BASELINE.md`：v2.5 那一行的日期、§二十 标题里的日期都写成了 **2026-09-03**，
  今天是 **2026-10-01**（`docs/TASKS.md` 的 P4f 标题与回执标题同样是 09-03，一并改）。
  基线台账是审计入口，日期错就查不回对应提交。
- `docs/P4F.md:257` 写 `test_p4f_c0.py = 63/63`，当前代码实测 **64/64**；
  证据文件 `docs/p4f/evidence/c0_selftest_output.txt` 也停在 63 条，
  缺 `[PASS] C0-⑥ 反向:返回值 != 真实 key 值`。**重跑一次并把证据刷新**（零额度），
  让「证据 ↔ 代码」重新对上（坑 56/59 家族）。
- 回执 §五 里那句「集中验证需测试者自带额度」请改成实况：**由 Qoder 用专用测试 key 跑最小档**，
  并写明最小档范围（`pf-01/02/03/pf-inject-01` + `qa-17`/`ss-03`/`cc-01` 闸门记账）。

---

## 2. 顺手可收（不阻塞，挑得动的做，做不动就在回执里写「未做+原因」）

| # | 位置 | 问题 |
|---|---|---|
| n1 | `novaagent/novaagent/websearch.py:109` | 注释说 payload「只有 model/input/tools 三个键」，实际四个（`tool_choice` 后加的）。合规自查引用的是这句，措辞要对上事实 |
| n2 | `novaagent/novaagent/main.py:996` 上方注释 | 写「学生只能列/用 `visibility='student'` 的」，但 `personas.visibility` 的 CHECK 只有 `private`/`public`（我造 `'counselor'` 时被 CHECK 当场拦下）。注释与实现两套口径，改注释 |
| n3 | `agent.py` `_REGEN_HINT` | 混进一段英文碎片 `", but "`，会进重生提示词 |
| n4 | 前端 persona 下拉 | 默认项文案「默认助手（无 人设）」中间多个空格 |
| n5 | `evals/run_evals.py:59` | `BASE` 默认仍 `:8900`，与 ① 同源；若改动面大就在回执里说明，别硬改 |
| n6 | 工作副本 CRLF | `evals/cases.json`、`docs/p4d/run_with_server.sh` 等 10 个文件工作副本是 CRLF（**仓库 blob 是 LF，`.gitattributes` 是生效的**）。提交前 `git checkout -- <file>` 规范化一次，避免下次整文件重排的假 diff |

**不要动的一条**：`GET /api/personas` 会把 `persona_prompt` 原文回传给学生（public 人设的提示词全文可见）。
这是产品决定，我已单独提请负责人拍板，**本单不要顺手改**。

---

## 3. 白名单（只允许改这些）

```
novaagent/tests/probe_port_check.py
novaagent/tests/test_p4f_persona.py
novaagent/tests/test_p4f_c0.py            # 仅当你要把额度档位断言搬成纯函数时
docs/EVAL_BASELINE.md                     # 只改日期与 v2.5 行的措辞，不动数值列
docs/P4F.md                               # 更正数字与 §五
docs/p4f/evidence/*                       # 重跑后的自测输出
novaagent/novaagent/websearch.py          # 仅 n1 注释
novaagent/novaagent/main.py               # 仅 n2 注释
novaagent/novaagent/agent.py              # 仅 n3 字符串字面量，禁止碰闸门/检索逻辑
novaagent/web/js/persona.js               # 仅 n4 文案
```

## 4. 禁改（碰了就整单打回）

`sims/**`、`mcp/**`、`weknora/**`、`evals/faithfulness.py`、`novaagent/novaagent/refusal.py`、
`evals/cases.json`（**用例一条都不许动**，篇幅比阈值等校准要等真实测数据出来再谈）、
`novaagent/web/css/theme.css`、`agent.py` 里的 grounding 闸门与检索编排逻辑、`.env`（**绝对不许往里写测试 key**）。

---

## 5. 交回要求

1. **零额度**：全程不得发真实 LLM / embedding / 联网请求。
   自查办法（我这次也是这么做的）：`export LLM_API_KEY="ZERO-QUOTA-PROTECTOR-not-a-real-key"`
   与 `EMBEDDING_API_KEY=同值` 再跑 —— 假 key 会盖住 `.env`，任何意外真调用拿到 401 而不是扣费。
2. **每条改完跑对应自测**，把**命令 + 退出码**写进回执（取退出码**不要接管道**，坑 55）。
3. **新增断言必须自带反向用例**（能判红才算数，坑 39/45）——尤其 ① 的额度档位与 ② 的流式炸点。
4. **不要跑整轮评测**（那要花额度，是我的活）。
5. 回执写进 `docs/TASKS.md` 的 P4f 段（新增「第 2 回复核后修复回执」），
   `docs/TASKS.md` 顶部持棒字段与 `HANDOFF.md` 台账同步改为 **IN_REVIEW / 持棒 = Qoder**，
   并明确写出「本轮零额度、未跑整轮」。
6. 起过的服务端口**按端口属主 PID 杀干净**并复查（`run_with_server.sh` 现在会打 `[port-check] :<port> closed=True`，坑 61）；
   `:8900` 是你自己的服务，别被我算成孤儿，动了也说一声。

---

## 6. 本单**不要动**的两件事（防止你顺手改掉，反而把证据链弄断）

1. **`pf-03` 的方向性假设** —— 我用专用测试 key 实测：两侧来源集合一致（主判据**过**），
   但 `warm` 2095 字 > `formal` 1599 字，比值 0.76 < 1.15 判红。
   「formal 一定更长」这个前提本身站不住（「先共情再给要点」天然会多写一段）。
   **但不要用这把测试 key 的输出分布去改 `cases.json`** —— 它是 reasoning 模型，
   小 `max_tokens` 路径还会返回空 `content`（详见报告 §6）。
   这条由我拿**生产同档模型**复算后再定改法（要么去掉 `longer` 方向、只留「比值 ≥1.15 方向不限」，要么换 `longer` 侧）。
2. **`GET /api/personas` 把 `persona_prompt` 原文回传给学生** —— 是产品决定，已单独提请负责人拍板。

---

## 7. 我这边并行做什么（你不用等，也不用管）

- **已做完**：集中验证**最小档**（专用测试 key，`llm_key_source=session_env`，三次运行）——
  `pf-01/02` ✅ 来源集合一致、`pf-inject-01` ✅ **注入未生效**、`qa-17`/`ss-03` ✅、
  `pf-03` ❌ 方向性假设（见 §6-1）、`cc-01` ❌ 该测试模型形态导致（非你的改动引入）。
  全文与逐条读数在 `docs/p4f/review_qoder_p4f_round1.md` §6。
- **待你交回后**：零额度复验必修三条 → 若通过，再决定 v2.5 基线用哪个模型产
  （这把测试 key 产不了可对照的基线，因为它 ① 是 reasoning 模型、② 与生产 `qwen-flash` 不同档）。

