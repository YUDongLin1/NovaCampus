# -*- coding: utf-8 -*-
"""下发 P4e：把 docs/TASKS.md 的 P4e 条目从 READY 升级为已下发，并加 C0 前置收口两条。"""
import io

P = "docs/TASKS.md"
lines = io.open(P, encoding="utf-8").read().splitlines(True)
log = []
nb_before = len([l for l in lines if l.strip()])

HDR_OLD = "### P4e 联网搜索开关 + 来源分区标注　📋 READY（待 P4d，设计见 M7）"
HDR_NEW = ("### P4e 联网搜索开关 + 来源分区标注 + **C0 前置收口两条**　🚀 **已下发**"
           "（2026-09-30，持棒 **WorkBuddy**，分支 `task/P4e-web-search`，设计见 M7，"
           "开单指令 `docs/p4e/workbuddy-order.md`）")

i = [k for k, l in enumerate(lines) if HDR_OLD in l]
assert len(i) == 1, "P4e header anchor hits %d" % len(i)
hi = i[0]
lines[hi] = HDR_NEW + ("\n" if lines[hi].endswith("\n") else "")
log.append("P4e header -> 已下发")

C0 = (
    "\n"
    "- **C0 前置收口（P4d 第二回 Review 移交，**merge-blocking：不做完这两条，本单集中验证不可能 48/48**）**\n"
    "\n"
    "  > **为什么在本单**：合并后的 v2.1 基线带着**一个已知红 `qa-12`**，评测退出码恒为 1。"
    "留着它，以后『退出码非 0 就阻塞』这条闸门会退化成狼来了（坑 39/54）。"
    "两条都是**小改**（一处融合层参数 + `cases.json` 两个词），且都要靠 P4e 的新评测来验收，"
    "所以**并进本单、集中跑一轮**，不单独开一单再复跑一整轮。"
    "\n"
    "  - [ ] **C0-① `qa-12` 融合层截断漏召（真实产品缺陷，必须真修，禁止改用例来改绿）**"
    "\n"
    "    - **实测断点（复核方探针 `docs/p4d/review_qa12_attribution.py`，证据 `docs/p4d/evidence/review/qa12_attribution.json`）**："
    "问句「研究生奖助学金评审是怎么规定的?」下，doc9「EVAL-研究生奖学金评定办法」"
    "**向量层第 6 位（0.6809）→ 关键词层未进 top20 → `FUSION_TOP_K=8` 的 8 个槽位被两篇本科生办法的全部块占满 → 根本没进 rerank**；"
    "最终 3 条来源全为本科生办法（0.9801/0.9063/0.7985），答案因此**错误地否定性断言**「研究生相关规定未在知识库覆盖」。"
    "\n"
    "    - ⚠ **不要动 `RERANK_MIN_SCORE`**——断点在它**之前**，动阈值既修不好这条、又会破坏 P4a 拒答门控与 F2 现场（本系列已三次确认这条纪律）。"
    "\n"
    "    - **允许的修法（任选，须给 A/B 数据）**：① 在**融合截断之前**做 per-doc 多样化（现有 `MAX_PER_DOC=2` 是在 rerank **之后**才生效，"
    "这是本缺陷的结构性根源）；② 扩 `FUSION_TOP_K`（注意与延迟/C2 质量信号的既有数值联动）；"
    "③ `TERM_EXPANSION` 补「奖助学金 → 奖学金|助学金」并把**学段词**（研究生/本科生）纳入改写维度。"
    "④ 生成侧配套：`context` 里**有来源时不得输出「未在知识库覆盖」这类否定性断言**，"
    "要么据实作答、要么明确区分「库内确无」与「未召回到」（这正是 ④ 非答案检测想暴露的行为）。"
    "\n"
    "    - **验收（不许口头说改好了）**：重跑 `docs/p4d/review_qa12_attribution.py` → 目标块**必须进入最终 sources**；"
    "`qa-12` 转 PASS；**且矩阵 8/8、`intent`/`rewrite`/`scoped_qa`/`refusal_indomain` 全绿不回退**（改融合层最可能碰坏 rewrite 那条链）。"
    "\n"
    "  - [ ] **C0-② `rind-07` 的 `expect_absent_keywords` 去掉宽词（坑 54）**"
    "\n"
    "    - **实测**：`证明` 在 student 可见块出现 **44 块**、`录取` **14 块**（休学要「诊断证明」、开除发「学习证明」等正当出处都有）；"
    "`饭卡`/`调档`/`交回`/`退卡`/`提档` 是 **0 块**。C0-① 把检索增强之后，`rind-07` 极可能被自己人判成「夹带无据断言」。"
    "\n"
    "    - **修法（二选一，须给理由）**：把宽词换成零命中的具体事项词（`交回`/`退卡`/`提档`）；"
    "或改成**共现判据**——`证明`/`录取` 仅在与「录取/报到/调档」同现时才算夹带。"
    "**不得因此削弱该用例的检测力**：修完必须保留至少 3 个零命中具体词，并在 `probe_ruler_selftest.py` 里加一条反向用例"
    "（构造一个含「需医院诊断证明」的**正当引用**答案 → 必须 PASS）。"
    "\n"
    "    - **同时把该用例 note 的证据口径改准**：现写「13 词在 65 篇**标题**中 0 命中 → 真的域内无据」，"
    "准确说法是「**标题层 0 命中；正文层有 `钥匙/空调/档案/录取` 等巧合命中，但全库『交回/退还/退卡/提档/调档/档案转递』皆 0 块、"
    "7 项诉求逐条无一可答 → 语义层无据**」（复核方 `docs/p4d/review_rind07_premise.py`，证据 `evidence/review/rind07_premise.json`）。"
    "\n"
)
lines.insert(hi + 1, C0)
log.append("C0 block inserted after P4e header")

# 依赖行补一句集中验证口径
dep_old = "- **依赖**：P4d 合并；`docs/P4.md` M7、§六"
j = [k for k, l in enumerate(lines) if dep_old in l]
assert len(j) == 1, "dep anchor hits %d" % len(j)
lines[j[0]] = (
    "- **依赖**：P4d 已合并（master `bb6e78b`）；`docs/P4.md` M7、§六\n"
    "- **测试节奏（用户 2026-09-30 定的口径）**：实现期**只跑针对性最小检查**（相关单条断言 / `probe_ruler_selftest.py` 这类纯本地秒级自测），"
    "**全部落地后集中跑一轮**完整评测（v2.1 = **48 用例，必须 48/48 且退出码 0**）+ 冒烟（`65→65`）；"
    "**不要中途反复复跑整轮**。忠实度按区间 0.9444~0.9722 读、且**逐条可互换**，不得当点值用作闸门（坑 50/54）。\n"
    "- **取证纪律**：要看退出码就**别把命令接在管道后**（坑 55）；"
    "整轮评测会让服务端写脏 `evals/badcases.json`（50 条滚动上限），交回前**按主键集合比对后 revert**，别把它当交付物提交（坑 56）。\n"
)
log.append("依赖/节奏/取证 lines appended")

body = "".join(lines)
nb_after = len([l for l in body.splitlines() if l.strip()])
assert nb_after > nb_before
io.open(P, "w", encoding="utf-8", newline="").write(body)
print(" | ".join(log))
print("non-blank %d -> %d (+%d)" % (nb_before, nb_after, nb_after - nb_before))
