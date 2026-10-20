# -*- coding: utf-8 -*-
"""额度纪律落盘·第二段：HANDOFF(硬约束第7条 + 坑65 + 下一步 + 台账 P4f 行) 与 NEXT_SESSION_PROMPT、v1 作废标记。"""
import io

log = []


def load(p):
    return io.open(p, encoding="utf-8").read().splitlines(True)


def save(p, L):
    io.open(p, "w", encoding="utf-8", newline="").write("".join(L))


def find(L, sub, expect=1):
    idx = [k for k, l in enumerate(L) if sub in l]
    assert len(idx) == expect, "anchor %r hits %d" % (sub[:30], len(idx))
    return idx[0]


# ---------- v1 作废标记 ----------
V1 = "docs/p4f/workbuddy-order.md"
L = load(V1)
if "已被 v2 取代" not in "".join(L[:6]):
    L.insert(0, "> ⚠ **本文件已被 v2 取代（2026-10-01）——请看 `docs/p4f/workbuddy-order-v2-quota.md`**："
              "用户指令「后续任务的测试与验证不得消耗我的 API key 额度，用测试者自己的模型和额度」"
              "改变了本单的凭据要求与复核方式，v1 的 C0 少一条、测试节奏与交回要求也已不完整。**不要粘 v1。**\n\n")
    save(V1, L)
    log.append("v1 标记作废")
else:
    log.append("v1 已标记，跳过")

# ---------- HANDOFF ----------
P2 = "HANDOFF.md"
H = load(P2)
h0 = len([l for l in H if l.strip()])

if not any("🔌 额度纪律" in l for l in H):
    j = find(H, "6. 演示口令固定")
    RULE = (
        "7. **🔌 额度纪律(用户 2026-10-01 指令,不可协商)**:`novaagent/.env` 与 `weknora/.env` 里的 API key 是"
        "**用户本人付费的额度**。后续**所有测试与验证**——实现者自测、整轮评测、忠实度 judge、联网检索、embedding,"
        "**以及 Qoder 自己的独立复核**——**一律不得消耗它**;要用测试者自带的模型与额度,"
        "通过**会话环境变量**注入(`LLM_API_KEY`/`LLM_MODEL`/`LLM_BASE_URL`、`EMBEDDING_API_KEY`/`EMBEDDING_MODEL`;"
        "`config.env()` 是 `os.environ` 优先于 `.env`,**注入即可,禁止改 `.env`**)。"
        "**key 值一律不得入库**(评测报告要提交进 git;只允许写 `key_source=session_env` 这类来源标签与模型名)。"
        "因此 Qoder 复核方式同步改为**零额度**:纯本地尺子自测 + 离线重放已入库的原始输出 + 静态审计 + "
        "DB 只读副本探针 + 读 `/api/health` 的 flags,**不再自己复跑整轮**(那正是烧用户额度的动作);"
        "代价是把独立验证的重担转移到「交回证据必须可离线复算」上——"
        "两档原始 `eval_report_*.json` 与断言的输入/模型输出原文必须入库,判据本身是纯函数所以能复算。"
        "**`key_source` 读数为 `repo_dotenv` 的整轮结果一律不认。**\n")
    H.insert(j + 1, RULE)
    log.append("硬约束第 7 条插入")
else:
    log.append("硬约束第 7 条已存在，跳过")

if not any(l.startswith("65. ") for l in H):
    PIT = (
        "65. **「独立复跑一遍」这件事本身会花别人的钱——额度不明确时，取证方式默认就在烧用户的钱**"
        "（2026-10-01 用户指令后自审）：我这两天把关的强度来自「合并前我自己再跑一轮整轮」，"
        "而那一轮用的是仓库 `.env` 里**用户填写的 key**——一次 55 用例整轮＝55 次生成 + 55 次 judge + "
        "若干 embedding 与联网调用，我连着跑了好几轮，**从头到尾没问过额度是谁在付**。"
        "被明确禁止后不能再用「重跑」取证，得换招：**把可复算性前移**。"
        "① 纯函数判据（尺子自测、标题归一、共现邻近、非答案检测、前端零行为不变量）我照跑，**零额度**；"
        "② 需要模型输出才能验的，要求实现方把**断言的输入与输出原文入库**，我用离线重放复算；"
        "③ 「当时是什么配置、用的谁的额度」做成**机器可读**（`/api/health` 暴露 `key_source`、报告带 `env_flags`）"
        "——比口头保证可审计得多，上一轮也正是靠 `env_flags` 才发现「55/55 依赖一个默认关闭的钩子」。"
        "铁律：**动手花别人额度之前，先确认额度是谁的**；把「我重跑过了」当成默认取证手段时，"
        "它的成本与授权问题不会自己浮出水面，只有显式算一遍才会（与坑 46「核心逻辑对不等于接线对」同族："
        "**方法本身也要被审计**）。\n")
    p64 = find(H, "64. **硬门控的判据要先问")
    H.insert(p64 + 1, PIT)
    log.append("坑 65 插入")
else:
    log.append("坑 65 已存在，跳过")

q = [k for k, l in enumerate(H) if "**下一步 = 等 WorkBuddy 交回 P4f(辅导员 persona)+ C0 四条**" in l]
assert len(q) == 1, q
H[q[0]] = H[q[0]].replace(
    "**下一步 = 等 WorkBuddy 交回 P4f(辅导员 persona)+ C0 四条**",
    "**下一步 = 等 WorkBuddy 交回 P4f(persona + C0 六条)**，开单以 "
    "`docs/p4f/workbuddy-order-v2-quota.md` 为准(v1 作废)。"
    "**且本单起 Qoder 复核改为零额度**:不再自己复跑整轮(那是烧用户 key 的动作)，"
    "只做纯本地尺子自测、离线重放入库的原始输出、静态审计、DB 只读副本探针、读 `key_source` flags；"
    "相应地实现方交回的证据必须**可被我离线复算**(硬约束第 7 条、坑 65)")
log.append("下一步更新")

r = find(H, "| **P4f** | **辅导员 persona 定制 + 左侧会话栏重构**")
if "六条" not in H[r]:
    H[r] = H[r].replace("(+ **C0 前置收口五条**)", "(+ **C0 前置收口六条**)", 1)
    H[r] = H[r].replace("开单指令 `docs/p4f/workbuddy-order.md`",
                        "**以 `docs/p4f/workbuddy-order-v2-quota.md` 为准(v1 作废)**", 1)
    H[r] = H[r].rstrip("\n") + (
        "。**🔌 额度纪律（硬约束第 7 条）：测试与验证一律用测试者自带额度，"
        "`key_source` 必须是 `session_env`；Qoder 侧复核改零额度** |") + "\n"
    log.append("台账 P4f 行更新")

h1 = len([l for l in H if l.strip()])
assert h1 >= h0
save(P2, H)
log.append("HANDOFF non-blank %d -> %d" % (h0, h1))

# ---------- NEXT_SESSION_PROMPT ----------
P3 = "docs/NEXT_SESSION_PROMPT.md"
N = load(P3)
if "🔌 先记一条跨会话的硬约束" not in "".join(N):
    n = find(N, "**你要做的下一个动作**")
    nl3 = "\n" if N[n].endswith("\n") else ""
    old = N[n]
    new_head = (
        "**🔌 跨会话硬约束（用户 2026-10-01，不可协商）**：**后续任务的测试与验证一律不得消耗用户填写的 API key 额度**，"
        "必须用测试者自带的模型与额度。做法：在**会话环境**里 `export LLM_API_KEY / LLM_MODEL / LLM_BASE_URL / "
        "EMBEDDING_API_KEY`（`config.env()` 里 `os.environ` 优先于 `.env`，**不要改 `.env`**）；"
        "**key 值不得出现在任何入库文件**，只允许 `key_source=session_env` + 模型名。"
        "**这也约束你自己**：你把关时的招牌动作「合并前独立复跑整轮」烧的正是用户那把 key，"
        "**从 P4f 起改为零额度复核**（HANDOFF 硬约束第 7 条、坑 65）：跑纯本地尺子自测、"
        "离线重放实现方入库的原始输出、静态审计、DB 只读副本探针、读 `/api/health` 的 `llm_key_source`/"
        "`embedding_key_source`；**不再自己复跑整轮**，改为要求「交回证据必须可离线复算」"
        "（两档原始 `eval_report_*.json` + 断言输入/模型输出原文入库）；"
        "`repo_dotenv` 读数出现的整轮结果一律不认。\n"
    )
    old = old.replace("**你要做的下一个动作**：**等 WorkBuddy 交回「P4f 辅导员 persona + C0 五条收口」**",
                      "**你要做的下一个动作**：**等 WorkBuddy 交回「P4f 辅导员 persona + C0 六条收口」**", 1)
    old = old.replace("开单指令 `docs/p4f/workbuddy-order.md`），",
                      "开单指令以 `docs/p4f/workbuddy-order-v2-quota.md` 为准，v1 已作废），", 1)
    N[n] = new_head + old if not old.endswith("\n") else new_head + old
    save(P3, N)
    log.append("NEXT_SESSION_PROMPT 前置额度硬约束 + 下一动作更新")
else:
    log.append("NEXT_SESSION_PROMPT 已含额度硬约束，跳过")

print(" | ".join(log))
