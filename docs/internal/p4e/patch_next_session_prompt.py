# -*- coding: utf-8 -*-
"""P4d 合并 + P4e 下发后，更新 docs/NEXT_SESSION_PROMPT.md 的「当前进度」与「你要做的下一个动作」。"""
import io

P = "docs/NEXT_SESSION_PROMPT.md"
lines = io.open(P, encoding="utf-8").read().splitlines(True)
log = []
nb_before = len([l for l in lines if l.strip()])


def replace_by_anchor(anchor, new_text):
    idx = [i for i, l in enumerate(lines) if anchor in l]
    assert len(idx) == 1, "anchor %r hits %d" % (anchor[:28], len(idx))
    i = idx[0]
    nl = "\n" if lines[i].endswith("\n") else ""
    lines[i] = new_text + nl
    log.append("line %d replaced" % (i + 1))


replace_by_anchor(
    "**当前进度（2026-09-30 晚）**",
    "**当前进度（2026-09-30 深夜）**：P1/P2 全部已合并。**P3 AIOps**：P3a 地基、P3b AIOps MCP Server"
    "（`mcp/aiops` 7 个只读工具，宿主机 venv `:18081`）已合并；**P3c/P3d 排队**，待 P4 之后由用户定。"
    "**P4（用户反馈驱动，设计见 `docs/P4.md` M1~M9）**：P4a 拒答硬门控+导入质量门 `827e1ae`、"
    "P4a-1 索引页判据 `5399a5e`、P4b-0 前端拆分 `e947259`、P4b 会话与上下文管理 `0499a89`、"
    "P4c KB 文件夹 + `@` 检索范围 `5611c16`、**P4d LangGraph 检索编排 + 查询改写重试 `bb6e78b`**"
    "（本系列唯一带硬指标的单：变体矩阵 **3/8 → 8/8**，消融 `NOVA_MAX_REWRITE=0` 退化回 3/8，"
    "`RERANK_MIN_SCORE` 全程未动）。**质量线 v2.1 = 48 用例、R@k 1.0、拒答 1.0、忠实度按区间 0.9444~0.9722**；"
    "⚠ **看到 48 条才是当前口径**，47/47、46/47、43/43、40/40 都是旧报告（坑 40）；"
    "⚠ **R@k 从 0.9412 变 1.0 是口径变更**（`qa-09` 括号全半角尺子缺陷已修，"
    "历史各版 0.9412 保留不抹、引用须注明「含尺子缺陷」，坑 51 / `docs/EVAL_BASELINE.md` §十五 15.4）；"
    "⚠ **忠实度是抽样不是测量值**：同输入只重跑 judge 连 3 轮 = 0.9444/0.9444/0.9722，"
    "且两轮独立整轮里 `qa-05`/`qa-07` 在 0.5↔1.0 **互换而聚合值相同** → **聚合稳定是巧合**（坑 50）。"
    "KB **documents 65 / chunks 487**、`dup_titles 0`。"
    "**⚠ 合并时基线带 1 个已知红 `qa-12`**（真实产品缺陷，被新加的「非答案检测」揭出，"
    "实现方**没改绿、退出码如实 1**），已列 P4e C0 必清。",
)

replace_by_anchor(
    "**你要做的下一个动作**",
    "**你要做的下一个动作**：**等 WorkBuddy 把 P4e 交回 `IN_REVIEW`**"
    "（联网搜索开关 + 来源分区标注 + **C0 前置收口两条**；分支 `task/P4e-web-search`，"
    "规格 `docs/TASKS.md` P4e，开单指令 `docs/p4e/workbuddy-order.md`）。"
    "**P4e 复核五把尺**：① **C0 两条是否真清**——`qa-12` 必须是**产品侧真修**（重跑 "
    "`docs/p4d/review_qa12_attribution.py` 看目标块进没进最终 sources），**不接受靠改用例改绿**；"
    "`rind-07` 的宽词修完必须仍保留 ≥3 个零命中具体词 + `probe_ruler_selftest.py` 新反向用例过；"
    "② **开关真的起作用**（坑 48）：同一问句「开」含 `[W1]`、「关」必须走 P4a 拒答模板，两条都要实测；"
    "③ **合规红线**：联网请求出去的那个字符串**只能来自用户本轮输入**——要自己读代码追"
    "「改写串有没有可能带语料片段」「日志记了什么字段」，这是**审代码不是测功能**；"
    "④ **降级可观测**（坑 46/47）：搜索失败退回仅本地必须有 trace/提示，静默兜底等于没兜；"
    "⑤ **基线回到 48/48 且退出码 0**——这是本单闸门，红基线一解放任什么都拦不住。"
    "照例：坑 17 证据入库对账（**落盘 ≠ 入库**）、坑 18 claim→字段、坑 33 探针非空、"
    "坑 45 空集假通过、坑 39 断言必须能判红、坑 38 集合改动做双向 diff。"
    "**新学到的两条要复用**：坑 54「断言用词必须查过它在库里出现几次，宽词=必然假红的雷；"
    "『前提是否成立』要分层验（标题层≠正文层≠语义层）」、"
    "坑 55「**取退出码不要用管道**，`cmd | tail; echo $?` 拿到的是 `tail` 的码」、"
    "坑 56「整轮评测会让服务端写脏 `evals/badcases.json`（50 条滚动上限），按主键集合比对后 revert，别按 +/- 行数判性质」。"
    "P4e 之后按序 **P4f（辅导员 persona + 侧边栏重构）→ P4g（UI 收尾）**。"
    "⚠ 仍要盯的结转项：F3 学段区分实际未交付——存量 65 篇 `audience` 全 common，追问永不触发；"
    "`rind-02` 的 `expect_sources` 是 F2 崩塌哨兵（材料被清会转红，属有意敏感）；"
    "`cc-01` 埋点按裁决保留现状；`badcases.json` 被产品代码写入跟踪文件已转技术债；"
    "两个待用户拍板的小决策：是否加 `.gitattributes`（`eol=lf`，消除坑 36 的双字节数歧义）、"
    "是否清理 4 个已合并的 `task/*` 分支（`task/P3a-sims`、`task/P3b-aiops-mcp`、"
    "`task/P4a-1-index-gate`、`task/P4a-answer-quality`；"
    "`workbuddy/task-t10-retrieval-d910a267` 是别的工作树的检出，**不要动**）。"
    "**⚠ 角色纪律不变**：若你发现自己又要动手实现代码，先确认是不是又一次角色破例——破例要留痕，且不要自己给自己过审。",
)

replace_by_anchor(
    "下发任务给 **Zcode**(实现者)",
    "你是 **Qoder**,NovaCampus 项目的**负责人**。你负责总体把握、拆解计划、下发任务给 **WorkBuddy**"
    "(实现者,2026-09-30 起接替 Zcode),并对 WorkBuddy 的交付做 Review 与合并。"
    "你的目标不是自己埋头写完,而是**保证每一次只有一个写入者、每一次合并都经过独立验证、两个 agent 不会一起改错**。",
)

body = "".join(lines)
nb_after = len([l for l in body.splitlines() if l.strip()])
assert nb_after == nb_before, "line count changed %d -> %d" % (nb_before, nb_after)
io.open(P, "w", encoding="utf-8", newline="").write(body)
print(" | ".join(log), "| non-blank kept %d" % nb_after)
