# -*- coding: utf-8 -*-
"""P4e 合并收尾的第二段：HANDOFF 台账（P4e -> DONE、插入 P4f 行）+ NEXT_SESSION_PROMPT 下一动作。"""
import io

log = []
P2 = "HANDOFF.md"
H = io.open(P2, encoding="utf-8").read().splitlines(True)
h0 = len([l for l in H if l.strip()])

pe = [k for k, l in enumerate(H) if l.startswith("| **P4e** | **联网搜索开关 + 来源分区标注**")]
assert len(pe) == 1, pe
nl = "\n" if H[pe[0]].endswith("\n") else ""
H[pe[0]] = (
    "| **P4e** | **联网搜索开关 + 本地/联网来源分区 + S1 流式收口 + S2 尺子与可审计性** | "
    "**✅ DONE —— 全部合并 `master` `5705830`**(2026-10-01;C0 两条第 2 回 ✅、主体+S1 第 1 回 ❌ 打回 → S2 第 2 回 ✅)。"
    "基线 **v2.4 / 55 用例**:canonical 档 **55/55 退出码 0**、默认档 54/55(两档都如实入库;`ss-03` 需服务端带 "
    "`NOVA_GROUNDING_STREAM_FORCE_UNGROUNDED=1`,报告现在有 `env_flags` 可自证配置 + 逐用例 `grounding_gate` 记账)。"
    "**联网只在本地拒答后作补充通道(本地有据不出网)**;来源分区显示真实 URL、`site_name` 由 netloc 推导并标明、"
    "**不绑定逐句 `[W]`**、整段级「未经本校核实」由代码注入;出网请求体实测只有 `model/input/tools/tool_choice`。"
    "S1 早窗恢复真流式(复核方自测 span 2687~5713ms vs 全缓冲 35~56ms,阈值 150 落在分布之外)。"
    "**复核攒下五条遗留转 P4f C0**:🔴 `env_flags.client_env` 收全部 `NOVA*` 而报告要入库(密钥进 git 的形状)/ "
    "grounding 闸门被套在种植轮(命中 16、重生失败 14、`final` 从未命中)/ web 超时实为 httpx idle 语义 / "
    "起服务脚本 `kill` 杀不掉 Windows 进程(实测 :8936 打印 shutting down 后仍监听)/ 改问句未升 version** |\n"
) + nl
log.append("HANDOFF 台账 P4e -> DONE")

if not any(l.startswith("| **P4f** |") for l in H):
    row = ("| **P4f** | **辅导员 persona 定制 + 左侧会话栏重构**(+ **C0 前置收口五条**) | "
           "**🚀 已下发(持棒 WorkBuddy,2026-10-01)**,分支 `task/P4f-persona`,"
           "规格 `docs/TASKS.md` P4f,开单指令 `docs/p4f/workbuddy-order.md`,设计 `docs/P4.md` M8。"
           "**红线:防幻觉规则 1-9 硬编码在模板里,persona 段不得覆盖或削弱(要有注入攻击用例真判红);"
           "persona 不得提权(绑定库仍受 RBAC 交集、越权静默忽略、空 scope 不回落)** |\n")
    pf = [k for k, l in enumerate(H) if l.startswith("| T7 | 向量库 sqlite → sqlite-vec")]
    assert len(pf) == 1, pf
    H.insert(pf[0], row)
    log.append("HANDOFF 插入 P4f 台账行")

h1 = len([l for l in H if l.strip()])
assert h1 >= h0
io.open(P2, "w", encoding="utf-8", newline="").write("".join(H))
log.append("HANDOFF non-blank %d -> %d" % (h0, h1))

P3 = "docs/NEXT_SESSION_PROMPT.md"
N = io.open(P3, encoding="utf-8").read().splitlines(True)
n = [k for k, l in enumerate(N) if "**你要做的下一个动作**" in l]
assert len(n) == 1
nl3 = "\n" if N[n[0]].endswith("\n") else ""
N[n[0]] = (
    "**你要做的下一个动作**：**等 WorkBuddy 交回「P4f 辅导员 persona + C0 五条收口」**"
    "（分支 `task/P4f-persona`，规格 `docs/TASKS.md` P4f，开单指令 `docs/p4f/workbuddy-order.md`）。"
    "**P4e 已整体合并 `master` `5705830`**（2026-10-01：联网开关 + 本地/联网来源分区 + S1 流式恢复 + S2 尺子与可审计性），"
    "基线 **v2.4 / 55 用例**；⚠ **canonical 命令必须带 `NOVA_GROUNDING_STREAM_FORCE_UNGROUNDED=1`**"
    "（`ss-03` 靠它必然命中；不带钩子是 54/55、退出码 1，两档结果都已如实入库），"
    "**现在每份报告自带 `env_flags` 与逐用例 `grounding_gate` → 读报告先看配置再判红绿**（这是坑 57/63 的制度化）。"
    "**P4f 复核五把尺**：① C0-① 密钥形状——`client_env` 改白名单且配一条能判红的单测（同时断言白名单项确实在，"
    "防「过滤过头变空集」假通过，坑 45）；② C0-③ 闸门作用域——种植轮命中必须归零且 `qa-17`/`ss-03` 兜底不回退，"
    "**不许用「长度<30 字」这类阈值糊过去**（判据要可解释）；③ persona 不得削弱防幻觉——"
    "「忽略以上规则」类注入攻击用例必须真判红；④ persona 不得提权——绑定库仍受 RBAC 交集、越权静默忽略、"
    "空 scope 不回落，沿用 P4c 那五条安全探针口径自己复验；⑤ C0-⑤ 起服务脚本收尾要打印 `[port-check]`，"
    "别再留 Windows 孤儿服务（负责人自己已踩过三次：:8906/:8907、:8923、:8936）。"
    "照例纪律：坑 55 取退出码不接管道、坑 57 整轮前单请求自证、坑 58 只读探针不与整轮并发取数、"
    "坑 56 `badcases.json` 按主键集合比对后还原、坑 63 定阈值前先跑 ≥5 次取分布、"
    "坑 64 硬门控落地前先问「这一轮本来就该有可核查事实吗」。"
) + nl3
io.open(P3, "w", encoding="utf-8", newline="").write("".join(N))
log.append("NEXT_SESSION_PROMPT 下一动作更新")
print(" | ".join(log))
