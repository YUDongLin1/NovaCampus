#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P4f 第 2 回复核落账：TASKS 状态 + HANDOFF 台账/下一步/新坑 72-73。

纪律同前：整行锚点 + assert 命中数 + 幂等（已改过就跳过），不写 CRLF。
"""
import io

log = []


def read(p):
    return io.open(p, encoding="utf-8").read()


def write(p, s):
    io.open(p, "w", encoding="utf-8", newline="").write(s)


# ---------------- TASKS ----------------
P = "docs/TASKS.md"
T = read(P)

a1 = "**当前持棒：Qoder**（**P4f 第 1 回 Review 的三条必修已于 2026-10-01 由 WorkBuddy 修完并交回 `IN_REVIEW`**"
b1 = ("**当前持棒：WorkBuddy**（**P4f 第 2 回复核 = ✅ 必修三条全部复验成立，另下发第 3 回八条收尾项**，"
      "2026-10-01 复核 = Qoder，复验报告 `docs/p4f/review_qoder_p4f_round2.md`，开单指令 "
      "`docs/p4f/workbuddy-order-round3.md`。复验读数：七个自测 **428 条 exit 全 0**（我逐条跑）、"
      "探针极性三态实测（注入 7/7 退 0 / 不注入 5/7 退 1 / 缺 `--base` 退 3）、"
      "流式炸点**我自己走完红绿闭环**（136→拆→134 退 1→复原→136，且拆掉后 detail 是上游 **401**，"
      "证明真请求确实发出去了）。集中验证四次整轮尝试**全部作废**（两次语料被冒烟污染成 69 篇、"
      "两次撞 OpenRouter 免费档每分钟限流 → 13 条 500 被记成用例失败），但拿到三条可用结论："
      "`pf-03` 方向前提被四次测量证伪（改法已定案=开单⑤）、`rind-07` 是尺子分不清「编造」与「如实说没有」"
      "（开单⑥）、C0-③ 种植轮命中 0 次（P4e 是 16 次）方向性成立。**v2.5 三列仍空**，"
      "前置清单见 `docs/EVAL_BASELINE.md` §20.6。上一状态：**P4f 第 1 回的三条必修已于 2026-10-01 由 WorkBuddy 修完并交回 `IN_REVIEW`**")
if a1 in T:
    T = T.replace(a1, b1, 1)
    log.append("TASKS 顶部持棒 header -> 第 2 回复验 + 第 3 回下发")
elif "第 2 回复核 = ✅ 必修三条全部复验成立" in T:
    log.append("TASKS 顶部 header 已改过，跳过")
else:
    raise AssertionError("TASKS 顶部锚点未命中")

lines = T.splitlines(True)
i = [k for k, l in enumerate(lines) if l.startswith("### P4f 辅导员定制")]
assert len(i) == 1
if "第 2 回复核 = ✅" in lines[i[0]]:
    log.append("TASKS P4f 标题已改过，跳过")
else:
    lines[i[0]] = lines[i[0]].replace(
        "❌ **第 1 回 Review 打回（必修三条，零额度）**（2026-10-01 复核 = Qoder，**当前持棒 = WorkBuddy**",
        "🟡 **第 1 回打回 → 第 2 回复核 = ✅ 必修三条全部复验成立 → 第 3 回下发八条**"
        "（2026-10-01 复核 = Qoder，**当前持棒 = WorkBuddy**", 1)
    assert lines[i[0]] != T.splitlines(True)[i[0]]
    log.append("TASKS P4f 标题 -> 第 2 回复验成立")
T = "".join(lines)

MARK = "<!-- QODER-P4F-REVIEW-R2 -->"
if MARK in T:
    log.append("TASKS 第 2 回 Review 结论已存在，跳过")
else:
    anchor = "### P4g UI 细节收尾"
    assert T.count(anchor) == 1
    BLOCK = (
        "#### Review 结论（Qoder，2026-10-01 第 2 回）—— ✅ **必修三条全部复验成立**（零额度），另下发第 3 回八条\n"
        + MARK + "\n"
        "\n"
        "**复验方式**：全程假 key 护身符（`LLM_API_KEY=ZERO-QUOTA-PROTECTOR-*`，意外真调用会拿 401 而不是扣费）。\n"
        "\n"
        "| 必修 | 我怎么验的 | 实测 |\n|---|---|---|\n"
        "| ① 探针极性 | `--selftest` + **真机三态** | 14/14 退 0；注入会话 key 起 `:8961` → `session_env` **7/7 退 0**；"
        "不注入起 `:8962` → `repo_dotenv` 两条判红 **5/7 退 1**；不传 `--base` → **退 3**。"
        "S6「把极性表整个反过来必须红」**不是同义反复**：它注入反表证明判据真从表里读极性；"
        "真表若被改回第一版，S1/S2 直接红 |\n"
        "| ② 流式炸点 | **我自己走红绿闭环** | 基线 136/136 退 0 → `patch_check_c5_tripwire.py apply` 拆炸点 → "
        "**134/136 退 1**（红项正是 C5 A/B）→ `revert` → **`git diff` 为空**（逐字节复原）→ 136/136 退 0。"
        "拆掉后 detail 是 `401 ... /v1/embeddings` —— **真请求确实发出去了**，没有护身符就是一次真实扣费 |\n"
        "| ③ 记账同步 | 逐处核对 | `EVAL_BASELINE` 两处日期 09-03→10-01；`c0_selftest_output.txt` 已刷到 64 条；"
        "`P4F.md` §3.1 主动写明上一版 401 条是「证据没跟着代码重跑」 |\n"
        "\n"
        "**边界与无回归**：本轮 diff 17 文件，`refusal.py`/`faithfulness.py`/`cases.json`/`theme.css`/`.env` **零改动**；"
        "七个自测我复跑 **428 条 exit 全 0**（64+136+33+62+99+20+14）；我第 1 回那 **41 条**安全断言重跑**仍全绿**"
        "（迁移幂等 / 不提权 / prompt 不被覆盖 / 判据能判红能判绿都没被碰坏）。"
        "五条 nit（n1-n5）全收，n6（CRLF）他们核实「入库是 LF、不需改」，我同意。\n"
        "\n"
        "**一处白名单缺口，责任在我**：`evals/run_evals.py` 不在我开的白名单里，但 n5 又点名要改它 —— 单据自相矛盾。"
        "他们把 `--base` 改成必填（方向正确），我按 P4e 先例**不计入实现方越界**。\n"
        "\n"
        "**复核中我代做的两条（纯文档、零额度、可复算）**：① `--base` 改必填后**全仓 3 份文档的复跑命令失效**"
        "（实测退 2），已统一改成 `run_with_server.sh <port> ../evals/run_evals.py --base ...` 并写明"
        "「不要再起 :8900」（脚本 `docs/p4f/patch_docs_base_required.py`；`docs/TASKS.md` 里 P1/P2 时代的 6 处"
        "**历史验收口径故意没动**，改历史等于伪造现场）；② `P4F.md` §3.4 有一行会被读成「种植轮已验证」，"
        "已改成区分「记账机制已拿到」与「种植轮归零仍未验证」。\n"
        "\n"
        "**集中验证四次尝试全部作废（但拿到三条可用结论）** —— 详见 `docs/p4f/review_qoder_p4f_round2.md` §6 "
        "与 `docs/EVAL_BASELINE.md` §20.6：两次因**冒烟中途失败留下 4 篇孤儿文档**把语料从 65 污染成 69"
        "（根因 **F3：`/api/kb/upload` 先落库再生成摘要，不回滚**）；两次撞 **OpenRouter 免费档每分钟限流**"
        "（429 命中 54 次 → 13 条 `HTTP 500` 被评测记成「用例失败」，R@k 从 1.0 砸到 0.6667 —— **F4**）。"
        "四份报告与日志全部改名 `INVALID__*` 存档，**没有一份当基线**。语料已复原 `65/487`、"
        "`user_settings` 已还原、`badcases.json` 主键集合 8→8 后还原。\n"
        "\n"
        "**裁决**：工程侧**无阻塞项**；第 3 回下发八条（① J4 放宽+强制披露 ② persona_prompt 对非作者隐藏正文 "
        "③ 冒烟硬编码模型名 ④ 报告记 effective_model ⑤ `pf-03` 改方向无关比值 ⑥ `rind-07` 判据区分"
        "「断言/声明无据」 ⑦ 报告落 `answer_head`+`sources` 摘要 ⑧ 评测节流 + `env_error` 与用例失败分开记账）。"
        "**全部零额度**，仍在 `task/P4f-persona`，不新建分支。v2.5 基线等 ⑧ 落地后重跑，"
        "或由负责人授权走生产通道（与 v2.4 同档，可直接对照）。\n"
        "\n"
    )
    T = T.replace(anchor, BLOCK + anchor, 1)
    log.append("TASKS 插入第 2 回 Review 结论")

write(P, T)

# ---------------- HANDOFF ----------------
H = read("HANDOFF.md")
hl = H.splitlines(True)
row = [k for k, l in enumerate(hl) if l.startswith("| **P4f** |")]
assert len(row) == 1
if "第 2 回复核 = ✅" in hl[row[0]]:
    log.append("HANDOFF 台账已改过，跳过")
else:
    nl = "\n" if hl[row[0]].endswith("\n") else ""
    old = hl[row[0]]
    hl[row[0]] = (
        "| **P4f** | **辅导员 persona 定制 + 左侧会话栏重构**(+ **C0 前置收口六条**) | "
        "**🟡 第 1 回打回 → 第 2 回复核 ✅ 必修三条全部复验成立 → 第 3 回下发八条**"
        "（2026-10-01，持棒 **WorkBuddy**，开单 `docs/p4f/workbuddy-order-round3.md`）。"
        "复验读数：七个自测 **428 条 exit 全 0**；探针极性真机三态（`session_env` 7/7 退 0 / "
        "`repo_dotenv` 5/7 退 1 / 缺 `--base` 退 3）；流式炸点**红绿闭环我亲自走过**"
        "（136→拆→134 退 1→复原 `git diff` 为空→136，拆掉后 detail 是上游 401，证明真请求确实发出）。"
        "边界干净（`refusal.py`/`faithfulness.py`/`cases.json`/`theme.css`/`.env` 零改动），"
        "我第 1 回的 41 条安全断言重跑仍全绿。**集中验证四次整轮全部作废**：两次语料被冒烟污染成 69 篇"
        "（F3 上传非原子，坑 72）、两次撞免费 key 每分钟限流（F4，坑 73）；"
        "但拿到三条可用结论——`pf-03` 方向前提四次测量全反（改法已定案）、`rind-07` 是尺子分不清"
        "「编造」与「如实说没有」、C0-③ 种植轮命中 0 次（P4e 是 16 次）。**v2.5 三列仍空**，"
        "前置清单见 `EVAL_BASELINE.md` §20.6。历史：第 1 回零额度复核 41 条独立断言全绿 + 必修三条" + nl)
    log.append("HANDOFF 台账 P4f -> 第 2 回复核成立 / 第 3 回下发")
H = "".join(hl)

# 下一步段
a5 = "**下一步 = WorkBuddy 已于2026-10-01 交回必修三条的修复 → Qoder 零额度复验 → 再决定合并**。"
b5 = ("**下一步 = Qoder 第 2 回复核 ✅ 已完成 → 已下发第 3 回八条（持棒 WorkBuddy，全部零额度）→ "
      "交回后我做零额度复验 + 重跑 v2.5 基线 → 再决定合并**。")
if a5 in H:
    H = H.replace(a5, b5, 1)
    log.append("HANDOFF 下一步 -> 第 3 回下发")
elif "已下发第 3 回八条" in H:
    log.append("HANDOFF 下一步已改过，跳过")
else:
    raise AssertionError("HANDOFF 下一步锚点未命中")

pits_anchor = "\n## 七、快速验证命令"
assert H.count(pits_anchor) == 1
if "72. **把「可选增强调用」放在写库之后" not in H:
    NEWP = (
        "\n72. **把「可选增强调用」放在写库之后 = 一次上游失败就把知识库弄脏**（2026-10-01 我自己踩出来的，"
        "F3，转 P4g 头号项）：`/api/kb/upload` 的顺序是 `insert_document` → `insert_chunks` → "
        "**之后**才调 LLM 生成摘要（`agent.summarize_document`）。摘要调用一失败（我这次是换通道后上游 400），"
        "接口回 500，但**文档与分块已经落库**——实测留下 4 篇孤儿，其中 1 篇 `student` 可见，"
        "把我第一次整轮的语料从 `65/487` 污染成 `69/491`，两份报告整体作废（`pf-01` 甚至把那篇孤儿文档召回了）。"
        "同一条也解释了「冒烟中途失败为什么会留脏数据」。铁律：① **可选增强（摘要/标题/向量补算）失败必须回滚整条写入**，"
        "或者先写占位、成功后再更新，绝不能让一次非核心调用决定 KB 是否被污染；"
        "② 任何会写库的验证脚本跑完必须 `kb_doctor` 复查计数（我这次靠它发现 69≠65）；"
        "③ 清理要走**应用自己的删除路径**（`db.delete_document` 会连带清 chunks/向量），不要手删表行。\n"
        "\n73. **评测把「上游限流/没额度」记成「模型答错」，报告就彻底失去归因能力**（2026-10-01 同一晚，F4）："
        "OpenRouter 免费档有**每分钟请求上限**，而 `run_evals.py` 是背靠背串行打 59 个用例。"
        "触发限流后 `llm.chat` 的 `raise_for_status()` 冒到 `/api/chat` 变 **500**，评测把它记成该用例 `pass=false`，"
        "于是 R@k 从 1.0 砸到 **0.6667**、通过率从 93% 掉到 69%——**报告里完全看不出这是额度问题而不是能力问题**。"
        "我第二次重跑（干净语料 65/487）因此又作废一次。铁律：① 评测必须把**环境失败（5xx/429/连不上）"
        "与用例失败分成两个桶**，环境失败不计入通过率分母、但退出码仍非 0；"
        "② 免费/共享通道要有**节流开关**（`NOVA_EVAL_THROTTLE_MS`，默认 0 不改现有行为）；"
        "③ 产品侧上游 429 应回 **503 + 明确文案**，而不是 500 白屏；"
        "④ 作废的报告**改名 `INVALID__*` 存档而不是删掉**——「为什么这一列还空着」必须可查。\n"
    )
    H = H.replace(pits_anchor, NEWP + pits_anchor, 1)
    log.append("HANDOFF 新增坑 72/73")
else:
    log.append("HANDOFF 坑 72 已存在，跳过")

write("HANDOFF.md", H)
print("\n".join(log))
