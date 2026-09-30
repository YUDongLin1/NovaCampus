# -*- coding: utf-8 -*-
"""P4e C0 第 2 回 Review 结论写入 TASKS.md（持棒头部 + 结论段）。串内用「」防 ASCII 引号（坑 4）。"""
import io

P = "docs/TASKS.md"
T = io.open(P, encoding="utf-8").read().splitlines(True)
log = []
nb0 = len([l for l in T if l.strip()])


def find(sub, expect=1, lo=0, hi=None):
    hi = hi or len(T)
    idx = [i for i in range(lo, hi) if sub in T[i]]
    assert len(idx) == expect, "anchor %r hits %d" % (sub[:30], len(idx))
    return idx[0]


# 1) 持棒头部整行重写
i = find("> **当前持棒：Qoder**（**P4d 已合并 `master`**")
nl = "\n" if T[i].endswith("\n") else ""
T[i] = ("> **当前持棒：Qoder**（**P4e 的 C0 两条第 2 回 Review = ✅ 通过，已合并 `master`**"
        "（分支 `task/P4e-web-search`，提交 `06d735a`(M1~M4) + `ff02688`(M5) + 记账 `1c24ff9`/`997089d`）。"
        "**基线 v2.3 / 48 用例、满通过**：我独立整轮 **48/48、退出码 0**、R@k 1.0、忠实度 0.9444、拒答 1.0、"
        "隔离 41 会话 ok（`reports/eval_report_20260930_230033.json`），冒烟 `--base` 打我自己的 :8910 "
        "**exit 0 / 65→65**。⚠ **v2.1 及以前的 R@k/TTFD 是 8 槽口径，与 v2.2+ 不可直接比较**。"
        "**合并时发现一条新的产品级代价（见下方 Review 结论 §新增发现）**：M4 的 grounding 闸门把流式路径改成"
        "**整段缓冲后下发**，我实测 TTFB 2365ms / E2E 2401ms（12 个 delta 挤在 36ms 里）——"
        "**真流式事实上被关掉，且评测与冒烟都不走 `/api/chat/stream`，全绿对它零证明力**（坑 60）。"
        "处置待用户拍板；**P4e 主体仍暂缓**。")
T[i] = T[i] + nl
log.append("持棒 header rewritten (line %d)" % (i + 1))

# 2) P4e 条目标题状态
p4e_i = find("### P4e 联网搜索开关 + 来源分区标注 + **C0 前置收口两条**")
for old_mark, new_mark in (
    ("🔶 **IN_REVIEW**", "✅ **C0 第 2 回 Review 通过并合并 `master`**（🔶 IN_REVIEW"),
    ("❌ 打回", "✅ 第 2 回通过并合并"),
):
    if old_mark in T[p4e_i]:
        T[p4e_i] = T[p4e_i].replace(old_mark, new_mark, 1)
assert "✅" in T[p4e_i], "P4e header not updated: %r" % T[p4e_i][:80]
log.append("P4e header marked 第 2 回通过")

CONCLUSION = (
    "\n#### Review 结论（Qoder，2026-09-30 深夜 C0 第 2 回）——✅ **通过并合并 `master`**\n"
    "\n"
    "**第 1 回四条必改逐条独立复验（我这次自己跑的，不采信回执）**\n"
    "\n"
    "| 项 | 我的验证动作 | 结论 |\n"
    "|---|---|---|\n"
    "| M1 共现段去宽词 + 邻近判据 | 自己数库：`录取通知书` student 可见 **5 块**（已在 cases.json 共现段删除）；"
    "读 `_cooccur_near`（同句优先 + 首现距离 ≤80 字兜底）；跑尺子自测 **44 条断言全过、退出码 0**，"
    "其中含我上轮点名的 (a)(b) 两条判例与他们自己加的 (c)「邻近但非同句也必须 FAIL」 | ✅ 成立，"
    "且 (c) 锁住了「窗口」这一侧——否则同句实现退化成整篇判据也测不出来 |\n"
    "| M2 共现段词频进证据 | `probe_rind07_kw.py` 改为**从 cases.json 读实际生效的断言**（不再自带词表），"
    "自测里新增两条「实测库」断言 + 一条显式锁死「录取通知书不得作共现词（实测 5 块）」；"
    "`run_evals.py` 注释里那句错的事实陈述已改准 | ✅ 成立，且「尺子与被测物各写一份词表」这个根因被拔掉了 |\n"
    "| M3 畸形对不许静默跳过 | 读 `raise` 分支；自测 **5 条 raise 判例 + 1 条结构正确不得 raise** 的反向判例，"
    "全部真的影响退出码 | ✅ 成立（坑 45/52 闭合） |\n"
    "| M4 生成出口确定性闸门 | 我自己在 :8910 连打 6 次 qa-17：**闸门命中 4 次、4 次重生后全部合格**"
    "（`answer_is_grounded` 与评测侧同一把尺子 `_FACTUAL`、刻意不判长度），"
    "另确认它接在 `strip_invalid_refs` **之后**、拒答路径不经本闸门（他们的反向探针 `gate_present=False` 我也复现了）；"
    "禁改项 `refusal.py` 全程 **0 变更** | ✅ 成立，且代码路径被真实执行过（不是「恰好没抽到」） |\n"
    "| M5 端口绑定与 `--base` | 冒烟用新加的 `--base` 打我的 :8910 → **exit 0**，且 [16a] 自家前端判回 "
    "`deny_url`（修复前是 `index_page`）；读 `_runtime_deny_origins`——`quality_gate_reject` 仍是纯函数、"
    "默认参数下行为逐字一致；他们把自己第一版「try/except 吞异常导致安全判定静默失效」的过程留了档 | ✅ 成立 |\n"
    "| 边界与常量 | `git diff --numstat master..HEAD -- refusal.py faithfulness.py web/**` **空**；"
    "`RERANK_MIN_SCORE=0.3`、`MAX_PER_DOC=2`、`FINAL_TOP_K=7` 均未动；`FUSION_TOP_K` 只此一处定义 | ✅ |\n"
    "| 取证纪律 | `badcases.json` 又被我的整轮写脏（3 增 3 删、case id 集合不变）→ 按主键集合比对后 `git checkout --` 还原、"
    "未入库（坑 56） | ✅ |\n"
    "\n"
    "**新增发现（合并后第一优先级，不是本次交付的缺陷而是我裁决时的遗漏）**\n"
    "\n"
    "**流式真流被 M4 的缓冲关掉了，而全项目没有任何自动化覆盖那条路径。**"
    "实测：`/api/chat/stream` 上 TTFB **2365 ms** / E2E **2401 ms** → 12 个 delta 全挤在最后 **36 ms** 下发；"
    "对照 P4d 记录的基线（`latency_compare.txt`）：检索路径 TTFD 2161 / E2E 2898（渐进窗口 737ms）、"
    "改写路径 3778 / 5440（窗口 1662ms）→ **渐进显示归零**。"
    "更关键的是：`evals/run_evals.py` 与 `smoke_test.py` **只打 `/api/chat`**，前端才走 `/api/chat/stream`"
    "（`grep -rn 'chat/stream' evals/ novaagent/tests/` = **0 命中**）→ 我这轮 48/48 与冒烟 exit 0 "
    "**对用户体验的改动没有任何证明力**。这是坑 46「两条路径矛盾时先信更接近用户的那条」的反面：这次连那条路径都没测。"
    "责任在我：第 1 回裁决只想了判据，没量化流式代价。\n"
    "\n"
    "建议的修法（待用户拍板优先级）：**早窗提交**——放行到出现首个 `[n]`/数字或前 N 字为止，之后照常流式；"
    "整段生成完仍无据才重生。这样缓冲窗口压到一两句，闸门与流式都保住。"
    "同时必须补一条走 `/api/chat/stream` 的评测/冒烟用例（断言 SSE 事件序列 `sources → context → delta* → done`、"
    "delta 数量 > 1、以及闸门命中时的行为）。\n"
    "\n"
    "**两处交接事实的更正（都在我的账上）**：① 我第 1 回写的「证明 44 块」错，稳定值 **42**，"
    "已在 HANDOFF/EVAL_BASELINE 全项目更正并记坑 58；② 我用 Git Bash `kill <Windows PID>` 没能杀掉自己的 "
    ":8906/:8907 实例（MSYS PID 与 Windows PID 不是一回事，命令返回成功而端口仍在听），"
    "是 WorkBuddy 用 `Get-NetTCPConnection` 复查后清掉并如实记了 `997089d` —— 记坑 61。\n"
)
k = find("#### Review 结论（Qoder，2026-09-30 C0 第 1 回）——❌ **打回**")
T.insert(k, CONCLUSION)
log.append("第 2 回 Review 结论 inserted")

body = "".join(T)
nb1 = len([l for l in body.splitlines() if l.strip()])
assert nb1 > nb0
io.open(P, "w", encoding="utf-8", newline="").write(body)
print(" | ".join(log), "| non-blank %d -> %d" % (nb0, nb1))
