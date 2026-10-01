#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P4f 第 3 回复核落账 + P5 立项（TASKS / HANDOFF 同步）。锚点整行匹配 + assert + 幂等。"""
import io

log = []


def read(p):
    return io.open(p, encoding="utf-8").read()


def write(p, s):
    io.open(p, "w", encoding="utf-8", newline="").write(s)


# ---------------- TASKS ----------------
P = "docs/TASKS.md"
T = read(P)

a1 = "**当前持棒：Qoder**（**P4f 第 3 回八条已由 WorkBuddy 全部修完并交回 `IN_REVIEW`**"
b1 = ("**当前持棒：WorkBuddy**（**P4f 第 3 回复核 = 八条里七条复验成立，只剩 ⑥ 一处必修**，"
      "2026-10-01 复核 = Qoder，报告 `docs/p4f/review_qoder_p4f_round3.md`，"
      "开单 `docs/p4f/workbuddy-order-round4.md`）。复验读数：七个自测我逐条跑 **508 条 exit 全 0**；"
      "② 我**亲自拆掉投影走了红绿闭环**（`main.py:1023` 换回 `rows` → **154/158 退 1**，红的正是脱敏 4 条 → "
      "`git checkout --` 复原 → **158/158 退 0**，`git diff` 无残留）；① 混合档真机 `:8963` → **7/7 退 0**，"
      "`[DISCLOSURE]` 里 `embedding_calls: null` + `raw: \"unknown\"`（**没写成 0**）。"
      "**⑥ 的两个假绿洞是我自己造样本复现的**：`_derive_no_evidence_marks()` 把模板里的噪声片段"
      "（`'0.3'`、`'https'`）也当成「声明无据」，而豁免方向是**放行** → "
      "「调档流程见 https://…」「饭卡余额 0.3 个工作日内退还」这类**真编造被判绿**；"
      "反过来「库内未细化…办理流程」被判红。假绿比假红危险（评测会报 PASS），故第 4 回必修这一条，"
      "约 10 行 + 3 条反向自测 + 一条「派生集合不得含数字/URL 片段」的静态体检。"
      "另：本轮汇总写 507 是把 `test_p4f_c0` 按 63 计（真值 64 → **508**），"
      "`HANDOFF` 台账行被写成两遍（闭合 `|` 后挂着 523 字旧内容）—— 两处我已代改（`2a9c4aa`），"
      "并要求第 4 回把「合计」改成**从各文件 `[RESULT] n/n` 现算**（同一形状第四次复发）。"
      "**同时 P5「应用外壳重构」已立项**：设计稿 `docs/P5.md`（负责人四项裁决：单栏导航+历史列表 / "
      "内置头像库 / 学生保留辅导员只读位 / 先合并 P4f 再开 P5），**等 P4f 合并后立即下发**。"
      "上一状态：**P4f 第 2 回复核 = ✅ 必修三条全部复验成立，另下发第 3 回八条收尾项**，"
      "由 WorkBuddy 修完八条后于 2026-10-01 交回")
if a1 in T:
    T = T.replace(a1, b1, 1)
    log.append("TASKS 顶部持棒 header -> 第 3 回复核 + 第 4 回下发 + P5 立项")
elif "P4f 第 3 回复核 = 八条里七条复验成立" in T:
    log.append("TASKS 顶部已改过，跳过")
else:
    raise AssertionError("TASKS 顶部锚点未命中")

lines = T.splitlines(True)
i = [k for k, l in enumerate(lines) if l.startswith("### P4f 辅导员定制")]
assert len(i) == 1
if "第 3 回复核 = 七条成立" in lines[i[0]]:
    log.append("TASKS P4f 标题已改过，跳过")
else:
    _before = lines[i[0]]
    lines[i[0]] = lines[i[0]].replace(
        "🟡 **第 3 回八条已修完 → IN_REVIEW 待复核**",
        "🟡 **第 3 回复核：八条里七条 ✅，⑥ 两个假绿洞 → 第 4 回一条必修**", 1)
    assert lines[i[0]] != _before, "P4f 标题替换未生效"
    log.append("TASKS P4f 标题 -> 第 3 回复核状态")
T = "".join(lines)

MARK = "<!-- QODER-P4F-REVIEW-R3 -->"
if MARK in T:
    log.append("TASKS 第 3 回 Review 结论已存在，跳过")
else:
    anchor = "### P4g UI 细节收尾"
    assert T.count(anchor) == 1
    BLOCK = (
        "#### Review 结论（Qoder，2026-10-01 第 3 回）—— ⚠ **七条 ✅ + ⑥ 两个假绿洞（第 4 回必修）**\n"
        + MARK + "\n"
        "\n"
        "全文 `docs/p4f/review_qoder_p4f_round3.md`。要点：①②③④⑤⑦⑧ 逐条复验成立"
        "（② 的红绿闭环我亲自走过；① 混合档真机 7/7 且 `embedding_calls` 照实写 `unknown`；"
        "⑤ `cases.json` 实测**只删了 `\"longer\": \"formal\"` 一行**）；"
        "**⑥ 判据的豁免方向是放行**，而派生集合混进 `'0.3'`/`'https'` 噪声 → "
        "真编造被判绿（我造的两条样本稳定复现，读数在 "
        "`docs/p4f/evidence/review/r3_qoder_rind07_ruler_probe.txt`），"
        "同时「库内未细化…办理流程」被误判红。第 4 回开单 `docs/p4f/workbuddy-order-round4.md`："
        "过滤函数具名纯函数化 + 补同义无据词 + 三条能判红的反向自测 + 一条静态体检，"
        "并要求把「七个自测合计」改成**现算**而不是手加。\n"
        "\n"
    )
    T = T.replace(anchor, BLOCK + anchor, 1)
    log.append("TASKS 插入第 3 回 Review 结论")

# P4g 归并到 P5
g_anchor = "### P4g UI 细节收尾（周报文本框等）　📋 READY（待 P4f，设计见 M9）"
if g_anchor in T and "已并入 P5" not in T:
    T = T.replace(g_anchor,
                  "### P4g UI 细节收尾（周报文本框等）　📋 **已并入 P5**（2026-10-01 用户提出外壳重构诉求，"
                  "见 `docs/P5.md`；P4g 的文本框等零碎项作为 P5-1 的子项一并做）", 1)
    log.append("TASKS P4g -> 并入 P5")

# 追加 P5 小节（放在「技术债」之前）
if "### P5 应用外壳重构" not in T:
    ta = "## 技术债（按简历价值排序，轮到下发时补全规格）"
    assert T.count(ta) == 1
    T = T.replace(ta, (
        "### P5 应用外壳重构：左侧单栏导航 + 辅导员页（内置头像库）　📐 **设计完成，等 P4f 合并即下发**"
        "（2026-10-01 用户提出，参考 WorkBuddy 客户端左栏）\n"
        "\n"
        "- **设计稿**：`docs/P5.md`（信息架构图、逐入口规格、RBAC 矩阵、9 条可验收标准、拆单方案）\n"
        "- **负责人四项裁决**：单栏导航 + 历史列表 / 内置头像库（16 个内联 SVG，存逻辑 id 不存路径，"
        "禁真实人物与校徽）/ 学生保留「辅导员」**只读位** / 先合并 P4f 再开 P5\n"
        "- **口径变更**：`docs/P4B0.md` 的「前端行为零变化」不变量在 P5 **替换**为「**后端行为零变化**」"
        "（`theme.css` 设计令牌仍不动；这条修订要写进 P4B0 末尾，不许偷偷改基线）\n"
        "- **一次后端小改**：`personas.avatar TEXT DEFAULT ''` 走既有幂等加列（库副本连跑两遍验幂等）\n"
        "- **拆单**：P5-1 壳层与页面搬迁 → P5-2 辅导员页 + 头像 + RBAC 矩阵断言（**一张单两阶段交回**，不拆五张）\n"
        "- **红线**：全程零额度（假 key 护身符）；走查用库副本 + 独立端口并按属主杀净；"
        "`E:\\<internal-affairs-dir>\\` 不入库；头像不含真实人脸/校徽\n"
        "\n") + ta, 1)
    log.append("TASKS 追加 P5 小节")
else:
    log.append("TASKS P5 小节已存在，跳过")

write(P, T)

# ---------------- HANDOFF ----------------
H = read("HANDOFF.md")
hl = H.splitlines(True)
row = [k for k, l in enumerate(hl) if l.startswith("| **P4f** |")]
assert len(row) == 1
if "第 3 回复核 = 七条" in hl[row[0]]:
    log.append("HANDOFF P4f 行已改过，跳过")
else:
    nl = "\n"
    hl[row[0]] = (
        "| **P4f** | **辅导员 persona 定制 + 左侧会话栏重构**(+ **C0 前置收口六条**) | "
        "**🟡 第 3 回复核：八条里七条 ✅，⑥ 有两个假绿洞 → 第 4 回一条必修**"
        "（2026-10-01 复核 = Qoder，报告 `docs/p4f/review_qoder_p4f_round3.md`，"
        "开单 `docs/p4f/workbuddy-order-round4.md`，持棒 **WorkBuddy**）。"
        "复验：**七个自测逐条跑 508 条 exit 全 0**；② 我亲自拆投影走红绿闭环"
        "（154/158 退 1 → 复原 → 158/158 退 0，`git diff` 无残留）；① 混合档真机 `:8963` 7/7 退 0 且 "
        "`embedding_calls` 写 `unknown` 不写 0；⑤ `cases.json` 实测只删 `\"longer\": \"formal\"` 一行。"
        "**⑥ 的问题**：`_derive_no_evidence_marks()` 把 `build_refusal` 模板切出的噪声片段"
        "（`'0.3'`、`'https'`）当成「声明无据」，而豁免方向是**放行** → "
        "「调档流程见 https://…」「饭卡余额 0.3 个工作日内退还」这类**真编造被判绿**（评测会报 PASS），"
        "同时「库内未细化…办理流程」被误判红。第 4 回：过滤函数具名化 + 补同义无据词 + "
        "三条能判红的反向自测 + 「派生集合不得含数字/URL」静态体检，并把自测合计改成现算"
        "（507 是手抄，真值 508；同一形状第四次复发）。"
        "**v2.5 基线**：⑥ 修完由我用 `qwen/qwen-plus` + `--throttle-ms 4000` 重跑两档并回填三列"
        "（按 C0-② 记通道口径变更）→ 合并 → 立即下发 **P5**。"
        "历史：第 1 回打回三条必修 → 第 2 回 ✅ → 第 3 回八条（J4 拆分/脱敏/冒烟/effective_model/"
        "pf-03 方向无关/absent 断言区分/answer_head/env_error 分账）" + nl)
    log.append("HANDOFF P4f 行 -> 第 3 回复核")
# 新增 P5 台账行
if "| **P5** |" not in H:
    t7 = [k for k, l in enumerate(hl) if l.startswith("| T7 |")]
    assert len(t7) == 1
    hl.insert(t7[0], (
        "| **P5** | **应用外壳重构：左侧单栏导航 + 辅导员页（内置头像库）** | "
        "**📐 设计完成，等 P4f 合并即下发**（2026-10-01 用户提出，参考 WorkBuddy 客户端左栏）。"
        "设计稿 `docs/P5.md`；四项裁决：单栏导航+历史列表 / 内置头像库（16 个内联 SVG，存逻辑 id，"
        "禁真实人物与校徽）/ 学生保留「辅导员」只读位 / 先合并 P4f。"
        "**口径变更**：`P4B0` 的「前端行为零变化」不变量替换为「后端行为零变化」（要在 P4B0 末尾留修订）。"
        "一次后端小改：`personas.avatar` 幂等加列。拆单：一张单两阶段（P5-1 壳层搬迁 / P5-2 辅导员页+头像+RBAC 矩阵） |\n"))
    log.append("HANDOFF 台账新增 P5 行")
H = "".join(hl)

# 下一步段
nxt = "**Qoder 下一步（全部零额度离线命令，不发任何真 LLM/embedding/联网请求）**："
if "P4f 第 4 回 = 一条必修" not in H:
    k = [i for i, l in enumerate(H.splitlines(True)) if l.startswith(nxt)]
    assert len(k) == 1, k
    lines2 = H.splitlines(True)
    lines2.insert(k[0], (
        "**P4f 第 4 回 = 一条必修（⑥ 判据假绿洞）**（2026-10-01 下发，持棒 WorkBuddy，零额度）："
        "复验入口 `novaagent/tests/test_p4f_persona_eval.py`（应 71/71 或新增条数）+ 其余六个自测全绿；"
        "反向闭环要求「把过滤函数改成不过滤 → 三条新断言必须红」。\n"
        "**P5 已立项**（2026-10-01 用户提出外壳重构诉求）：设计稿 `docs/P5.md`，"
        "**等 P4f 合并后立即下发**；P4g 的零碎 UI 项并入 P5-1。\n"))
    H = "".join(lines2)
    log.append("HANDOFF 下一步插入第 4 回与 P5")
elif "P4f 第 4 回 = 一条必修" in H:
    log.append("HANDOFF 下一步已改过，跳过")

write("HANDOFF.md", H)
print("\n".join(log))
