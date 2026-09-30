# -*- coding: utf-8 -*-
"""续跑：TASKS 已改完，这里只做 HANDOFF(台账 P4e 行/下一步/坑 62) 与 NEXT_SESSION_PROMPT。"""
import io

log = []

P2 = "HANDOFF.md"
H = io.open(P2, encoding="utf-8").read().splitlines(True)
h0 = len([l for l in H if l.strip()])

i = [k for k, l in enumerate(H) if l.startswith("| **P4e** | **联网搜索开关 + 来源分区标注**")]
assert len(i) == 1, i
old = H[i[0]]
assert "主体暂缓" in old, old[:150]
H[i[0]] = old.replace(
    "主体暂缓(协议契约硬停已确认),待「流式被缓冲」处置拍板**。持棒 WorkBuddy",
    "**主体 + S1 流式收口已下发**(用户 2026-09-30 深夜拍板合在一单)。"
    "持棒 WorkBuddy,分支 `task/P4e-websearch-main`,"
    "开单指令 `docs/p4e/workbuddy-order-main-body.md`。**S1 = M4 缓冲把真流式关掉(坑 60),merge-blocking**",
    1)
log.append("HANDOFF 台账 P4e 行更新")

p = [k for k, l in enumerate(H) if "**下一步 = 等 WorkBuddy 交回 C0 第 2 回**" in l]
assert len(p) == 1, p
H[p[0]] = H[p[0]].replace("**下一步 = 等 WorkBuddy 交回 C0 第 2 回**",
                          "**P4e C0 第 2 回 Review = ✅ 通过并合并 `master` `022b5ef`**(2026-09-30 深夜)。"
                          "M1~M5 逐条独立复验成立:尺子自测 44 条全过且退出码 0、`录取通知书` 已从共现段删除"
                          "(我实测 5 块)、探针改为**从 cases.json 读实际生效断言**(把「尺子与被测物各写一份词表」"
                          "的根因拔掉)、畸形共现对 raise + 6 条判例、**M4 闸门我在 :8910 连打 6 次 qa-17 命中 4 次"
                          "且重生后全部合格**、冒烟用新加的 `--base` 打我自己的端口 exit 0 且 [16a] 回到 deny_url。"
                          "我独立整轮 **48/48、退出码 0**(`reports/eval_report_20260930_230033.json`)、"
                          "合并后再跑冒烟仍 **exit 0 / 65→65**。"
                          "**但合并时发现一条新的产品级代价并已下发修**:M4 为拦空话把 `/api/chat/stream` 改成整段缓冲,"
                          "我实测 TTFB 2365ms/E2E 2401ms、12 个 delta 挤在 36ms 里 → **真流式被关掉**,"
                          "而 `evals/` 与 `novaagent/tests/` 全项目 **0 处**走那条端点 → 全绿对它零证明力(坑 60,"
                          "责任在我裁决时只想了判据没量化流式代价)。"
                          "**下一步 = 等 WorkBuddy 交回「P4e 主体 + S1」**(分支 `task/P4e-websearch-main`;"
                          "S1 是 merge-blocking,必须交**先红后绿两份流式证据 + 三档延迟数字**)")
log.append("HANDOFF 下一步更新")

PITS = (
    "62. **行尾统一已落地：`.gitattributes` 的 `* text=auto eol=lf`**(2026-09-30 深夜,用户拍板)："
    "此前 `core.autocrlf=true` 让同一文件存在 LF/CRLF 两种字节数(坑 36),复核按字节数对账会得到两个都"
    "「看起来对」的值。加完 `.gitattributes` 后跑 `git add --renormalize .` 的结果是 **0 个文件变更**——"
    "因为索引里本来就存 LF,这条只固定检出行为,不产生大规模改写、不污染 blame。"
    "同批清理 4 个已合并的 `task/*` 分支;其中 `task/P3b-aiops-mcp` 被 `git branch -d` 拒绝"
    "(其 tip `b468391` 不是 master 祖先),我先核对内容归属再 `-D`："
    "**master 上的 `d041819` 与它是同一件事的重复提交**(`docs/CASE_STUDY.md` 两边都 144 行;"
    "`evals/query_variant_matrix.py` master 已演进到 154 行,分支是 98 行的早期版)。"
    "铁律：① **「未完全合入」不等于「有独有内容」**——删分支前要按文件比对两边版本与提交来历,不能只看 "
    "`branch -d` 的拒绝信息就强删,也不能因为它拒绝就认定还有东西没拿回来;"
    "② 强删时把**原 tip SHA 与等价提交写进记录**,便于恢复。\n"
)
p61 = [k for k, l in enumerate(H) if l.startswith("61. **Git Bash 里 `kill <Windows PID>`")]
assert len(p61) == 1, p61
H.insert(p61[0] + 1, PITS)
log.append("HANDOFF 坑 62 inserted")

h1 = len([l for l in H if l.strip()])
assert h1 > h0
io.open(P2, "w", encoding="utf-8", newline="").write("".join(H))
log.append("HANDOFF non-blank %d -> %d" % (h0, h1))

P3 = "docs/NEXT_SESSION_PROMPT.md"
N = io.open(P3, encoding="utf-8").read().splitlines(True)
n = [k for k, l in enumerate(N) if "**你要做的下一个动作**" in l]
assert len(n) == 1
nl = "\n" if N[n[0]].endswith("\n") else ""
N[n[0]] = (
    "**你要做的下一个动作**：**等 WorkBuddy 交回「P4e 主体 + S1 流式收口」**"
    "（分支 `task/P4e-websearch-main`，规格 `docs/TASKS.md` P4e，"
    "开单指令 `docs/p4e/workbuddy-order-main-body.md`；P4e 的 C0 两条已于 2026-09-30 深夜 ✅ 合并 `master` "
    "`022b5ef`，基线 **v2.3 / 48 用例满通过**）。**S1 是 merge-blocking，复核四把尺**："
    "① **流式是否真恢复**——要求交「先红后绿」两份证据：先在现有全缓冲实现上证明"
    "「`delta` 事件数 > 1」「TTFB 与 E2E 之差 > 0」这两条断言**确实 FAIL**，再证明修复后 PASS"
    "（坑 39/60：改了用户可感知的路径，就必须至少有一条断言走那条路径）；"
    "② **闸门不得被弱化**——`qa-17` 连打 ≥10 次 FAIL=0，命中时 `grounding_retry` 事件真实出现、"
    "落库的是重生后答案（我实测 6 次命中 4 次，可作对照）；"
    "③ **引用语义不许做成假精确**——联网条目只列真实 URL + netloc 推导站点名 + 整段级「未经本校核实」，"
    "必须有**反向断言禁止逐句 `[W<n>]` 角标**（上游没有任何映射关系，我独立复验过字段只有 `{type,url}`）；"
    "④ **合规红线**：自己读代码追「出网的那个字符串是否只来自用户本轮输入」——"
    "含改写串会不会带语料片段、日志记了哪些字段，这是审代码不是测功能。"
    "照例：坑 17 落盘≠入库、坑 18 claim→字段、坑 39 断言能判红、坑 45 空集假通过、"
    "坑 55 管道吞退出码、坑 56 `badcases.json` 按主键集合比对后还原、坑 57 整轮前做单请求端到端自证、"
    "坑 58 只读探针不与整轮评测并发取数、坑 61 Windows 终止进程用 `taskkill //PID x //F` 或 psutil 并**复查端口**、"
    "坑 62 删分支前先核对内容归属。仓库已统一 `eol=lf`，4 个已合并分支已清理。"
) + nl
io.open(P3, "w", encoding="utf-8", newline="").write("".join(N))
log.append("NEXT_SESSION_PROMPT updated")

print(" | ".join(log))
