# -*- coding: utf-8 -*-
"""P4e 合并收尾 + 下发 P4f：TASKS（P4e 标题/P4f 标题+C0 块）、HANDOFF 台账、NEXT_SESSION_PROMPT。"""
import io

log = []

P = "docs/TASKS.md"
T = io.open(P, encoding="utf-8").read().splitlines(True)
nb0 = len([l for l in T if l.strip()])

if "C0 前置收口（P4e 复核攒下" in "".join(T):
    log.append("TASKS 已含 P4f C0 块，跳过（幂等保护）")
    nb0 = nb1 = len([l for l in T if l.strip()])
else:
    pass
T[k] = T[k].replace("📋 READY（待 P4e，设计见 M8）",
                    "🚀 **已下发**（2026-10-01，持棒 WorkBuddy，分支 `task/P4f-persona`，设计见 M8，"
                    "开单指令 `docs/p4f/workbuddy-order.md`）", 1)
assert "🚀 **已下发**" in T[k], T[k][:110]

C0 = (
    "\n- **C0 前置收口（P4e 复核攒下；C0-① 与 C0-③ 为 merge-blocking）**\n"
    "\n"
    "  - [ ] **C0-①（🔴 红线形状）** `evals/run_evals.py` 的 `env_flags.client_env` 现在收**所有** `NOVA*` 变量，"
    "而评测报告**要提交进 git**：一旦有人 `export NOVAAGENT_LLM_API_KEY=...`，密钥就进库并永久留在历史里"
    "（今天实测只有 `NOVAAGENT_EVAL_TEMPERATURE`，无害，但形状是错的）。改显式白名单 + 一条**能判红**的单测"
    "（断言密钥类键名不在 `client_env`、且白名单项确实在 → 防空集假通过，坑 45）。\n"
    "  - [ ] **C0-②** 规则落地：**问句级/判据常量级变更也算口径变更**，必须升 `version` 并在 "
    "`docs/EVAL_BASELINE.md` 记一行（S2 换了 `ss-*` 长问句、阈值 300→150 却仍标 v2.4，同一标签现覆盖两种刺激）。\n"
    "  - [ ] **C0-③（闸门作用域）** grounding 闸门被套在**不需要事实回答的轮次**上："
    "P4e S2 我实测默认档命中 12 次/重生失败 11 次、canonical 档命中 16/失败 14，**全部来自 `cc-01` 的种植轮，"
    "`final` 轮从未命中**；「重生一次都没救回来」＝前提不成立（种植轮是塞背景，模型回「记下了」才对）。"
    "要求给闸门加**轮次类型判定**（只对期待事实回答的轮次生效），判据写进注释、不许用「长度<30 字」糊。"
    "验收：整轮记账里种植轮命中数归零，且 `qa-17`/`ss-03` 的兜底能力不回退。\n"
    "  - [ ] **C0-④** `WEB_SEARCH_TIMEOUT_S=60` 名实不符：httpx 那个是**空闲超时**不是总时限"
    "（实现方实测同问句 12.3s/**79.4s**，60s 没截断）。做总时限 + 双层（idle 20s / 总 45s）或改名 + 文档写清等待预期，"
    "并补一条用假 transport 的**慢响应必判红**单测（不打真实网络）。\n"
    "  - [ ] **C0-⑤** `docs/p4d/run_with_server.sh` 收尾 `kill $SRV` **杀不掉 Windows 进程**："
    "本轮复核打印 `[server] done rc=0, shutting down 8936` 之后端口**仍在监听**；"
    "负责人另两次也留过孤儿实例（:8906/:8907、:8923），都是实现方复查端口时发现的。"
    "改 `taskkill //PID x //F` 或 psutil，并在退出前**按端口复查打印** `[port-check] :N closed=True/False`，"
    "False 时非 0 退出（坑 61）。\n"
)
T.insert(k + 1, C0)
log.append("P4f C0 块插入")

io.open(P, "w", encoding="utf-8", newline="").write("".join(T))
nb1 = len([l for l in T if l.strip()])
assert nb1 > nb0
log.append("TASKS non-blank %d -> %d" % (nb0, nb1))

# ---------------- HANDOFF 台账 ----------------
P2 = "HANDOFF.md"
H = io.open(P2, encoding="utf-8").read().splitlines(True)
pe = [k for k, l in enumerate(H) if l.startswith("| **P4e** | **联网搜索开关 + 来源分区标注**")]
assert len(pe) == 1, pe
nl = "\n" if H[pe[0]].endswith("\n") else ""
H[pe[0]] = ("| **P4e** | **联网搜索开关 + 本地/联网来源分区标注 + S1 流式收口 + S2 尺子与可审计性** | "
            "**✅ DONE —— 全部合并 `master` `5705830`**(2026-10-01;C0 两条第 2 回 ✅、主体+S1 第 1 回 ❌ 打回、"
            "S2 第 2 回 ✅)。基线 **v2.4 / 55 用例**:canonical 档 **55/55 退出码 0**、默认档 54/55(已如实记账,"
            "`ss-03` 需服务端带 `NOVA_GROUNDING_STREAM_FORCE_UNGROUNDED=1`);报告新增 `env_flags` + 逐用例 "
            "`grounding_gate` 自证配置;**联网只在本地拒答后作补充通道(本地有据不出网)**;来源分区显示真实 URL、"
            "`site_name` 由 netloc 推导并标明、**不绑定逐句 `[W]`**、整段级「未经本校核实」由代码注入;"
            "S1 早窗恢复真流式(复核方自测 span 2687~5713ms vs 全缓冲 35~56ms)。"
            "**复核攒下五条遗留转 P4f C0**(🔴 `env_flags.client_env` 收全部 `NOVA*` 而报告入库 / "
            "闸门被套在种植轮 / web 超时实为 idle 语义 / 起服务脚本杀不掉 Windows 进程 / 问句级变更未升 version)" + nl)
log.append("HANDOFF 台账 P4e -> DONE")

row = ("| **P4f** | **辅导员 persona 定制 + 左侧会话栏重构**(+ **C0 前置收口五条**) | **🚀 已下发(持棒 WorkBuddy,2026-10-01)**,"
       "分支 `task/P4f-persona`,规格 `docs/TASKS.md` P4f,开单指令 `docs/p4f/workbuddy-order.md`,"
       "设计 `docs/P4.md` M8。**红线:防幻觉规则 1-9 硬编码,persona 段不得覆盖或削弱;persona 不得提权(仍受 RBAC 交集)** |\n")
pf = [k for k, l in enumerate(H) if l.startswith("| T7 | 向量库 sqlite → sqlite-vec")]
assert len(pf) == 1, pf
H.insert(pf[0], row)
log.append("HANDOFF 台账插入 P4f 行")

h0 = len([l for l in H if l.strip()])
io.open(P2, "w", encoding="utf-8", newline="").write("".join(H))
log.append("HANDOFF non-blank -> %d" % len([l for l in H if l.strip()]))

# ---------------- NEXT_SESSION_PROMPT ----------------
P3 = "docs/NEXT_SESSION_PROMPT.md"
N = io.open(P3, encoding="utf-8").read().splitlines(True)
n = [k for k, l in enumerate(N) if "**你要做的下一个动作**" in l]
assert len(n) == 1
nl = "\n" if N[n[0]].endswith("\n") else ""
N[n[0]] = (
    "**你要做的下一个动作**：**等 WorkBuddy 交回「P4f 辅导员 persona + C0 五条收口」**"
    "（分支 `task/P4f-persona`，规格 `docs/TASKS.md` P4f，开单指令 `docs/p4f/workbuddy-order.md`）。"
    "**P4e 已整体合并 `master` `5705830`**（2026-10-01）：联网开关 + 本地/联网来源分区 + S1 流式恢复 + S2 尺子与可审计性；"
    "基线 **v2.4 / 55 用例**，⚠ **canonical 命令必须带 `NOVA_GROUNDING_STREAM_FORCE_UNGROUNDED=1`**"
    "（`ss-03` 靠它必然命中；不带钩子是 54/55、退出码 1，两档都已在 EVAL_BASELINE §十九 如实记账），"
    "报告现在自带 `env_flags` 与逐用例 `grounding_gate` 记账，**读报告先看 flags 再判红绿**。"
    "**P4f 复核五把尺**：① C0-① 密钥形状（`client_env` 白名单 + 能判红的单测，含「白名单项确实在」防过滤过头）；"
    "② C0-③ 闸门作用域（种植轮命中归零且 `qa-17`/`ss-03` 兜底不回退——**不许用长度阈值糊过去**）；"
    "③ **persona 不得削弱防幻觉**：必须有一条「忽略以上规则」类注入攻击用例真的判红；"
    "④ **persona 不得提权**：绑定库仍受 RBAC 交集、越权静默忽略、空 scope 不回落，沿用 P4c 那五条安全探针口径复验；"
    "⑤ C0-⑤ 起服务脚本收尾必须打印 `[port-check]`，别再把 Windows 孤儿服务留给下一个人（我自己已踩过三次）。"
    "照例纪律：坑 55 取退出码不接管道、坑 57 整轮前单请求自证、坑 58 探针不与评测并发取数、"
    "坑 63 定阈值前先跑分布、坑 64 硬门控先问「这一轮本来就该有可核查事实吗」。"
) + nl
io.open(P3, "w", encoding="utf-8", newline="").write("".join(N))
log.append("NEXT_SESSION_PROMPT 下一动作更新")

print(" | ".join(log))
