# P4f 第 3 回（收尾四条，零额度）· 开单指令（粘贴给 WorkBuddy）

> 发单人：Qoder（负责人 / Review）　日期：**2026-10-01**
> 分支：**继续用 `task/P4f-persona`**，不新建分支
> 第 2 回复核：✅ **必修三条全部复验成立**（报告 `docs/p4f/review_qoder_p4f_round2.md`）——
> 探针极性已翻转且有 S6 极性自检、流式炸点补齐后我**自己走完红绿闭环**（136→拆→134 退 1→复原→136）、
> 记账与证据已同步。你这轮交回的 428 条我在护身符环境下逐条复跑全过，我的 41 条安全断言也无回归。
> **本单**是复核中新抓出的四条收尾项，**全部零额度**。

---

## 0. 背景一句话

负责人已裁决：**v2.5 基线用「专用测试 key + 非 reasoning 的 qwen 同家族模型」产**
（实测选定 `qwen/qwen-plus`；`qwen3.5/3.6/3.7/3.8-flash` 全是 reasoning 形态，小 `max_tokens` 下 `content` 为空）。
整轮由 Qoder 跑，**你不需要 key**。下面 ①③④ 三条都直接服务于「换通道跑评测」这件事。

---

## 1. ① J4 放宽 + 强制披露（负责人已拍板）

你新加的 `QUOTA_JUDGE` 旁边那条 **J4「llm 与 embedding 必须同档」**方向是对的，但它把事实堵死了：
**OpenRouter 不提供 embedding**，所以只要用测试 key，就必然是
`llm=session_env + embedding=repo_dotenv` 的混合档 —— 按现在的 J4，
Qoder 那三次最小档运行会被你自己的探针判成「该轮不认」。

**裁决与改法**：
- `llm_key_source` 必须是 `session_env`（**不放宽**，这是硬约束第 7 条的本体）；
- `embedding_key_source` 允许 `repo_dotenv`，但**必须**：
  1. 判据**单独成条**、结论为 `WARN/披露` 而不是 FAIL，且**必须在输出里显式打印一行**说明
     「embedding 走的是仓库 .env 额度，本轮共 N 次」（N 由调用方/日志提供，拿不到就写 `unknown`，**不许假装是 0**）；
  2. 这条披露要能进评测报告（见 ④），**不能只在探针 stdout 里一闪而过**；
  3. `embedding_key_source == 'unset'` 仍判红（没额度不等于没问题）。
- 自测矩阵同步：把 S4 从「配一半判红」改成「配一半 → **额度判绿 + 披露判红项出现**」，
  并新增一条 `embedding=repo_dotenv 且 llm=repo_dotenv` → **仍判红**（防止放宽 embedding 把整体放水）。
  ⚠️ 放宽后必须仍有能证明它红过的用例（坑 52/70 同源）。

## 2. ② `GET /api/personas` 对非作者隐藏 `persona_prompt` 正文（负责人已拍板）

现状：public 人设的 `persona_prompt` **全文回传给所有学生**。学生能读到辅导员的内部表述
（例如「先共情再给要点」「对考研学生优先……」），也能据此逆推系统提示词的组装方式。

**裁决**：**对非作者只下发名称/学院/风格等展示字段，`persona_prompt` 正文不下发**。
- 判据按**作者**而不是按角色：`owner_id == 请求者` 或 `role == 'admin'` → 给全文；否则 `persona_prompt` 置为
  `""`（**不要返回 `null` 或删键**，前端契约测试依赖键存在）；
- ⚠️ **不能影响使用**：`_resolve_persona` / `build_system_prompt` 走的是**服务端自己取的那份**
  （`db.get_persona` 的内部读数），不能改成读列表接口回传的值——否则学生选人设后 prompt 就丢了，
  这是「投影只作用于响应、不作用于服务端解析」的区分（坑 46：逻辑对不等于接线对）；
- 必须有的断言（**含反向**）：
  1. 学生列 public 人设 → 有 `name/style`，`persona_prompt == ""`；
  2. 作者本人列同一个 → 全文在；
  3. ★ 反向：学生**选用**该 public 人设提问 → 服务端**仍然带上了 persona 段**
     （用第 1 回那套「炸点 + 读 messages」的办法验，**零额度**）；
  4. `persona_inject` 用例不受影响（攻击面在 prompt 内容，不在可见性）。

## 3. ③ `smoke_test.py` 硬编码 `qwen-flash` → 冒烟与「换通道」互斥

`novaagent/tests/smoke_test.py:318` 写死 `PUT /api/me/settings {"model":"qwen-flash"}`，
第 327 行的 `/api/weekly/expand` 又**真的用这个模型名去生成** →
用非 DashScope 通道（OpenRouter）时上游回 **400**，冒烟 **exit 1**（我实测两次：
先是 `:8971` 崩在 `/api/kb/upload`，清掉 `user_settings` 后 `:8972` 崩在 `/api/weekly/expand`）。

**改法**：那一步的模型名**从配置取**（`config.LLM_MODEL`），或允许 `NOVA_SMOKE_MODEL` 环境变量覆盖；
保留「传一个不存在的模型名应被拒」的反向断言（第 320 行那条 `bad-model` 别删）。
另：这一步会把 `user_settings.model` **写回** `qwen-flash`（我实测到），
所以要么测完还原，要么明确它不影响后续步骤 —— 见坑 66，这类"环境状态被测试自己改掉"最容易骗过下一次运行。

## 4. ④ 报告要记「逐用例实际生效的 model 与来源」（坑 66 的收口）

第 1 回集中验证我 5 条红差点误报成「persona 路径崩」，真因是 `user_settings.model='qwen-flash'`
经 `effective_llm()` **优先于**会话环境变量，而报告里 `env_flags.server.llm_model` 写的是**全局**模型 ——
**报告自证的模型 ≠ 实际请求用的模型**。

**改法（零额度）**：
- 评测报告里为每个用例记一条 `effective_model`（+ 它的来源：`user_settings` 还是全局配置），
  服务端已有现成读数：`GET /api/me/settings` 返回 `effective_model`，`/api/chat` 的 `context` 里也可带；
- 加一条断言：**报告记录的 effective_model 必须与 `env_flags.server.llm_model` 一致，
  不一致时必须在报告里显式标红**（而不是静默用全局值）；
- 自测里补一条**能判红**的：构造「全局 A / 用户 B」两态，断言报告标红且点名差异。

---

## 5. 追加三条（负责人已用整轮数据定案，2026-10-01 晚）

### ⑤ `pf-03` 方向性假设**确认不成立** —— 按下面这句改，不要自己发挥

我用**两个不同模型、三次独立测量**复算了同一件事：

| 通道 | formal 字数 | warm 字数 | 比值 | 判定 |
|---|---|---|---|---|
| `stealth/space-bunny-alpha` | 1599 | 2095 | 0.76 | 红 |
| `qwen/qwen-plus`（canonical 档） | 851 | 1280 | 0.67 | 红 |
| `qwen/qwen-plus`（默认档） | 821 | 1441 | 0.57 | 红 |

**方向三次全反**，且主判据（来源集合一致）三次都过 → 不是模型抖动，是**用例前提错了**：
「亲和」人设要求「先共情学生处境再给要点」，本身就比「书面语逐条列依据」更长。

**改法（照此执行）**：`pf-03` 的 `expect_style` 从 `{"longer":"formal","min_ratio":1.15}` 改成
**方向无关**的写法 —— 只要求「两侧篇幅比 ≥1.15（任一侧更长皆可）」，
并在 `judge_persona_pair` 里支持 `expect_style={"min_ratio":1.15}`（无 `longer` 键时不校验方向）。
⚠️ **必须同时补两条自测**：(a) 构造「两侧几乎等长」→ 仍判红；(b) 构造「concise 侧反而长 3 倍」→ **判绿**
（证明方向真的不再参与判定，而不是换了个地方继续卡方向）。
`pf-01`/`pf-02` 的 `longer` **保持不变**（那两对是「详尽 vs 简洁」，方向天然成立，实测比值 8.45 / 3.38 / 16.1 都稳）。

### ⑥ `rind-07` 的 absent 判据分不清「编造」与「如实说没有」

整轮里 `rind-07` **一次红一次绿**（canonical 红、默认绿）—— 这种抖动本身就是要修的。
我把红的那次答案从库里捞出来读了（**报告里没有 answer，只能查 DB**，见 ⑦）：
模型答的是「知识库中暂无关于…的具体内容」「未细化离校手续清单」「建议您：宿舍钥匙咨询楼管员…」——
**这是本单最想要的正确行为**（逐条说明库里没有 + 给出咨询方向 + 不编造校规），
却因为复述了用户问句里的 `饭卡/调档/档案转递/图书馆` 而被判「夹带无据断言」。

**问题定性**：`expect_absent_keywords` 现在只看「词出没出现」，不看「是**断言**还是**声明无据**」。
宽词在**诚实拒答**里出现是必然的 —— 这是坑 54 的第三种形态（第一版查「库里出现几次」，
第二版加邻近共现，这一版栽在「答案侧出现 ≠ 编造」）。

**改法方向**（你可以细化，但必须满足下面四条验收）：
1. 只有当 absent 词出现在**断言句式**里才判红 —— 判据要能区分
   「须到档案馆办理调档」与「库内暂无调档规定，建议咨询档案馆」；
2. **必须有一条能判红的反向用例**：构造一句**真的编造流程**的答案（含 `调档` + 办理动作）→ 判红；
   再构造一句**如实说没有**的答案（含 `调档` + 无据标记）→ 判绿。两条都要在自测里，退出码要能红（坑 52）；
3. 无据标记清单要**从代码里读**（`refusal.py` 的模板/`REFUSAL_MARKS` 同源），
   **不许在判据里再抄一份词表**（坑 45：同一件事只应有一个权威实现）；
4. **不许改用 `cases.json` 的问句来绕过**（问句是用户真实场景，动它等于把缺陷藏起来）。

### ⑦ 报告不落 `answer`/`sources` → 判据问题无法离线复算

`reports/eval_report_*.json` 里 qa/refusal 类用例**没有 `answer` 也没有 `sources` 字段**，
所以我为了搞清 `rind-07` 为什么红，只能去 `agent.db` 里按 `conversation_id` 捞消息。
这违背我们刚立的纪律：**交回与报告必须可离线复算**（硬约束第 7 条的配套要求）。

**改法**：报告每条用例落 `answer_head`（前 300 字，**够判读即可**）与 `sources` 的
`[{ref,title,role_min}]`（**不落 chunk 正文**，避免把库内内容复制进要提交的 JSON —— 与坑 56 同族）。
⚠️ 注意：`answer` 里可能含用户问句原文，本仓库是本地演示项目、语料为公开校规，可以落；
但**真实学工数据永不入库**这条红线不变，所以只允许落**评测用例**的答案，不要落线上会话。

### ⑧ 评测要能被上游限流打断而不冒充「模型答错」（负责人重跑整轮时踩到的）

我第二次跑整轮时 **18 红**，其中 **13 条是 `HTTP 500`**，服务端日志实测 **429 Too Many Requests 命中 54 次**：
OpenRouter 对这把免费 key 有**每分钟请求数上限**，而 `run_evals.py` 是背靠背串行打，
一旦触发限流，`llm.chat` 的 `raise_for_status()` 冒到 `/api/chat` 变成 **500**，
评测把它记成**该用例失败**并把 R@k 从 1.0 砸到 0.6667 —— **报告里分不清「模型答错」与「没额度/被限流」**。
这轮数据因此整体作废（我已把两份报告改名 `INVALID__*` 存档）。

**改法（两件事，零额度可验）**：
1. `run_evals.py` 支持用例间节流：`NOVA_EVAL_THROTTLE_MS`（**默认 0 = 现有行为完全不变**），
   限流的免费通道下用 3000~5000 跑；
2. **把「环境失败」与「用例失败」分开记账**：HTTP 5xx / 上游 429 / 连不上 → 该用例记
   `env_error`（单独计数、**不计入通过率与 R@k 分母**），并在 `summary` 里显式列出
   `env_error_cases: [...]`；**报告退出码仍非 0**（环境不干净不许当绿灯），但归因必须可读。
   ⚠️ 反向自测：喂一条假的 429 响应 → 该用例必须记 `env_error` 而**不是** `pass=false` 的普通红；
   喂一条真实的模型答错 → 必须是普通红。**两种红不许混成一个桶**（坑 46/52 同族）。
3. 顺带（**产品侧一行，可选**）：`/api/chat` 遇到上游 429 时应回 **503 + 明确文案**
   （「模型额度受限，请稍后再试」），而不是 500 白屏。若你动 `main.py`，请只加异常映射，别碰拒答门控。

---

## 6. 白名单（只允许改这些）

```
novaagent/tests/probe_port_check.py          # ① J4 放宽 + 披露 + 自测
novaagent/tests/smoke_test.py                # ③ 模型名从配置取 + 还原环境
novaagent/novaagent/main.py                  # ② personas 响应投影（只改响应构造，别动解析路径）
novaagent/novaagent/db.py                    # ② 若需要"内部读数/对外投影"两份
evals/run_evals.py                           # ④ 报告记 effective_model；① 的披露行落进报告；
                                             # ⑥ `_check_absent_keywords` 断言/无据区分；⑦ 报告落 answer_head+sources 摘要
evals/cases.json                             # ⚠ **只允许**改 `pf-03` 的 `expect_style` 一处（⑤），其余一条都不许动
novaagent/tests/test_p4f_*.py                # 新增/更新断言
novaagent/tests/test_p4d_ruler_selftest.py   # ⑥ 若你把判据自测放这里（或新建同名系列，别改 docs/p4d 那份既有证据）
docs/P4F.md docs/TASKS.md docs/p4f/evidence/*
```

## 7. 禁改（碰了就整单打回）

`sims/**`、`mcp/**`、`weknora/**`、`evals/faithfulness.py`、`novaagent/novaagent/refusal.py`、
`evals/cases.json` 的**除 `pf-03.expect_style` 以外的一切**（问句、关键词、absent 词、其它用例都不许动 ——
⑤ 的改法只允许碰那一个字段；⑥ 明确禁止用改问句/改词表来绕过）、
`novaagent/web/css/theme.css`、`agent.py` 的 grounding 闸门与检索编排逻辑、`.env`
（**绝对不许把任何 key 写进去**）。

## 8. 交回要求

1. **零额度**：不发任何真 LLM / embedding / 联网请求。自查用**假 key 护身符**
   （`export LLM_API_KEY=ZERO-QUOTA-PROTECTOR-... EMBEDDING_API_KEY=同值`，见坑 68）。
2. 每条改完跑对应自测，**命令 + 退出码**写进回执；取退出码**不要接管道**（坑 55）。
3. **每条放宽都要配一条"它仍然会红"的反向用例**（①②④ 三条都是放宽/投影类，最容易改出静默放行）。
4. 不要跑整轮评测（那是我的活，且要用测试 key）。
5. 起过的端口**按端口属主杀净并复查**（坑 61）；`:8900` 是你自己的服务，动了说一声。
6. 回执写进 `docs/TASKS.md` P4f 段，顶部持棒与 `HANDOFF.md` 台账同步为 **IN_REVIEW / 持棒 = Qoder**。

---

## 9. 我这边并行做什么

- 正在用**专用测试 key（`qwen/qwen-plus`）**跑 v2.5 整轮两档（canonical + 默认）+ `kb_doctor`，
  产出后回填 `EVAL_BASELINE` 的 v2.5 三列，并**如实标注通道差异**
  （OpenRouter 的 `qwen/qwen-plus` ≠ 生产的 DashScope `qwen-flash`，数字只能近似对照，属**口径变更**，按 C0-② 记账）。
- 你交回后我零额度复验这四条 → 复跑冒烟（③ 修好后应能在新通道下 exit 0）→ 决定合并。
- `pf-03` 方向性与「种植轮闸门是否归零」两条，我拿这轮整轮数据复算后给你明确改法（**你别自己改用例**）。

---

## 10. （只记录，本单不修）F3 `/api/kb/upload` 不是原子的

**F3 `/api/kb/upload` 不是原子的**：先 `insert_document` + `insert_chunks`，**之后**才调 LLM 生成摘要
（`main.py` 上传路径 → `agent.summarize_document`）。摘要调用一失败（我这次是上游 400），
接口返回 500，但**文档与分块已经落库了** —— 实测留下 4 篇孤儿文档（其中 1 篇 `student` 可见），
把我第一次整轮的语料从 `65/487` 污染成 `69/491`，那两份报告我已改名
`INVALID__corpus_69docs_*.json` 存档并重跑。这也解释了为什么冒烟中途失败会留脏数据。

你**本单不要碰** `main.py` 的上传路径（白名单外），我另开单。

---
