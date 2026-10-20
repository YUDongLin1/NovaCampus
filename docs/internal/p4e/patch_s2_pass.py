# -*- coding: utf-8 -*-
"""P4e 主体+S1+S2 第 2 回通过：TASKS 头部与结论、HANDOFF 台账/下一步/坑 64。串内一律用「」。"""
import io

log = []

# ---------------- TASKS.md ----------------
P = "docs/TASKS.md"
T = io.open(P, encoding="utf-8").read().splitlines(True)
nb0 = len([l for l in T if l.strip()])

i = [k for k, l in enumerate(T) if l.startswith("> **当前持棒：")]
assert len(i) == 1
nl = "\n" if T[i[0]].endswith("\n") else ""
T[i[0]] = ("> **当前持棒：Qoder → 已下发 P4f（含 C0 前置收口）**"
           "（**P4e 主体 + S1 + S2 = ✅ 全部通过并合并 `master`**，2026-10-01 晨。分支 "
           "`task/P4e-websearch-main`，S2 提交 `d660271`+`5f965f9`+`4a059eb`。"
           "我这一档实测：**canonical（带钩子）整轮 55/55、退出码 0**、R@k 1.0、忠实度 0.9444、拒答 1.0、"
           "隔离 47 会话全量 ok；**默认档（不带钩子）54/55、退出码 1、失败项只有 `ss-03` 且文案点名环境变量**；"
           "冒烟 `--base` exit 0 / `documents 65→65`；`kb_doctor` 回到 65/487；我自己起的端口全部复查为关闭。"
           "**分离度我也独立复现**：全缓冲档 span 56/35/47ms vs 早窗档 5713/2904/2687ms（约 48 倍），"
           "阈值 150ms 落在分布之外。基线 **v2.4 / 55 用例**"
           "（⚠ 本节 S2 只改了 `ss-*` 问句与阈值、未升 version，v2.4 存在两种刺激，见复核结论 ④）。"
           "**下一步 = 等 WorkBuddy 交回 P4f + C0**，开单指令 `docs/p4f/workbuddy-order.md`）")
T[i[0]] = T[i[0]] + nl
log.append("TASKS 持棒头部：P4e 全绿已合并 + P4f 已下发")

p4e = [k for k, l in enumerate(T) if l.startswith("### P4e 联网搜索开关")]
assert len(p4e) == 1
k = p4e[0]
T[k] = T[k].replace("🟡 **进行中 —— 主体 + S1 第 1 回 ❌ 打回（尺子与可复现性）**",
                    "✅ **DONE —— 主体 + S1 第 1 回 ❌ 打回 → S2 第 2 回 ✅ 通过并合并 `master`**", 1)
assert "✅ **DONE" in T[k], T[k][:90]
log.append("P4e 条目改 DONE")

CONC = (
    "\n#### Review 结论（Qoder，2026-10-01 S2 第 2 回）——✅ **通过并合并 `master`**\n"
    "\n"
    "**四条必修逐条独立复验（全部我自己跑，不复用他们的 probe 与 judge）**\n"
    "\n"
    "| 项 | 我的验证动作 | 结论 |\n"
    "|---|---|---|\n"
    "| S2-① 阈值落在分布之外 | 我自己起两档实例（:8930 默认 / :8931 `EARLY_WINDOW_CHARS=0`），"
    "问句直接从 `cases.json` 读、自己算 `span=E2E-TTFB`：全缓冲 **56/35/47ms**，早窗 **5713/2904/2687ms** "
    "（约 48 倍间隔）→ 150ms 两侧都有量级余量 ✅（誊录证据 `evidence/review/qoder_s2_span_separation.json`） |\n"
    "| S2-② 官方绿可审计 | `run_evals.py` 取 **服务端** `/api/health` 的 flags 作权威（比我提的客户端 env 更对，"
    "坑 57 同源），报告新增 `env_flags` + `grounding_gate`；我实测两档报告里 `force_ungrounded` "
    "分别如实记 false/true；`ss-03` 的 FAIL 文案点名该设的变量并指向 canonical 命令 ✅ |\n"
    "| S2-③ 归因 11 条 ungrounded | 我这一档独立量化：默认档 **命中 12 次 / 重生失败 11 次**，"
    "canonical 档 **命中 16 / 失败 14**，**全部落在 `cc-01` 的种植轮**（`turn5/8/9/13/15/17/20/32…`），"
    "末轮 `final` 一次都没命中；`qa-17`/`ss-*` 命中后重生均成功 ✅ 归因成立且不再靠 badcases 反推 |\n"
    "| S2-④ 两处记账 | 忠实度区间已扩为 0.8889~0.9722（我这轮整轮实测 0.9444，与实现方同值）；"
    "`QA12_E2E_DISCREPANCY.md` 顶部已加「当前结论」块 ✅ |\n"
    "| 边界与红线 | `refusal.py`/`faithfulness.py` 全程 0 变更；三个检索常量未动；"
    "`cases.json` 55→55、只有 `ss-01/02/03` 的 question+note 变，旧用例零丢失；"
    "出网请求体仍只有 `model/input/tools/tool_choice` 且 `input` 恒等问题文本 ✅ |\n"
    "\n"
    "**我对实现方两处判据的独立认同（他们推翻了我）**\n"
    "\n"
    "1. **不采纳我给的另一条思路**（他们明确拒绝并给了理由）：`span >= max(120, 0.10 × E2E)` 在本语料里 "
    "E2E≈3.0~6.4s → 相对阈值 = 300~640ms，**恰好又落回被判定为「压在分布里」的量级**，且会随检索段变慢而变严。"
    "我复核后认同：绝对阈值 + 固定长刺激才是对的解法，我的相对判据是错的。\n"
    "2. **先修测量、再修阈值**：他们发现真正的问题不是阈值数字，而是**问句太短**（答案 110~230 字，"
    "两档分布几乎贴合，缝隙只有 20~30%），换成三段式长问句后 span 回到它本该度量的量。"
    "这比我把 300 改成 150 的要求做得更彻底，也更值钱。\n"
    "\n"
    "**四项裁决（他们上交，未自决）**\n"
    "\n"
    "- **测试钩子 `NOVA_GROUNDING_STREAM_FORCE_UNGROUNDED` 进生产代码**：✅ **接受**。"
    "它是服务端启动期 env、默认关、不可由外部输入触发、只影响流式首版判定，"
    "而且现在**每份报告都自带 `env_flags`**，「不存在偷偷开钩子把绿混进来」的空间。"
    "（若哪天去掉钩子，`ss-03` 会立刻 FAIL 并点名缺哪个变量——这正是可审计的形态。）\n"
    "- **`cc-01` 种植轮触发闸门**：定性为**闸门作用域错配，不是产品缺陷，但也不豁免、要修**。"
    "证据是「命中 16 次、重生失败 14 次全在种植轮」——**重生从未救回来过一次**，"
    "说明那些轮次本就不该要求「可核查事实」（种植轮是往会话里塞背景资料，模型回「记下了」是正确行为）。"
    "代价是每轮评测白烧 11~14 次 LLM 调用并污染 badcase 档案。→ **已列入 P4f C0-③**。\n"
    "- **联网不覆盖被判定为 `chitchat` 的域外问句**：⏸ 挂起，需扩意图类别（如 `web_fact`），"
    "属设计变更，另单处理；本轮不阻塞。\n"
    "- **`WEB_SEARCH_TIMEOUT_S=60` 语义**：httpx 的是**空闲超时**不是**总时限**（实测同问句 12.3s/79.4s，"
    "60s 并未截断 79.4s 那次），文档却写「超时 60s」。→ 列入 **P4f C0-④**：改名为 idle 语义或加总时限，"
    "并把 UI 等待预期写清。\n"
    "\n"
    "**两处遗留问题（合并后第一优先级，已写进 P4f C0）**\n"
    "\n"
    "1. 🔴 **红线级**：`run_evals.py` 的 `env_flags.client_env` 收集所有 `NOVA*` 环境变量，"
    "而评测报告**是要提交进 git 的**。今天实测只有 `NOVAAGENT_EVAL_TEMPERATURE`（无害），"
    "但一旦有人按惯例 `export NOVAAGENT_LLM_API_KEY=...`，**密钥就会被写进入库报告**。"
    "改成显式白名单（只收 `NOVA_GROUNDING_*`/`NOVA_GRAPH_ENABLED`/`NOVA_MAX_REWRITE`/`NOVA_FUSION_TOP_K`/"
    "`NOVAAGENT_EVAL_TEMPERATURE` 这类非敏感项），并补一条「含 KEY/TOKEN/PASSWORD 的键名一律不落盘」的单测。\n"
    "2. ⚠ **口径记账**：S2 改了 `ss-*` 的问句刺激与渐进性阈值但**没升 `version`（仍 v2.4）**，"
    "于是「v2.4」这个标签现在覆盖两种测试刺激、两种阈值。已在 `docs/EVAL_BASELINE.md` 补记，"
    "并要求以后**问句级变更也算口径变更**（与坑 40 同族）。\n"
    "\n"
    "**我自己的取证缺陷（自纠）**：第一版 `review_qoder_s2_gate.py` 因变量名笔误（`REP` 写成 `REPORT`）"
    "在第 4 阶段崩溃，两档整轮没跑成；分离度数据已拿到，我另写 `review_qoder_s2_rounds.py` 补跑两档。"
    "另外 `reports/_port_owner.txt` 显示实现方复查端口时发现我上一轮留下的 :8923 孤儿实例（我自己没复查到），"
    "他们清掉了——坑 61 我自己又踩了一次，姿势仍不彻底：**杀完必须按端口复查**。\n"
)
T.insert(k + 1, CONC)
log.append("S2 第 2 回 Review 结论插入")

io.open(P, "w", encoding="utf-8", newline="").write("".join(T))
nb1 = len([l for l in T if l.strip()])
assert nb1 > nb0
log.append("TASKS non-blank %d -> %d" % (nb0, nb1))

# ---------------- HANDOFF.md ----------------
P2 = "HANDOFF.md"
H = io.open(P2, encoding="utf-8").read().splitlines(True)
h0 = len([l for l in H if l.strip()])

p = [k for k, l in enumerate(H) if "**下一步 = 等 WorkBuddy 交回 S2 四条(阈值/可审计/归因/记账)**" in l]
assert len(p) == 1, p
H[p[0]] = H[p[0]].replace(
    "**下一步 = 等 WorkBuddy 交回 S2 四条(阈值/可审计/归因/记账)**",
    "**P4e 主体 + S1 + S2 = ✅ 全部通过并合并 `master`**(2026-10-01 晨,基线 v2.4 / 55 用例)。"
    "S2 四条我逐条独立复验成立:两档 span 我自己测(全缓冲 35~56ms vs 早窗 2687~5713ms,约 48 倍间隔),"
    "阈值 150 落在分布之外;**默认档 54/55、canonical 档 55/55 我都复现了**,且报告带 `env_flags`、"
    "`ss-03` 失败文案点名环境变量;`cc-01` 种植轮归因我也独立量化(命中 16/重生失败 14 全在种植轮,"
    "`final` 从未命中)。**实现方两处推翻我的判断,我复核后都认同**:① 我提的相对阈值 "
    "`max(120,0.10×E2E)` 在本语料会落回 300~640ms 又压进分布里,不该用;② 真正的病根不是阈值数字而是"
    "**问句太短让两档分布贴合**,他们改成三段式长问句比我把 300 调成 150 更彻底。"
    "**两项合并后必修已转 P4f C0**:🔴 `env_flags.client_env` 收所有 `NOVA*` 变量而报告要入库 → "
    "一旦有人 export `NOVAAGENT_LLM_API_KEY` 就会把密钥提交进 git(今天无害,但是红线形状);"
    "⚠ 改了 `ss-*` 问句却没升 version,`v2.4` 现在覆盖两种刺激(问句级变更也算口径变更)。"
    "另裁决:`cc-01` 种植轮的闸门触发=**作用域错配**(重生 14 次全失败=那些轮本就不该要求可核查事实),"
    "每轮白烧 11~14 次 LLM 调用,列入 P4f C0-③。"
    "**下一步 = 等 WorkBuddy 交回 P4f(辅导员 persona)+ C0 四条**")
log.append("HANDOFF 下一步更新")

PIT = (
    "64. **硬门控的判据要先问「这一轮本来就该有可核查事实吗」**（2026-10-01 复核 P4e S2 发现）："
    "M4 那道 grounding 闸门（有来源却零 `[n]` 零数字 → 判无效 → 重生）在 qa 上是对的，"
    "但在评测的**种植轮**上命中 16 次、**重生失败 14 次**、`final` 轮一次都没命中 —— "
    "「重生从未救回来过一次」不是模型不争气，而是**前提不成立**：种植轮是往会话里塞背景资料，"
    "模型回一句「记下了」才是正确行为，那里本就没有需要引用的事实。"
    "代价是每轮评测白烧 11~14 次 LLM 调用、badcase 档案被噪声灌满。"
    "铁律：① 任何「答案必须含 X」式硬门控，落地前先枚举**它会被套在哪些轮次类型**上"
    "（提问轮 / 陈述轮 / 确认轮 / 追问轮 / 压缩种植轮），只对该回答事实的轮次生效；"
    "② **用「重生后成功率」反过来检验判据是否错配**——某类轮次 100% 重生失败，几乎一定是判据用错了地方，"
    "不是模型能力问题；③ 归因要能自证：本条若没有 S2-③ 新增的「逐用例逐轮 `grounding_gate` 记账」，"
    "就只能像上一轮的我一样去猜「最可疑是 cc-01」——**评测侧留痕，才让归因从猜测变成读数**。\n"
)
p63 = [k for k, l in enumerate(H) if l.startswith("63. **给别人的验收阈值")]
assert len(p63) == 1, p63
H.insert(p63[0] + 1, PIT)
log.append("HANDOFF 坑 64 插入")

h1 = len([l for l in H if l.strip()])
assert h1 > h0
io.open(P2, "w", encoding="utf-8", newline="").write("".join(H))
log.append("HANDOFF non-blank %d -> %d" % (h0, h1))

print(" | ".join(log))
