# -*- coding: utf-8 -*-
"""P4d 合并后同步 HANDOFF.md（台账/基线行/运行状态/下一步/坑 54-55）。

按行内子串定位 + 断言唯一命中，防止其他会话并行改文档导致锚点漂移（HANDOFF 坑 3）。
"""
import io
import sys

P = "HANDOFF.md"
lines = io.open(P, encoding="utf-8").read().splitlines(True)
report = []


def find(sub, expect=1):
    idx = [i for i, l in enumerate(lines) if sub in l]
    assert len(idx) == expect, "anchor %r hit %d times (expect %d)" % (sub[:30], len(idx), expect)
    return idx[0]


def replace_line(sub, new_text):
    global lines
    i = find(sub)
    old = lines[i]
    lines[i] = new_text + ("\n" if old.endswith("\n") else "")
    report.append("replaced line %d (anchor %r)" % (i + 1, sub[:24]))


def insert_after(sub, block):
    i = find(sub)
    lines.insert(i + 1, block)
    report.append("inserted after line %d (anchor %r)" % (i + 1, sub[:24]))


# ---- 1) 顶部日期行：追加本轮结论 ----
i = find("供**零上下文新会话**接续")
lines[i] = lines[i].replace(
    "供**零上下文新会话**接续",
    "**2026-09-30 由 Qoder 更新:P4d 第二回 Review 通过并合并 `master`(`bb6e78b`),基线 v2.1(48 用例,"
    "合并时**已知 1 红 `qa-12`**——是 ④ 揭出的真实漏召,不是尺子问题),**P4e 已下发(持棒 WorkBuddy),"
    "含 C0 前置收口两条**(`qa-12` 融合层截断漏召 + `rind-07` 宽词断言),见 `docs/TASKS.md` P4e 与 `docs/p4e/workbuddy-order.md**;"
    "供**零上下文新会话**接续",
    1,
)
report.append("header date line updated")

# ---- 2) 运行状态：:8900 实例归属 ----
i = find("venv=`novaagent/.venv`")
lines[i] = lines[i].rstrip("\n") + (
    ";**当前 :8900 实例归属 WorkBuddy**(父进程链 `uvicorn → bash → sandbox-cli → WorkBuddy.exe`,"
    "cwd=主工作树 `novaagent/`,`NOVAAGENT_EVAL_TEMPERATURE=0`)。"
    "**Review 期只读它的端口、不自作主张重启别人的服务**(坑 37);需第二实例请另起端口并用 `run_with_server.sh` 收进同一条命令"
) + "\n"
report.append("运行状态 NovaAgent row updated")

# ---- 3) 评测基线行：补复核方独立轮次与"必须清红"约束 ----
i = find("以下为 v2.0 历史口径(保留)")
lines[i] = lines[i].replace(
    "以下为 v2.0 历史口径(保留)",
    "**复核方(Qoder)独立整轮 `reports/eval_report_20260930_173320.json` = 47/48、R@k 1.0、忠实度 0.9722、"
    "拒答 1.0、隔离 ok(41 会话)——与实现方逐值一致**;但**同一批用例里 `qa-05` 0.5→1.0、`qa-07` 1.0→0.5 互换**,"
    "聚合相同是巧合(judge 抖动第二条实证,见 EVAL_BASELINE §十六 16.2)。"
    "⚠ **合并时基线带 1 个已知红(`qa-12`),P4e 的集中验证必须清回 48/48 且退出码 0**,"
    "否则'退出码非 0'会长期失真成狼来了(坑 39/54)。以下为 v2.0 历史口径(保留)",
    1,
)
report.append("评测基线 row updated")

# ---- 4) 任务台账：P4c / P4d / P4e 三行 ----
new_rows = (
    "| **P4c** | **KB 文件夹 + `@` 指定检索范围 + 学段元数据** | **✅ DONE —— Review 通过并合并 master `5611c16`(2026-09-30),"
    "三条硬约束由自写 5 条安全探针守住,迁移与 db 层在库副本跑到 18/18,基线 v1.9** |\n"
    "| **P4d** | **LangGraph 检索编排 + 查询改写重试**(本系列唯一带硬指标的单) | **✅ DONE —— 第一回 REJECTED(工程侧全过、评测侧 4 条收口),"
    "修复轮 290e287 交回,**第二回独立把关通过并合并 master `bb6e78b`**(2026-09-30)。"
    "硬指标矩阵 3/8→**8/8**、消融退化为 3/8、`RERANK_MIN_SCORE` 未动;基线 **v2.1 / 48 用例,R@k 1.0(口径变更)**,"
    "合并时**已知 1 红 `qa-12`** |\n"
    "| **P4e** | **联网搜索开关 + 来源分区标注**(+ **C0 前置收口两条**) | **🚀 已下发(持棒 WorkBuddy,2026-09-30)**,"
    "规格 `docs/TASKS.md` P4e,开单指令 `docs/p4e/workbuddy-order.md`,设计见 `docs/P4.md` M7。"
    "**红线:联网请求只发当前问题文本**,库内内容/会话历史/学生信息一律不出网 |\n"
)
insert_after("| T7 | 向量库 sqlite → sqlite-vec", new_rows)  # placeholder: insert before via replace below

# 上面那行插到了 T7 之后，这里把它挪到 T7 之前（保持台账顺序 P4c→P4d→P4e→T7）
j = find("| **P4c** | **KB 文件夹 + `@` 指定检索范围 + 学段元数据** | **✅ DONE")
moved = lines.pop(j)
assert moved == new_rows, "row block mismatch"
k = find("| T7 | 向量库 sqlite → sqlite-vec")
lines.insert(k, moved)
report.append("P4c/P4d/P4e ledger rows inserted before T7")

# ---- 5) §五 下一步：把"等 WorkBuddy 修完再交回"换成本轮结论 ----
i = find("**下一步 = 等 WorkBuddy 按 4 条清单修完再交回**")
lines[i] = lines[i].replace(
    "**下一步 = 等 WorkBuddy 按 4 条清单修完再交回**",
    "**P4d-fix 第二回复核=通过并合并 `master` `bb6e78b`**(2026-09-30)。4 条收口逐条独立复验成立:"
    "② 我自跑 `probe_ruler_selftest.py` 21 断言全 OK 且退出码 0;③ `faithfulness.py` 0 变更 + spread 证据字段逐值对上;"
    "④ 非答案检测**只挂 `judge_qa`**(`judge_refusal*` 零调用点,不会把正确拒答打成非答案);① `cases.json` 按 id 语义比对 47→48 零丢失、"
    "`refusal_indomain` 经 `rind-07` 补回仍 6 条。**我这轮集中验证 47/48 与实现方逐值一致**、冒烟 exit 0(不带管道实测)且 65→65。"
    "**复核新增两条(转 P4e C0,不构成本单第二次打回)**:"
    "① `qa-12` 的真实断点**在融合层 `FUSION_TOP_K=8` 截断**(doc9 向量第 6 位、关键词未进 top20、8 个融合槽位被两篇本科生办法占满,"
    "**根本没进 rerank**)——回执写的"未进 top3"字面对但归因偏后,**只动 rerank 阈值修不好**;"
    "② `rind-07` 的"域内无据"我把它从标题层推到**正文/语义层**复验(**成立**:全库"交回/退还/退卡/提档/调档/档案转递"皆 0 块,7 项诉求无一可答,"
    "不是 `rind-02` 那种伪前提),**但 `expect_absent_keywords` 混了宽词**(`证明` 在学生可见块 44 块、`录取` 14 块),"
    "检索一增强就会**必然假红**。"
    "**下一步 = 等 WorkBuddy 交回 P4e**(分支 `task/P4e-web-search`;实现期只做最小检查,全部落地后集中一轮 48/48 + 冒烟)"
) + "\n" if not lines[i].endswith("\n") else lines[i].replace(
    "**下一步 = 等 WorkBuddy 按 4 条清单修完再交回**",
    "**P4d-fix 第二回复核=通过并合并 `master` `bb6e78b`**(2026-09-30)。4 条收口逐条独立复验成立:"
    "② 我自跑 `probe_ruler_selftest.py` 21 断言全 OK 且退出码 0;③ `faithfulness.py` 0 变更 + spread 证据字段逐值对上;"
    "④ 非答案检测**只挂 `judge_qa`**(`judge_refusal*` 零调用点,不会把正确拒答打成非答案);① `cases.json` 按 id 语义比对 47→48 零丢失、"
    "`refusal_indomain` 经 `rind-07` 补回仍 6 条。**我这轮集中验证 47/48 与实现方逐值一致**、冒烟 exit 0(不带管道实测)且 65→65。"
    "**复核新增两条(转 P4e C0,不构成本单第二次打回)**:"
    "① `qa-12` 的真实断点**在融合层 `FUSION_TOP_K=8` 截断**(doc9 向量第 6 位、关键词未进 top20、8 个融合槽位被两篇本科生办法占满,"
    "根本没进 rerank)——回执写的『未进 top3』字面对但归因偏后,**只动 rerank 阈值修不好**;"
    "② `rind-07` 的『域内无据』我把它从标题层推到**正文/语义层**复验(**成立**:全库『交回/退还/退卡/提档/调档/档案转递』皆 0 块,"
    "7 项诉求无一可答,不是 `rind-02` 那种伪前提),**但 `expect_absent_keywords` 混了宽词**"
    "(`证明` 在学生可见块 44 块、`录取` 14 块),检索一增强就会**必然假红**。"
    "**下一步 = 等 WorkBuddy 交回 P4e**(分支 `task/P4e-web-search`;实现期只做最小检查,全部落地后集中一轮 48/48 + 冒烟)"
)
report.append("§五 下一步 updated")

# ---- 6) 坑 54 / 55 ----
i = find("53. **归因要指向能被复现的实验")
pits = (
    "54. **用例断言里混「宽词」= 给未来埋一颗必然假红的雷(2026-09-30 复核 P4d-fix 时发现,转 P4e C0)**:"
    "`rind-07` 的 `expect_absent_keywords` 选了 `证明`/`录取`——它们在 student 可见块分别出现 **44 块 / 14 块**,"
    "而 `饭卡`/`调档` 是 0 块。今天该用例因 `sources=0` 而 PASS,**可 P4e/P4f 做的正是"让检索更强"**,一旦召回《学籍管理规定》"
    "并据实引用"因病休学需医院诊断证明",就会被自己的断言判成"夹带无据断言"——**这是必然,不是偶发**。\n"
    "   铁律:① 写"某词不得出现在答案里"这类断言前,**先查这个词在全库可见块里出现几次**,宽词要么换成零命中的具体事项词,"
    "要么改成"与上下文词共现才算"(如 `证明` 只在与「录取/报到/调档」共现时判违规);② **"前提是否成立"要分层验**:"
    "标题层无据 ≠ 正文层无据 ≠ **语义层(有没有能回答该诉求的条款)无据**——`rind-02` 就是栽在只看标题(库内其实有 4 篇);"
    "③ 复用一个"补覆盖"的新用例时,必须比原用例**测得更严**,而不是换个 id 换一批词。\n"
    "55. **管道会把退出码吞成假绿——`cmd | tail; echo $?` 取的是 `tail` 的状态(2026-09-30 我自己差点据此误判)**:"
    "我这轮集中评测写成 `python run_evals.py | tail -40 ; echo \"[eval exit=$?]\"`,屏幕上跳出一行 `[eval exit=0]`,"
    "而真实情况是 **47/48、应当判 1**。若我照这行写进结论,就等于"实测退出码 0"粉饰了一次红基线(与坑 35「后台任务 exit 0 ≠ stdout 到手」同源,但方向相反:"
    "**这次是真的把非 0 读成了 0**)。铁律:① 需要退出码时**不要用管道**,先重定向到文件再 `echo $?`,或 `set -o pipefail` / 取 `${PIPESTATUS[0]}`;"
    "② 看到 `exit=0` 与 `47/48` **同时出现就是矛盾**,必须停下来查谁在撒谎;③ 无法实测时**写清"这条是推定不是实测"**,"
    "我在结论里就是这样标的(推定依据:`run_evals.py:761` 的 `return 0 if (total_pass==total and iso_ok) else 1`),冒烟那条才是重跑不带管道的实测。\n"
    "56. **运行时会被测方写脏 git 跟踪文件,按行数判性质会看错(2026-09-30 复核 P4d-fix)**:整轮评测让**服务端**的"
    "`refusal.record_fabricated_ref` 追加 `evals/badcases.json`,该文件 `fabricated_ref.history` 有 **50 条滚动上限**,"
    "我这轮 diff 显示 **34 增 / 34 删**——看着像"重写/丢数据"。做**双向集合比对**后结论是:`cases` 8→8、id 集合不变、"
    "除 `last_seen` 外无字段变化、history 总条数 70→70,丢的 4 条与被加的 4 条是同一现场(`qa-01` 越界引用)的滚动重复,"
    "属**纯运行时副作用**,已 revert 不入库。\n"
    "   铁律:① 说明书写"只增不删"要问清**增删的单位是什么**——这里对 case 成立、对 history 行**不成立**;"
    "② 复核脏文件先做**按主键的集合比对**(id/at/字段三元组),再决定 revert / commit,不能按 `+/-` 行数拍性质;"
    "③ 产品代码写仓库内跟踪文件 = 每次跑测都脏树,后续单应把它挪到 `DATA_DIR` 或加 `.gitignore`(转技术债)。\n"
)
lines.insert(i + 1, pits)
report.append("pits 54/55/56 inserted after pit 53")

body = "".join(lines)
nb = len([l for l in body.splitlines() if l.strip()])
io.open(P, "w", encoding="utf-8", newline="").write(body)
print("written; non-blank lines now %d" % nb)
for r in report:
    print("  -", r)
