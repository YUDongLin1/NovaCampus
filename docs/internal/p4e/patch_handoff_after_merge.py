# -*- coding: utf-8 -*-
"""P4d 合并后同步 HANDOFF.md（顶部日期行 / 运行状态 / 评测基线行 / 任务台账 / §五 下一步 / 坑 54-56）。

按行内子串定位 + 断言唯一命中，防止其他会话并行改文档导致锚点漂移（HANDOFF 坑 3）。
串内一律用「」，不用 ASCII 双引号，避免嵌套引号截断字符串（坑 4）。
"""
import io

P = "HANDOFF.md"
lines = io.open(P, encoding="utf-8").read().splitlines(True)
log = []
nb_before = len([l for l in lines if l.strip()])


def find(sub):
    idx = [i for i, l in enumerate(lines) if sub in l]
    assert len(idx) == 1, "anchor %r hit %d times" % (sub[:28], len(idx))
    return idx[0]


def patch_line(sub, old_frag, new_frag):
    i = find(sub)
    assert old_frag in lines[i], "fragment missing on line %d: %r" % (i + 1, old_frag[:28])
    assert lines[i].count(old_frag) == 1, "fragment not unique on line %d" % (i + 1)
    lines[i] = lines[i].replace(old_frag, new_frag, 1)
    log.append("patched line %d" % (i + 1))


# ---------- 1) 顶部日期行 ----------
patch_line(
    "供**零上下文新会话**接续",
    "供**零上下文新会话**接续",
    "**2026-09-30 由 Qoder 更新:P4d 第二回 Review 通过并合并 `master`(`bb6e78b`),基线 v2.1(48 用例,"
    "合并时**已知 1 红 `qa-12`** = ④ 揭出的真实漏召,不是尺子问题);**P4e 已下发(持棒 WorkBuddy),"
    "含 C0 前置收口两条**(`qa-12` 融合层截断漏召 + `rind-07` 宽词断言),"
    "见 `docs/TASKS.md` P4e 与 `docs/p4e/workbuddy-order.md**;"
    "供**零上下文新会话**接续",
)

# ---------- 2) 运行状态：:8900 实例归属 ----------
i = find("venv=`novaagent/.venv`")
lines[i] = lines[i].rstrip("\n") + (
    ";**当前 :8900 实例归属 WorkBuddy**(父进程链 `uvicorn -> bash -> sandbox-cli -> WorkBuddy.exe`,"
    "cwd=主工作树 `novaagent/`,`NOVAAGENT_EVAL_TEMPERATURE=0`,2026-09-30 由 `b165caf` 代码起,"
    "已用 `git diff --stat b165caf..HEAD -- novaagent/` 为空**确认服务端代码与被审对象一致**)。"
    "**Review 期只读它的端口、绝不自作主张重启别人的服务**(坑 37);要第二实例就另起端口,"
    "并用 `bash docs/p4d/run_with_server.sh <port> <cmd>` 把起停收进同一条命令(Git Bash 无 setsid)"
) + "\n"
log.append("运行状态 NovaAgent row patched")

# ---------- 3) 评测基线行 ----------
patch_line(
    "以下为 v2.0 历史口径(保留)",
    "以下为 v2.0 历史口径(保留)",
    "**复核方(Qoder)独立整轮 `reports/eval_report_20260930_173320.json` = 47/48、R@k 1.0、忠实度 0.9722、"
    "拒答 1.0、隔离 ok(41 会话)——与实现方逐值一致**;但**同一批用例里 `qa-05` 0.5→1.0、`qa-07` 1.0→0.5 互换**,"
    "**聚合值相同是巧合,不是指标可靠**(judge 抖动第二条实证,`docs/EVAL_BASELINE.md` §十六 16.2)。"
    "⚠ **合并时基线带 1 个已知红(`qa-12`):P4e 集中验证必须清回 48/48 且退出码 0**,"
    "否则『退出码非 0 就阻塞』会长期失真成狼来了(坑 39/54)。以下为 v2.0 历史口径(保留)",
)

# ---------- 4) 任务台账：P4c / P4d / P4e 三行（插在 T7 之前） ----------
rows = (
    "| **P4c** | **KB 文件夹 + `@` 指定检索范围 + 学段元数据** | **✅ DONE —— Review 通过并合并 master `5611c16`(2026-09-30)"
    ";三条硬约束由复核方自写 5 条安全探针守住,迁移与 db 层在库副本上跑到 18/18,基线 v1.9** |\n"
    "| **P4d** | **LangGraph 检索编排 + 查询改写重试**(本系列唯一带硬指标的单) | **✅ DONE —— 第一回 REJECTED(工程侧全过、评测侧 4 条收口),"
    "修复轮 `290e287` 交回,**第二回独立把关通过并合并 master `bb6e78b`**(2026-09-30)。"
    "硬指标矩阵 **3/8→8/8**、消融 `NOVA_MAX_REWRITE=0` 退化回 3/8、`RERANK_MIN_SCORE` 全程未动;"
    "基线 **v2.1 / 48 用例、R@k 1.0(口径变更:qa-09 括号全半角尺子缺陷已修)**,"
    "合并时**已知 1 红 `qa-12`**(转 P4e C0)** |\n"
    "| **P4e** | **联网搜索开关 + 来源分区标注**(+ **C0 前置收口两条**) | **🚀 已下发(持棒 WorkBuddy,2026-09-30)**,"
    "规格 `docs/TASKS.md` P4e,开单指令 `docs/p4e/workbuddy-order.md`,设计 `docs/P4.md` M7。"
    "**合规红线:联网请求只发当前问题文本**——库内文档内容/会话历史/学生个人信息一律不出网 |\n"
)
k = find("| T7 | 向量库 sqlite → sqlite-vec")
lines.insert(k, rows)
log.append("3 ledger rows inserted before T7")

# ---------- 5) §五 下一步 ----------
next_text = (
    "**P4d-fix 第二回复核 = ✅ 通过并合并 `master` `bb6e78b`**(2026-09-30,一次集中把关)。4 条收口逐条独立复验成立:"
    "② 我自跑 `docs/p4d/probe_ruler_selftest.py` → 21 条断言全 OK、**退出码 0**(断言会判红,坑 39 达标);"
    "③ `evals/faithfulness.py` **0 变更** + `faithfulness_spread.json` 字段与文档引用**逐值对上**;"
    "④ 非答案检测**只挂 `judge_qa`**、`judge_refusal*` 路径**零调用点**(否则会把正确拒答打成非答案);"
    "① `cases.json` 按 id 语义比对 47→48 **零丢失**、唯一被改的就是 `rind-02`(`95585` 仍留在 `expect_absent_keywords`)、"
    "`rind-07` 使 `refusal_indomain` **补回 6 条**。我这轮集中验证 **47/48 与实现方逐值一致**,"
    "冒烟 `exit 0`(第二次不带管道重跑,是实测)且 `documents 65→65`。"
    "**复核新增 2 条发现 → 转 P4e C0(不构成本单第二次打回,理由见 `docs/TASKS.md` Review 结论 ⑤)**:"
    "① `qa-12` 的真实断点**在融合层 `FUSION_TOP_K=8` 截断**——doc9「EVAL-研究生奖学金评定办法」向量排**第 6**、"
    "关键词**未进 top20**(问句用「奖助学金/评审」,doc9 正文只有「奖学金/评定」)、8 个融合槽位被两篇本科生办法占满、"
    "**根本没进 rerank**;回执写的『未进 top3』字面成立但归因偏后,**只动 `RERANK_MIN_SCORE` 修不好**;"
    "② `rind-07` 的『域内无据』我从标题层推到**正文/语义层**复验——**前提成立**(全库『交回/退还/退卡/提档/调档/档案转递』皆 **0 块**,"
    "7 项诉求逐条扫描无一可答,**不是 `rind-02` 那种伪前提**),**但 `expect_absent_keywords` 混了宽词**"
    "(`证明` 在 student 可见块 **44 块**、`录取` **14 块**),检索一增强就**必然假红**。"
    "**下一步 = 等 WorkBuddy 交回 P4e**(分支 `task/P4e-web-search`;实现期只做针对性最小检查,"
    "全部落地后集中跑一轮 **48/48 + 退出码 0 + 冒烟 65→65**)"
)
i = find("**下一步 = 等 WorkBuddy 按 4 条清单修完再交回**")
nl = "\n" if lines[i].endswith("\n") else ""
lines[i] = lines[i].replace("**下一步 = 等 WorkBuddy 按 4 条清单修完再交回**", next_text, 1) + (nl if not lines[i].endswith("\n") else "")
log.append("§五 下一步 patched")

# ---------- 6) 坑 54 / 55 / 56 ----------
pits = (
    "54. **用例断言里混「宽词」= 给未来埋一颗必然假红的雷(2026-09-30 复核 P4d-fix 发现,转 P4e C0)**:"
    "`rind-07` 的 `expect_absent_keywords` 选了 `证明`/`录取`——它们在 student 可见块分别出现 **44 块 / 14 块**,"
    "而 `饭卡`/`调档` 是 0 块。今天该用例因 `sources=0` 而 PASS,**可 P4e/P4f 做的正是「让检索更强」**,"
    "一旦召回《学籍管理规定》并据实引用「因病休学需医院诊断证明」,就会被自己的断言判成「夹带无据断言」——**必然,不是偶发**。"
    "铁律:① 写「某词不得出现在答案里」这类断言前,**先查这个词在全库可见块里出现几次**;宽词要么换成零命中的具体事项词,"
    "要么改成「与上下文词共现才算」(如 `证明` 只在与「录取/报到/调档」共现时判违规);"
    "② **「前提是否成立」要分层验**——标题层无据 ≠ 正文层无据 ≠ **语义层(有没有能回答该诉求的条款)无据**,"
    "`rind-02` 就栽在只看标题(库内其实有 4 篇);③ 为补覆盖新写的用例必须比原用例**测得更严**,不能换个 id 换一批词。\n"
    "55. **管道会把退出码吞成假绿——`cmd | tail; echo $?` 取的是 `tail` 的状态(2026-09-30 我自己差点据此误判)**:"
    "我这轮集中评测写成 `python run_evals.py | tail -40 ; echo \"[eval exit=$?]\"`,屏幕上跳出 `[eval exit=0]`,"
    "而真实情况是 **47/48、应当判 1**。若照这行写进结论,就等于拿「实测退出码 0」粉饰了一次红基线"
    "(与坑 35 同源但方向相反:**这次是真的把非 0 读成了 0**)。"
    "铁律:① 需要退出码时**不要用管道**,先重定向到文件再 `echo $?`,或 `set -o pipefail` / 取 `${PIPESTATUS[0]}`;"
    "② `exit=0` 与 `47/48` **同时出现就是矛盾**,必须停下来查谁在撒谎;③ 拿不到实测就**写清「这条是推定不是实测」**,"
    "我在结论里就是这样标的(推定依据 `run_evals.py:761` 的 `return 0 if (total_pass==total and iso_ok) else 1),"
    "冒烟那条才是重跑不带管道的实测)。\n"
    "56. **运行时会被测方写脏 git 跟踪文件,按 +/- 行数判性质会看错(2026-09-30 复核 P4d-fix)**:"
    "整轮评测让**服务端**的 `refusal.record_fabricated_ref` 追加 `evals/badcases.json`,"
    "其 `fabricated_ref.history` 有 **50 条滚动上限**,我这轮 diff 显示 **34 增 / 34 删**——看着像「重写/丢数据」。"
    "做**双向集合比对**后定性为:`cases` 8→8、id 集合不变、除 `last_seen` 外无字段变化、history 总条数 70→70,"
    "丢的 4 条与被加的 4 条是同一现场(`qa-01` 越界引用)的滚动重复 → **纯运行时副作用**,已 revert 不入库。"
    "铁律:① 说明书写「只增不删」要问清**增删的单位**——这里对 case 成立、对 history 行**不成立**;"
    "② 复核脏文件先做**按主键的集合比对**(id/at/字段三元组)再决定 revert/commit,不能按行数拍性质;"
    "③ 产品代码往仓库内跟踪文件写 = 每次跑测都脏树,应挪到 `DATA_DIR` 或加 `.gitignore`(转技术债)。\n"
)
p = find("53. **归因要指向能被复现的实验")
lines.insert(p + 1, pits)
log.append("pits 54/55/56 inserted")

body = "".join(lines)
nb_after = len([l for l in body.splitlines() if l.strip()])
assert nb_after > nb_before, "content shrank: %d -> %d" % (nb_before, nb_after)
io.open(P, "w", encoding="utf-8", newline="").write(body)
print(" | ".join(log))
print("non-blank lines %d -> %d (+%d)" % (nb_before, nb_after, nb_after - nb_before))
