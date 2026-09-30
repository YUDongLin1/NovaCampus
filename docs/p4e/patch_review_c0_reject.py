# -*- coding: utf-8 -*-
"""P4e C0 第 1 回打回后的文档同步：TASKS 状态/Review 结论/白名单增补 + HANDOFF 数字更正与坑 57-59
+ 在实现方回执下留一条更正注（不改他们的记录，只加注）。串内一律用「」，不用 ASCII 双引号（HANDOFF 坑 4）。"""
import io

log = []


def load(p):
    return io.open(p, encoding="utf-8").read().splitlines(True)


def find(lines, sub, expect=1):
    idx = [i for i, l in enumerate(lines) if sub in l]
    assert len(idx) == expect, "anchor %r hits %d (expect %d)" % (sub[:32], len(idx), expect)
    return idx[0]


def patch(lines, sub, old, new):
    i = find(lines, sub)
    assert old in lines[i], "fragment missing on line %d: %r" % (i + 1, old[:32])
    lines[i] = lines[i].replace(old, new, 1)
    log.append("patched line %d" % (i + 1))


# ---------------- TASKS.md ----------------
T = load("docs/TASKS.md")

# 持棒头部整行重写（保留实现方写下的事实，换成第 1 回打回结论）
i = find(T, "> **当前持棒：Qoder**（**P4d 已合并 `master`**")
nl = "\n" if T[i].endswith("\n") else ""
T[i] = ("> **当前持棒：WorkBuddy**（**P4d 已合并 `master`**，2026-09-30 第二回 Review 通过；"
        "**P4e 的 C0 第 1 回复核 = ❌ 打回**（分支 `task/P4e-web-search`，commit `0d50e31`+`b2db785`，**未合并 master**）。"
        "**C0-① 达标**：我自己起 :8904 显式 `--base` 端到端复验，`qa-12` sources=4 且第 4 条正是 "
        "`EVAL-研究生奖学金评定办法`，我独立跑的整轮 **48/48、退出码 0**（`reports/eval_report_20260930_215743.json`）。"
        "`cases.json` 已升 **v2.2 / 48 用例**（`FUSION_TOP_K` 8→12 属**检索行为变更**，与 v2.1 的 8 槽口径不可直接比较，"
        "记账见 `docs/EVAL_BASELINE.md` §十七）。**打回的是 C0-② 的三条必改 + `qa-17` 裁决落地**："
        "① 共现段仍含 `录取通知书`（实测 student 可见 5 块、与「证明」同句共现于助学贷款办法）→ 必然假红；"
        "② 共现段词频无证据且代码注释把它写成「零命中处置词」（事实错误）；"
        "③ `len(pair)<2` 静默跳过；④ `qa-17` 我已裁决 = 生成出口加**确定性闸门**（禁止放宽判据）。"
        "打回指令 `docs/p4e/workbuddy-reject-order.md`，Review 结论见 `docs/TASKS.md` 同名小节。"
        "**负责人自认两条错**：「证明 44 块」应为 42（坑 58）、开单示例没带 `--base` 害实现方白跑六轮整轮评测（坑 57）。"
        "**P4e 主体暂缓**，等 C0 第 2 回交回后下发增补规格（引用语义已定稿「分区展示 + 整体级标注」）")
T[i] = T[i] + nl
log.append("line %d (持棒 header) rewritten" % (i + 1))

p4e_i = find(T, "### P4e 联网搜索开关 + 来源分区标注 + **C0 前置收口两条**")
for mark_old, mark_new in (
    ("🚀 **已下发**", "🟡 **进行中（C0 第 1 回 Review ❌ 打回**（原 🚀 已下发"),
    ("🔶 **IN_REVIEW", "❌ 打回**（原 🔶 IN_REVIEW"),
):
    if mark_old in T[p4e_i]:
        T[p4e_i] = T[p4e_i].replace(mark_old, mark_new, 1)
assert "❌ 打回" in T[p4e_i], "P4e header status marker unexpected: %r" % T[p4e_i][:80]
log.append("P4e header marked 第 1 回打回")

p4f_i = [j for j in range(p4e_i + 1, len(T)) if T[j].startswith("### P4f ")]
assert p4f_i, "P4f header not found"
_window = [j for j in range(p4e_i, p4f_i[0]) if T[j].startswith("- **禁改**：`sims/**`")]
assert len(_window) == 1, "P4e 禁改 anchor hits %d" % len(_window)
i = _window[0]
T[i] = T[i].rstrip("\n") + (
    "\n  - **⚠ 白名单增补（2026-09-30 第 1 回 Review，责任在负责人）**：本单再允许改 "
    "`docs/p4d/**`（`probe_ruler_selftest.py` 与 `run_with_server.sh`——前者是 C0-② 要求它改的却没进白名单，"
    "后者是 `--base` 自检要落的文件）与 `novaagent/tests/smoke_test.py` 的 `--base` 参数化。"
    "原始规格的这两处缺口由 Qoder 负责，不计入实现方越界。\n"
)
log.append("whitelist augmented")

REVIEW = (
    "\n#### Review 结论（Qoder，2026-09-30 C0 第 1 回）——❌ **打回**"
    "（范围窄：C0-① 已达标，卡在 C0-② 的 3 条 + `qa-17` 裁决）\n"
    "\n"
    "**我这次自己跑的（全部实测，命令与产物已入库）**\n"
    "\n"
    "| 复核动作 | 结果 |\n|---|---|\n"
    "| 边界 `git diff --numstat master..HEAD` | 22 文件；`refusal.py`/`faithfulness.py`/`config.py`/`main.py`/`web/**` **0 变更**；"
    "`RERANK_MIN_SCORE` 实测 **0.3**（config 与 rag 别名两处） |\n"
    "| **端口自证**：我自己起 `:8904` 并显式 `--base` | `qa-12` 端到端 **sources=4，第 4 条 = `EVAL-研究生奖学金评定办法`**，"
    "答案带 `[4]` 并复述「平均绩点不低于 3.5」→ **C0-① 是真修，不是改绿** |\n"
    "| **整轮评测独立复跑** | **48/48、退出码 0**、R@k 1.0、忠实度 0.9167、拒答 1.0、隔离 41 会话全量 ok "
    "（`reports/eval_report_20260930_215743.json`） |\n"
    "| rag 层 8/12 槽 A/B（`docs/p4e/review_fusion_gate.py`） | `refusal_indomain` 6 条 + `qa-12`/`qa-17`/`rewrite-01`/`rewrite-02` "
    "的 **`n_above_threshold` 与来源数逐条相同**（实现方证据没记这个门控变量，我补测了） |\n"
    "| `录取通知书` 词频实测 | student 可见块 **5 块**；与「证明」**同句**共现于《国家助学贷款实施办法》第十一条、第十七条 |\n"
    "| 尺子自测复跑 | `probe_ruler_selftest.py` 32 条断言全过、退出码 0；**但没有一条校验共现段词的零命中性** |\n"
    "| KB 残留自查与清理 | 我的冒烟副本中途失败，在库里留了残留（69/491）；已按 API 删净，"
    "`kb_doctor` 回到 **65 / 487、danger 0** |\n"
    "\n"
    "**必改四条（详见 `docs/p4e/workbuddy-reject-order.md`）**\n"
    "\n"
    "1. **M1**：共现段删 `录取通知书`，并把共现判据从「整篇两词都在」改成**窗口邻近**。"
    "现状会让据实引用助学贷款条款的正常答案被判「夹带无据断言」——**这就是坑 54 在改进后的断言里复发**，"
    "而它恰恰是 C0-② 要消除的那类缺陷。\n"
    "2. **M2**：共现段每个词纳入同一把零命中计数尺子并落盘；同时改掉 `run_evals.py` 注释与回执里"
    "「共现词一律取零命中的处置动词」这句**与实测不符的事实陈述**（错在代码注释里最危险，后人会当依据）。\n"
    "3. **M3**：`len(pair) < 2 → continue` 改为显式 `raise`，并补 `all(len(p) >= 2 and p[1] ...)` 断言（坑 45/52）。\n"
    "4. **M4（裁决 `qa-17`）**：**不选 A（放宽判据）**——两次 FAIL 样本（41 字 / 156 字，零 `[n]` 零数字）确实是真非答案。"
    "**选 B 的代码化版本**：按本项目铁律「判定放代码不放 prompt」（P4a C1 / 坑 21），在生成出口加确定性闸门"
    "（`sources 非空` 且答案既无 `[n]` 又无数字 → 一次带硬约束重生；仍不合格 → 写 trace flag + badcase，"
    "评测照旧判红，不许静默兜底）。验收 = `qa-17` 连测 ≥10 次 FAIL=0 + 整轮 48/48 且退出码 0 + 拒答面零回退。\n"
    "\n"
    "**责任在我身上的两条（已写进 HANDOFF 坑 57/58）**\n"
    "\n"
    "- **「证明 44 块」是错的，稳定值 42**。我把只读探针与自己那一轮整轮评测**并发**跑，"
    "取到的是 `seed_corpus_if_needed` 正在塞种子文档的 **70 篇**中间态"
    "（我自己的输出第一行就印着「全库文档 = 70」，异常信号摆在眼前却没停手——按纪律这是硬停项，我违反了）。"
    "错误数值被写进 HANDOFF / TASKS / EVAL_BASELINE 三处，并被实现方回执继承。"
    "实现方代码注释写的 42 才是对的。\n"
    "- 我在开单指令里给的 `bash docs/p4d/run_with_server.sh 8902 ../evals/run_evals.py` **没带 `--base`**，"
    "而 `run_evals.py` 的 `BASE` 默认 `:8900` → 实现方**六轮整轮评测全打在他人 15:40 起的 8 槽旧实例上**。"
    "根因是它自己查出来的（`docs/p4e/evidence/QA12_E2E_DISCREPANCY.md` §一），"
    "它给的「整轮前先做一次单请求端到端自证，看 trace 里有没有本次新增字段」我提为通用验收纪律。\n"
    "\n"
    "**已成立、不必重做**：C0-① 融合层扩槽位（纯加法）、矩阵 8/8、延迟量化（954.9→1121.4 ms 中位，+17.4%）、"
    "`badcases.json` 集合比对后还原、`rag.py:19` 重复常量清除、主体未开工与硬停判断（我实测四入口确认）。\n"
)
T.insert(p4e_i, REVIEW)   # 放在 C0 交回回执之后、P4e 规格之前
log.append("C0 review conclusion inserted")

io.open("docs/TASKS.md", "w", encoding="utf-8", newline="").write("".join(T))

# ---------------- HANDOFF.md ----------------
H = load("HANDOFF.md")
nb0 = len([l for l in H if l.strip()])
cnt = 0
for i, l in enumerate(H):
    if "44 块" in l:
        H[i] = l.replace("44 块", "42 块（负责人第 1 版误记为 44，错因见坑 58）")
        cnt += 1
log.append("HANDOFF 44->42 in %d line(s)" % cnt)

patch(H, "**下一步 = 等 WorkBuddy 交回 P4e**",
      "**下一步 = 等 WorkBuddy 交回 P4e**",
      "**P4e 的 C0 第 1 回 Review = ❌ 打回（2026-09-30，范围窄）**：C0-① 我已端到端复验通过"
      "（自起 :8904 显式 --base，qa-12 sources=4 且第 4 条就是 doc9，整轮 48/48 退出码 0）；"
      "打回原因是我列的第 1 条必改没做（共现段仍含 `录取通知书`，实测 student 可见 5 块且与「证明」同句共现）、"
      "共现段词频无证据、`len(pair)<2` 静默跳过未修，以及 `qa-17` 的裁决要落地"
      "（我裁决 = 生成出口加确定性闸门，禁止放宽判据）。打回指令 `docs/p4e/workbuddy-reject-order.md`。"
      "**我自己的两条错误已认**：「证明 44 块」错（稳定值 42，坑 58）、"
      "开单示例没带 `--base` 害它白跑六轮（坑 57）。**下一步 = 等 WorkBuddy 交回 C0 第 2 回**")

PITS = (
    "57. **开单指令里的命令示例本身也会坑人——`--base` 没写进示例，实现方就白跑了六轮整轮评测**"
    "(2026-09-30 P4e C0)：我在 P4d 写的 `docs/p4d/run_with_server.sh` 只透传 `\"$@\"`，"
    "而 `evals/run_evals.py` 的 `BASE` 是**模块级默认 `http://127.0.0.1:8900`**；"
    "我给它的示例是 `bash docs/p4d/run_with_server.sh 8902 ../evals/run_evals.py`（没带 `--base`）→ "
    "它起了 8902 新实例、评测却全程打在别人 15:40 起的 8 槽旧实例上，连续 6 轮 47/48，"
    "**极易被误读成「修法无效」而去改用例**（那就是把真修成假）。根因是实现方自己查出来的，"
    "它给的流程纪律我已采纳为通用验收项：**整轮评测前先做一次单请求端到端自证，"
    "看响应/trace 里有没有本次新增的字段——缺字段＝连的是旧代码**。"
    "同源二次实证（负责人自己踩）：我今天把 `smoke_test.py` 的 BASE 改成 :8905，"
    "结果 [16a] 判红（期望 `deny_url`、实得 `index_page`）——因为 `main.py:318 DENY_URLS` 里写死了 "
    "`http://127.0.0.1:8900/`，**「自家前端禁抓」这条防线是端口绑定的**，换端口即失效。"
    "铁律：① 任何「起服务 + 打服务」的脚本，**目标地址必须显式参数化并写进示例**；"
    "② 断言与安全防线不能绑死端口字面量；③ 别人的六轮数据和我的轮次矛盾时，"
    "**先怀疑连的是不是同一个进程**（与坑 37「health=200 不证明是谁起的」同源）。\n"
    "58. **只读探针绝不能与整轮评测并发取数——我因此把一个错数写进了三份文档**(2026-09-30 P4e C0)："
    "我在评测跑着的时候并行执行 `docs/p4d/review_rind07_premise.py`，读到的是 "
    "`seed_corpus_if_needed` **正在往库里塞种子文档的中间态**（我自己的输出就印着「全库文档 = 70」，"
    "而基线是 65——**异常信号出现在我眼前，我没停手**），于是把「证明 44 块」写进了 "
    "HANDOFF / TASKS / EVAL_BASELINE，并被实现方回执继承。实现方代码注释写的 **42** 才是稳定值。"
    "**这是「看见矛盾不硬停」的代价：错误会被下游全部文档继承。**"
    "铁律：① 读库计数**必须等评测/冒烟结束、`kb_doctor` 回到基线（65/487）再测**，或者干脆串行；"
    "② 探针要把看到的**总量印在第一行**（我印了，但印在结论后面，等于没印）；"
    "③ 与坑 33「取到非空才落盘」并列：**取到「干净状态」才落盘**。\n"
    "59. **修「必然假红的宽词」时，新引入的词必须过同一把尺子，否则缺陷在改进里复发**"
    "(2026-09-30 P4e C0 第 1 回)：C0-② 把 `证明/录取` 从无条件段挪进共现段，"
    "但共现段的上下文词里塞了 `录取通知书`（实测 student 可见 **5 块**，且与「证明」**同句**共现于"
    "《国家助学贷款实施办法》第十一条「可提交录取通知书；…有效身份证明」、"
    "第十七条「在线提交录取通知书、身份证等相关证明资料」），而共现判据是**整篇答案两词都在**、"
    "不是同句邻近 → 据实引用该条款的正常答案会被判「夹带无据断言」。**坑 54 在它的修复里复发了**。"
    "而自测 32 条全绿——因为它只校验无条件段的零命中性，从没校验共现段。"
    "铁律：① **「改进后的断言」要和原断言一起被同一把尺子重测**，不能只测新逻辑的正例；"
    "② 凡「某词出现即违规」的判据，词的库内频次是**入单前置条件**，无条件段与共现段两侧都要查；"
    "③ 邻近语义要显式定义（同句 / ≤N 字窗口）——「两词都在整篇里」几乎等价于无条件判违规，"
    "只是把假红概率往后挪了一层。\n"
)
p = find(H, "56. **运行时会被测方写脏 git 跟踪文件")
H.insert(p + 1, PITS)
log.append("HANDOFF pits 57/58/59 inserted")

body = "".join(H)
nb1 = len([l for l in body.splitlines() if l.strip()])
assert nb1 > nb0, "content shrank"
io.open("HANDOFF.md", "w", encoding="utf-8", newline="").write(body)

# ---------------- 实现方回执下的更正注 ----------------
A = load("docs/EVAL_BASELINE.md")
i = find(A, "**唯一遗留（上交裁决，未自行拍板）**")
A.insert(i, "> **⚠ 负责人复核注（2026-09-30）**：本节出现的「`证明` 44 块」沿用负责人错误数值，"
             "稳定实测值为 **42**（错因＝只读探针与整轮评测并发，取到 70 篇中间态，HANDOFF 坑 58）。"
             "实现方代码注释里的 42 是正确的。裁决与新口径见 `docs/TASKS.md`"
             "「Review 结论（Qoder，2026-09-30 C0 第 1 回）」与 `docs/p4e/workbuddy-reject-order.md`。\n\n")
io.open("docs/EVAL_BASELINE.md", "w", encoding="utf-8", newline="").write("".join(A))
log.append("EVAL_BASELINE correction note inserted")

print("\n".join(log))
