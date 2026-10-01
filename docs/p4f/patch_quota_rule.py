# -*- coding: utf-8 -*-
"""把「额度纪律」写进四处会存活跨会话的地方：TASKS、HANDOFF(硬约束+坑65+台账+下一步)、NEXT_SESSION_PROMPT、v1 开单指令标记被取代。"""
import io

log = []


def load(p):
    return io.open(p, encoding="utf-8").read().splitlines(True)


def save(p, L):
    io.open(p, "w", encoding="utf-8", newline="").write("".join(L))


def find(L, sub, expect=1):
    idx = [k for k, l in enumerate(L) if sub in l]
    assert len(idx) == expect, "anchor %r hits %d" % (sub[:28], len(idx))
    return idx[0]


# ---------- 1) v1 开单指令：标记被取代 ----------
V1 = "docs/p4f/workbuddy-order.md"
L = load(V1)
if "已被 v2 取代" not in "".join(L[:6]):
    L.insert(0, "> ⚠ **本文件已被 v2 取代（2026-10-01）——请看 `docs/p4f/workbuddy-order-v2-quota.md`**："
              "用户指令「后续任务的测试与验证不得消耗我的 API key 额度，用测试者自己的模型和额度」"
              "改变了本单的凭据与复核方式，v1 的 §2/§4/§5 已不完整。**不要粘 v1。**\n\n")
    save(V1, L)
    log.append("v1 标记被取代")

# ---------- 2) TASKS.md ----------
P = "docs/TASKS.md"
T = load(P)
nb0 = len([l for l in T if l.strip()])

# 2a 持棒头部：改成 v2 下发
i = find(T, "> **当前持棒：Qoder → 已下发 P4f（含 C0 前置收口）**")
nl = "\n" if T[i].endswith("\n") else ""
T[i] = ("> **当前持棒：WorkBuddy**（**P4f 以 v2 重新下发**：`docs/p4f/workbuddy-order-v2-quota.md`，"
        "分支 `task/P4f-persona`；v1 已标记作废）。"
        "**P4e 主体 + S1 + S2 已 ✅ 合并 `master` `5705830`，基线 v2.4 / 55 用例**"
        "（canonical 档 55/55 退出码 0、默认档 54/55 均如实入库；报告自带 `env_flags` 与逐用例 `grounding_gate`）。"
        "**⚠ 用户 2026-10-01 指令（最高优先级纪律，也约束 Qoder 自己）**："
        "后续任务的测试与验证**不得消耗用户填写的 API key 额度**，必须用测试者自带的模型与额度——"
        "做法是会话内 `export LLM_API_KEY/LLM_MODEL/EMBEDDING_API_KEY`（`config.env()` 里 os.environ 优先于 `.env`，"
        "不改 `.env`），且**key 值一律不得入库**；本单加 **C0-⑥** 把它做成机器可核验（`/api/health` 暴露 "
        "`llm_key_source`/`embedding_key_source`，报告里读数为 `repo_dotenv` 的整轮**一律不认**）。"
        "**Qoder 侧同步改为零额度复核**：跑纯本地尺子自测、离线重放已入库的原始输出、静态审计、DB 只读副本探针、读 flags；"
        "不再自己复跑整轮（那正是烧用户额度的动作），因此**实现方交回的证据必须可被我离线复算**（原始报告与输入输出入库）。"
        "详见 HANDOFF 硬约束第 7 条与坑 65。") + nl
log.append("TASKS 持棒头部改 v2 下发 + 额度纪律")

# 2b P4f 的 C0 块补第 6 条
k = find(T, "  - [ ] **C0-⑤** `docs/p4d/run_with_server.sh` 收尾 `kill $SRV` **杀不掉 Windows 进程**")
C06 = (
    "  - [ ] **C0-⑥（🔌 额度可核验化，用户 2026-10-01 指令，merge-blocking）** 把「不用用户 key」做成代码而不是口头承诺："
    "`config.py` 加 `key_source(key)`（返回 `session_env`/`repo_dotenv`/`unset`，**绝不返回值**）→ "
    "`/api/health` 的 flags 暴露 `llm_key_source`、`embedding_key_source` → 评测报告 `env_flags.server` 自动带上 →"
    " **闸门规则：key_source 读数为 `repo_dotenv` 的整轮结果一律不认**。"
    "自测在「注入 / 不注入」两种状态下各取一次 `/api/health` 落盘对照（只读 health，不烧额度）。\n"
    "- **🔌 额度与凭据纪律（本单最高优先级，违反即打回）**：`novaagent/.env` 里的 key 是**用户本人的额度**。"
    "任何真发请求（服务自测、整轮评测、忠实度 judge、联网检索、embedding）都必须走会话环境变量注入的自带 key；"
    "**不允许也不需要用改 `.env` 来切换**（`os.environ` 优先）；**key 值不得出现在任何入库文件里**，"
    "只允许写来源标签与模型名。省额度做法：实现期只做不烧额度的检查（纯本地尺子、DB 只读副本、离线重放、"
    "假 transport 单测、`/api/health`），**整轮一单只跑一次**。\n"
    "- **⚠ 交回必须「零额度可复核」**：因为 Qoder 不再复跑整轮，你必须把断言用到的输入与模型输出原文入库"
    "（原始 `eval_report_*.json` 两档 + 证据 JSON），让判据能被纯函数离线复算——"
    "**入库证据不足以复算时，我会回来请你用你的额度补跑指定探针，不会动用户那把 key**。\n"
)
T.insert(k + 1, C06)
log.append("TASKS P4f C0-⑥ 与额度纪律插入")

save(P, T)
nb1 = len([l for l in T if l.strip()])
assert nb1 > nb0
log.append("TASKS non-blank %d -> %d" % (nb0, nb1))

# ---------- 3) HANDOFF.md ----------
P2 = "HANDOFF.md"
H = load(P2)
h0 = len([l for l in H if l.strip()])

# 3a 硬约束第 7 条
j = find(H, "6. 演示口令固定")
RULE = ("7. **🔌 额度纪律(用户 2026-10-01 指令,不可协商)**:`novaagent/.env` 与 `weknora/.env` 里的 API key 是"
        "**用户本人付费的额度**。后续**所有测试与验证**——包括实现者自测、整轮评测、忠实度 judge、联网检索、embedding,"
        "**以及 Qoder 自己的独立复核**——**一律不得消耗它**;要用测试者自带的模型与额度,"
        "通过**会话环境变量**注入(`LLM_API_KEY`/`LLM_MODEL`/`LLM_BASE_URL`、`EMBEDDING_API_KEY`/`EMBEDDING_MODEL`;"
        "`config.env()` 是 `os.environ` 优先于 `.env`,所以**注入即可,禁止改 `.env`**)。"
        "**key 值一律不得入库**(报告要提交进 git,只允许写 `key_source=session_env` 这类来源标签与模型名)。"
        "因此 Qoder 的复核方式同步改为**零额度**:纯本地尺子自测 + 离线重放已入库的原始输出 + 静态审计 + DB 只读副本探针 + 读 flags,"
        "**不再自己复跑整轮**;代价是把「独立验证」的重担转移到「交回证据必须可离线复算」上——"
        "原始 `eval_report_*.json`(两档)与断言输入/模型输出原文必须入库,判据本身是纯函数所以能复算。"
        "**任何一份 key_source 读数为 `repo_dotenv` 的整轮结果都不作数。**\n")
H.insert(j + 1, RULE)
log.append("HANDOFF 硬约束第 7 条插入")

# 3b 坑 65
PIT = (
    "65. **「独立复跑一遍」这件事本身会花别人的钱——复核方式必须跟着换**（2026-10-01 用户指令）："
    "我这两天的把关强度来自「合并前我自己再跑一轮整轮」，而**那一轮用的是仓库 `.env` 里用户填写的 key**——"
    "一次 55 用例整轮＝55 次生成 + 55 次 judge + 若干 embedding/联网调用，我跑了多轮，从没问过额度是谁在付。"
    "用户明确禁止后，我不能再靠「重跑」取证，得换招：**把可复算性前移**。"
    "① 纯函数判据（尺子自测、归一、共现邻近、非答案检测、静态不变量）我照样自己跑，**零额度**；"
    "② 需要模型输出才能验的东西，要求实现方把**断言的输入与输出原文入库**，我用离线重放复算；"
    "③ 配置与「当时用谁的额度」做成**机器可读**（`/api/health` 暴露 `key_source`，报告带 `env_flags`），"
    "比任何口头保证都可审计——上一轮正是靠 `env_flags` 才发现「55/55 依赖一个默认关闭的钩子」。"
    "铁律：**动手花别人额度前先确认额度是谁的**；把「我重跑过了」当成默认取证方式时，"
    "它的成本与授权问题不会自己浮出水面，只有显式算一遍才会。\n"
)
p64 = find(H, "64. **硬门控的判据要先问")
H.insert(p64 + 1, PIT)
log.append("HANDOFF 坑 65 插入")

# 3c 下一步
q = find(H, "**下一步 = 等 WorkBuddy 交回 P4f（辅导员 persona）+ C0 四条**")
H[q] = H[q].replace(
    "**下一步 = 等 WorkBuddy 交回 P4f（辅导员 persona）+ C0 四条**",
    "**下一步 = 等 WorkBuddy 交回 P4f（persona + C0 六条）**，且**本单起 Qoder 复核改为零额度**："
    "不再自己复跑整轮（那是烧用户 key），只做纯本地尺子自测、离线重放入库的原始输出、静态审计、"
    "DB 只读副本探针与 flags 读数；额度纪律见硬约束第 7 条与坑 65。")
log.append("HANDOFF 下一步更新")

# 3d 台账 P4f 行加 v2 与 C0-⑥
r = find(H, "| **P4f** | **辅导员 persona 定制 + 左侧会话栏重构**")
H[r] = H[r].replace("(+ **C0 前置收口五条**) | **🚀 已下发(持棒 WorkBuddy,2026-10-01)**,"
                    "分支 `task/P4f-persona`,规格 `docs/TASKS.md` P4f,开单指令 `docs/p4f/workbuddy-order.md`,",
                    "(+ **C0 前置收口六条**) | **🚀 已下发 v2(持棒 WorkBuddy,2026-10-01)**,"
                    "分支 `task/P4f-persona`,规格 `docs/TASKS.md` P4f,"
                    "**以 `docs/p4f/workbuddy-order-v2-quota.md` 为准(v1 已作废)**,", 1)
H[r] = H[r].replace("**红线:防幻觉规则 1-9 硬编码,persona 段不得覆盖或削弱(要有注入攻击用例真判红);"
                    "persona 不得提权(仍受 RBAC 交集)** |",
                    "**红线:防幻觉规则 1-9 硬编码,persona 段不得覆盖或削弱(要有注入攻击用例真判红);"
                    "persona 不得提权(仍受 RBAC 交集)**。"
                    "**🔌 C0-⑥:测试与验证一律用测试者自带额度(`key_source` 必须是 session_env),Qoder 侧复核改零额度** |")
log.append("HANDOFF 台账 P4f 行更新")

h1 = len([l for l in H if l.strip()])
assert h1 >= h0
save(P2, H)
log.append("HANDOFF non-blank %d -> %d" % (h0, h1))

# ---------- 4) NEXT_SESSION_PROMPT ----------
P3 = "docs/NEXT_SESSION_PROMPT.md"
N = load(P3)
n = find(N, "**你要做的下一个动作**：**等 WorkBuddy 交回「P4f 辅导员 persona + C0 五条收口」**")
nl3 = "\n" if N[n].endswith("\n") else ""
N[n] = (
    "**🔌 先记一条跨会话的硬约束（用户 2026-10-01）**：**后续任务的测试与验证一律不得消耗用户填写的 API key 额度**，"
    "要用测试者自带的模型与额度。具体做法：在**会话环境**里 `export LLM_API_KEY / LLM_MODEL / LLM_BASE_URL / "
    "EMBEDDING_API_KEY`（`config.env()` 里 os.environ 优先于 `.env`，**不要改 `.env`**）；"
    "**key 值不得出现在任何入库文件**，只允许 `key_source=session_env` + 模型名。"
    "**这也约束你自己**：你过去把关时的「合并前独立复跑整轮」烧的正是用户 `.env` 那把 key，"
    "**从本单起改为零额度复核**（HANDOFF 硬约束第 7 条、坑 65）——跑纯本地尺子自测、离线重放实现方入库的原始输出、"
    "静态审计、DB 只读副本探针、读 `/api/health` 的 `llm_key_source`/`embedding_key_source`；"
    "**不再自己复跑整轮**，改为要求「交回证据必须可离线复算」（两档原始 `eval_report_*.json` + 断言输入/模型输出原文入库）。"
    "`repo_dotenv` 读数出现的整轮结果一律不认。\n"
    + N[n].replace("**你要做的下一个动作**：**等 WorkBuddy 交回「P4f 辅导员 persona + C0 五条收口」**"
                   "（分支 `task/P4f-persona`，规格 `docs/TASKS.md` P4f，开单指令 `docs/p4f/workbuddy-order.md`）。",
                   "**你要做的下一个动作**：**等 WorkBuddy 交回「P4f 辅导员 persona + C0 六条收口」**"
                   "（分支 `task/P4f-persona`，规格 `docs/TASKS.md` P4f，"
                   "**开单指令以 `docs/p4f/workbuddy-order-v2-quota.md` 为准，v1 已作废**）。") + nl3)
save(P3, N)
log.append("NEXT_SESSION_PROMPT 前置额度硬约束 + 下一动作更新")

print(" | ".join(log))
