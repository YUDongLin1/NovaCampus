# P4f 第 2 回复核（Qoder，零额度）—— ✅ **必修三条全部复验成立**

> **结论先行**：三条必修我**逐条独立复验成立**，且他们交回的**反向验证是真的做了闭环**
> （不是"改完就绿"，而是"把防护拆掉必须红、复原后必须绿"）。七个自测我复跑 **428 条 exit 全 0**，
> 我自己的 41 条安全断言重跑**仍全绿**（无回归）。工程侧**无阻塞项**。
> 复核实测中另抓出 **2 条新问题**（④文档命令、⑤表述精度），我已代做（纯文档、零额度、留痕见下）。
> **唯一还挡着合并的是额度决策**：v2.5 基线要产，就得换一把**非 reasoning 的生产同档模型**——这是你的决定。
>
> 复核人：Qoder　分支 `task/P4f-persona` @ `9089fe1`　日期 **2026-10-01**
> 全程假 key 护身符（`LLM_API_KEY=ZERO-QUOTA-PROTECTOR-*`），**一次真调用都没发**（见证据④）

---

## 1. 必修① —— 额度探针极性：✅ 已翻转，且做成了「改错会被当场抓住」

第一版只是把 `if src == "session_env": 判红` 反过来写。他们做的是**把极性收进一张表**
`QUOTA_JUDGE`（`tests/probe_port_check.py:69-76`），判据抽成**纯函数** `judge_flags/judge_payload`，
再配 14 条离线自测。我逐条复跑并读了实现：

| 我实测的 | 结果 |
|---|---|
| `probe_port_check.py --selftest` | **14/14，exit 0**（`r2_qoder_port_selftest.txt`） |
| **真机合规档**：注入会话 key 起 `:8961` | `llm/embedding key_source='session_env'` → **7/7，exit 0**（`r2_port_A_session_env.txt`） |
| **真机违规档**：不注入，读 `.env`，起 `:8962` | 两条 `额度档位[repo_dotenv] → 该轮不认` **FAIL** → 5/7，**exit 1**（`r2_port_B_repo_dotenv.txt`） |
| 不传 `--base` | `[FATAL] 必须显式 --base` → **exit 3**（`r2_port_C_no_base.txt`） |

**S6 极性自检我重点看了，不是同义反复**（`probe_port_check.py:233-246`）：它注入一张**反表**再判一遍，
断言 `repo_dotenv` 不再判红、`session_env` 改判红 —— 证明判据真的**从表里读极性**而不是硬编码；
而真表若被改回第一版，S1/S2 会直接红。**双向都堵住了。**

**顺带多送我两条我没要求的判据**（好）：J2 取值域封闭（将来加档位不会静默漏判）、
J4 **llm 与 embedding 必须同档**（专防"embedding 悄悄用用户额度"）。J4 带来一个政策问题，见 §5。

## 2. 必修② —— 流式 LLM 炸点：✅ 补齐，且**红绿闭环我自己走了一遍**

`install_llm_probe` 现在同时替换 `chat_for` 与 `chat_stream_for`，后者是**异步生成器版炸点**
（`async for` 取第一个元素时才 raise，注释解释了"用 raise 不用 yield"的理由——
yield 假 token 会让后续断言在假数据上通过，等于没拦）。返回 `restore()` 供 `finally` 复位。

我不采信回执，自己跑了完整闭环（全程护身符环境）：

| 步骤 | 我的实测 | 回执声称 |
|---|---|---|
| 基线 | **136/136，exit 0** | 136/136 |
| `patch_check_c5_tripwire.py apply`（拆炸点） | **134/136，exit 1**，红项正是 `C5 A` 与 `C5 B` | 134/136 |
| `revert` 后 `git diff` | **空**（逐字节复原，没留下 `pass`） | — |
| 复原后重跑 | **136/136，exit 0** | 136/136 |

**最有价值的一条读数**：拆掉炸点后 `C5 B` 的 detail 是
`Client error '401 Unauthorized' for url 'https://api.siliconflow.cn/v1/embeddings'`
—— 说明**真请求确实发出去了**，只是被我的假 key 挡在门外。
也就是说：没有护身符的话，那次自测就是**一次真实扣费**。这条把「为什么必修②不是洁癖」量化了。
（他们自己在坑 71 里也写了同一条，并记下"第一版 revert 只删标记行、留下 `pass`"的教训。）

## 3. 必修③ —— 记账与证据同步：✅ 全部对上

- `EVAL_BASELINE.md` v2.5 行与 §二十 标题：`2026-09-03` → **`2026-10-01`**（两处都改，我逐处核过）。
- `test_p4f_c0.py` 我复跑 **64/64**，`c0_selftest_output.txt` 已刷到 64 条 `[PASS]` + `[RESULT] 64/64`。
- `docs/P4F.md` §3.1 改成「七个自测 **428 条**」并**主动写明**上一版 401 条是"证据没跟着代码重跑"。
- n1/n2/n3/n4/n5 五条 nit 全收（payload 注释四键、`visibility` 档位注释、`_REGEN_HINT` 的英文碎片、
  下拉文案空格、`run_evals.py` 的 `BASE` 默认值）。n6（CRLF）他们核实"入库是 LF、不需改"——
  我同意，`.gitattributes` 确实生效（我第 1 回也是这么测的）。

## 4. 边界与无回归

- 本轮 diff 17 文件：`refusal.py`/`faithfulness.py`/`cases.json`/`theme.css`/`sims/**`/`.env` **零改动**（`git diff --name-only` 过滤无命中）。
- **七个自测 428 条 exit 全 0**（我逐条跑，`64+136+33+62+99+20+14 = 428`，与他们声称一致）。
- 我自己的 **41 条**安全断言重跑**全绿**（`r2_qoder_zeroquota_stdout.txt`）→ 迁移幂等、persona 不提权、
  prompt 规则不被覆盖、判据能判红能判绿这些性质**没被这轮改动碰坏**。
- 端口：我起过 `:8961`/`:8962`，包装脚本按端口属主杀净并复查 `closed=True`；`:8900` 是 WorkBuddy 的，未动。
- **一处白名单缺口，责任在我**：`evals/run_evals.py` 不在我开的白名单里，但 n5 又点名要改它——
  单据自相矛盾。他们改了（`BASE=""` + `--base` 必填 + 双保险），方向正确，我按 P4e 的先例
  **不计入实现方越界**，责任记在我头上。

## 5. 复核中抓出的两条新问题（我已代做，纯文档）

- **④ `--base` 改必填后，文档里的复跑命令全失效**。实测 `python evals/run_evals.py`（不带 `--base`）
  → **退出码 2**；`docs/COLLAB.md` §5 合并闸门第 2 步、`docs/EVAL_BASELINE.md` 的 canonical 复跑口径、
  `docs/BADCASES.md` 两处，照抄都会第一步撞墙；`EVAL_BASELINE` 那行还写着起服务用 `--port 8900`
  （正是坑 57 要避免的他人常驻实例）。**已修**：三处命令统一改成
  `bash docs/p4d/run_with_server.sh <端口> ../evals/run_evals.py --base http://127.0.0.1:<端口>`
  并写明"不要再起 :8900"。脚本 `docs/p4f/patch_docs_base_required.py`（可复算）。
  ⚠️ **故意没动** `docs/TASKS.md` 里 P1/P2 时代的 6 处旧命令——那是**已完成任务的历史验收口径**，
  改历史等于伪造现场。
- **⑤ `P4F.md` §3.4 有一行会被读成"种植轮已验证"**：原文「C0-③ 种植轮（`ss-03` 的闸门记账）｜✅ 逐用例记账已拿到」。
  实际拿到的是**记账机制**的读数（`ss-03` `hits=1 regen_failed=0 stage=final`），
  而"种植轮命中是否归零"要看 `cc-01` 的 43 轮 —— `cc-01` 这轮没跑成，所以该条**仍未验证**。
  **已改成明确区分两者**的表述。

## 6. 还剩什么（不是缺陷，是决策）

| 项 | 状态 | 卡在哪 |
|---|---|---|
| 三条必修 | ✅ 复验成立 | — |
| 七个自测 / 我的 41 条 | ✅ 428 + 41 全绿 | — |
| `pf-01/02` 主判据、`pf-inject-01` 注入防御 | ✅ 真实模型已证（第 1 回 §6） | — |
| **v2.5 整轮基线（通过率 / R@k / 忠实度）** | ❌ 未产 | **需要非 reasoning 的生产同档模型** —— 待你定额度 |
| `pf-03` 方向性假设 | ⏸ 待复算 | 同上（不得拿测试模型分布改 `cases.json`） |
| C0-③ 种植轮归零 | ⏸ 待复算 | 同上（`cc-01` 在测试模型下必崩） |
| `persona_prompt` 是否回传学生 | ⏸ 待你拍板 | 产品决定 |
| F1 judge 静默降级 / F2 缺 `choices` 守卫 | ⏸ 转 P4g C0 候选 | 不属 P4f |

**⚠️ 一个由必修①引出的政策问题（需要你裁决）**：新加的 J4 要求
`llm_key_source` 与 `embedding_key_source` **同档**，否则整轮不认。而 OpenRouter **不提供 embedding**，
所以只要用这把测试 key，就必然是 `llm=session_env + embedding=repo_dotenv` 的**混合档**
——按 J4，我第 1 回那三次最小档运行**会被自己的探针判成"该轮不认"**。三条出路：
① 放宽 J4（允许 embedding 走 `.env`，但必须在报告里显式披露次数与来源）；
② 你再给一把**SiliconFlow 免费 embedding key** 作测试用（最干净，两档就真同档了）；
③ 保持 J4 不变，那么任何整轮都必须走 `.env`（回到授权问题）。
