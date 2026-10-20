# -*- coding: utf-8 -*-
"""P4e C0 第 2 回通过后的文档同步：HANDOFF 基线行升 v2.3 + 台账 + 坑 60/61。串内用「」防 ASCII 引号（坑 4）。"""
import io

P = "HANDOFF.md"
lines = io.open(P, encoding="utf-8").read().splitlines(True)
log = []
nb0 = len([l for l in lines if l.strip()])


def find(sub, expect=1):
    idx = [i for i, l in enumerate(lines) if sub in l]
    assert len(idx) == expect, "anchor %r hits %d" % (sub[:30], len(idx))
    return idx[0]


def patch_line(sub, old, new):
    i = find(sub)
    assert old in lines[i], "fragment missing line %d: %r" % (i + 1, old[:30])
    lines[i] = lines[i].replace(old, new, 1)
    log.append("line %d" % (i + 1))


# 1) 顶部日期行
patch_line("供**零上下文新会话**接续",
           "供**零上下文新会话**接续",
           "**2026-09-30 深夜由 Qoder 更新:P4e 的 C0 两条(第 2 回)Review 通过并合并 `master`,"
           "基线升 **v2.3 / 48 用例**(含生成出口 grounding 闸门);**P4e 主体仍暂缓**,待负责人对"
           "「流式被缓冲」的处置拍板**;供**零上下文新会话**接续")

# 2) 评测基线行:整行前缀替换为 v2.3 口径(v2.2/v2.1 历史保留在后续文字里)
patch_line("| **评测基线** | **v2.1(2026-09-30 P4d-fix 后,当前对照口径)**",
           "| **评测基线** | **v2.1(2026-09-30 P4d-fix 后,当前对照口径)**",
           "| **评测基线** | **v2.3(2026-09-30 P4e C0 第 2 回后,当前对照口径)**:**48 用例**;⚠ **v2.2→v2.3 是断言口径变更**"
           "(共现判据改**窗口邻近**、共现词全部实测零命中);⚠ **v2.1→v2.2 是检索行为变更**(`FUSION_TOP_K` 8→12),"
           "**v2.1 及以前的 R@k/TTFD 均在 8 槽下测得,与 v2.2+ 不可直接比较**;**v2.2 起 `qa-12` 不再是红、基线回到满通过**;"
           "**新增生成出口 `grounding` 闸门**(有来源却零 `[n]` 零数字 → 重生一次;复核方实测 qa-17 连 6 次命中 4 次、"
           "重生后全部合格)。以下为 v2.2/v2.1 历史口径(保留):v2.1(2026-09-30 P4d-fix 后")

# 3) 台账 P4e 行:状态更新
patch_line("| **P4e** | **联网搜索开关 + 来源分区标注**(+ **C0 前置收口两条**) |",
           "**🚀 已下发(持棒 WorkBuddy,2026-09-30)**",
           "**🟡 进行中 —— C0 两条已 Review 通过并合并 `master`(第 2 回,2026-09-30 深夜);"
           "主体暂缓(协议契约硬停已确认),待「流式被缓冲」处置拍板**。持棒 WorkBuddy")

# 4) 坑 60/61
PITS = (
    "60. **评测打的端点≠用户走的端点——改了用户可感知的路径,48/48 会对它一声不吭"
    "(2026-09-30 复核 P4e M4 时发现)**:`evals/run_evals.py` 与 `novaagent/tests/smoke_test.py` 全程只打 "
    "`/api/chat`(非流式),而前端 `web/js/chat.js` 走的是 `/api/chat/stream`(SSE:`sources → context → delta* → done`)。"
    "M4 的 grounding 闸门**同时改了流式路径的实现方式**(delta 先缓冲、判完闸门再下发),"
    "而我这轮独立复跑的 48/48 与冒烟 exit 0 **一条都没经过那条路径**——"
    "「全绿」在这里对用户体验没有任何证明力。我自己实测出来的代价:"
    "**首字 TTFB 2365 ms、E2E 2401 ms,即 12 个 delta 全挤在最后 36 ms 里下发**;"
    "对照 P4d 记录(`docs/p4d/evidence/after/latency_compare.txt`):检索路径 TTFD 2161 / E2E 2898(窗口 737ms)、"
    "改写路径 3778 / 5440(窗口 1662ms)→ **渐进显示几乎归零,真流式事实上被关掉了**"
    "(TTFB 没变差,变差的是「一点点往外冒字」这个体验和它的可感知等待)。"
    "铁律:① **凡改动用户可感知路径的改动,必须至少有一条断言真的走那条路径**——"
    "否则要么补 `stream` 型用例,要么在回执里显式声明「该路径无自动化覆盖」;"
    "② 判据正确性闸门与流式体验不是二选一:可做**早窗提交**(先放行到出现首个 `[n]`/数字或前 N 字为止,"
    "之后照常流式;整段生成完仍无据才重生),把缓冲窗口压到一两句;"
    "③ 我此前给的「闸门接在 `strip_invalid_refs` 之后、不静默兜底」是对的,"
    "但我在裁决时**只考虑了判据、没量化流式代价**,这是裁决不完整。\n"
    "61. **Git Bash 里 `kill <Windows PID>` 杀不掉 psutil 报出来的进程——我因此留了两个孤儿服务"
    "(2026-09-30)**:我用 `psutil` 找到 :8906/:8907 的监听 PID(33580/39800),再在 Git Bash 里 `kill $PID`,"
    "命令**返回成功、端口却仍在听**(MSYS 的 PID 命名空间与 Windows PID 不是一回事)。"
    "后果是别人接手时看到两个来源不明的存活实例——这正是坑 37 教过的「health=200 不证明是谁起的」的再演。"
    "最后是 WorkBuddy 用 `Get-NetTCPConnection` 复查后 `Stop-Process` 清掉并如实记了 commit `997089d`。"
    "铁律:① Windows 上终止进程用 `taskkill //PID <pid> //F`(Git Bash 里双斜杠)或 "
    "`psutil.Process(pid).terminate()`,**不要用 MSYS `kill` 打 Windows PID**;② 杀完必须**复查端口**再写交接,"
    "不要把「命令退出码 0」当「进程已死」。\n"
)
p = find("59. **修「必然假红的宽词」时")
lines.insert(p + 1, PITS)
log.append("pits 60/61 inserted")

body = "".join(lines)
nb1 = len([l for l in body.splitlines() if l.strip()])
assert nb1 > nb0
io.open(P, "w", encoding="utf-8", newline="").write(body)
print(" | ".join(log), "| non-blank %d -> %d" % (nb0, nb1))
