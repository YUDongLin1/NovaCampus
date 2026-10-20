# -*- coding: utf-8 -*-
"""P4e 主体+S1 第 1 回打回的文档同步（TASKS 头部与结论、HANDOFF 下一步、坑 63）。"""
import io

log = []

# ---------------- TASKS.md ----------------
P = "docs/TASKS.md"
T = io.open(P, encoding="utf-8").read().splitlines(True)
nb0 = len([l for l in T if l.strip()])

i = [k for k, l in enumerate(T) if l.startswith("> **当前持棒：")]
assert len(i) == 1
nl = "\n" if T[i[0]].endswith("\n") else ""
T[i[0]] = ("> **当前持棒：WorkBuddy**（**P4e 主体 + S1 第 1 回复核 = ❌ 打回**，2026-10-01；"
           "分支 `task/P4e-websearch-main`，提交 `c65f771`+`467bbae`+`8c1b5f1`，**未合并 master**。"
           "**功能与红线我逐条实测通过**：出网请求体只有 `model/input/tools/tool_choice` 且 `input` 恒等问题文本、"
           "合规探针带 E6/E6b 反向对照；`web_grounded` 4/4 开↔关双向；冒烟 exit 0/65→65；"
           "流式渐进性确实恢复（早窗 span 208~574ms vs 全缓冲 31~48ms）、abort 后消息 0 残留；"
           "18 条 qa 逐条实测无一例「有来源却零可核查事实」。"
           "**卡住合并的是尺子与可复现性**："
           "① `STREAM_MIN_SPAN_MS=300`（我给的数）落在真流式实测分布**里面** → 会随机判红；"
           "② 「55/55」依赖默认关闭的测试钩子，而**评测报告 JSON 不记录 env 标志**（我核过两份报告的顶层键），"
           "不带钩子我实测 **53/55、退出码 1**（`ss-01` span=239ms、`ss-03` 闸门未命中）；"
           "③ 我这轮 `badcases.json` 多出 **11 条 `ungrounded`**（重生后仍无据），已排除 qa，疑在多轮/长上下文"
           "（`cc-01` 一轮 43 请求），**必须归因**，不许靠改判据掩盖。"
           "打回指令 `docs/p4e/workbuddy-reject-order-main.md`；"
           "负责人自认三条错：单据里「② 也该 FAIL」是我写错（delta 数无区分力）、阈值 300 是我给的、"
           "要求全绿却没写钩子必须开。基线 **v2.4 / 55 用例**")
T[i[0]] = T[i[0]] + nl
log.append("TASKS 持棒头部重写")

p4e = [k for k, l in enumerate(T) if l.startswith("### P4e 联网搜索开关")]
assert len(p4e) == 1
k = p4e[0]
if "🟡 **进行中**" in T[k]:
    T[k] = T[k].replace("🟡 **进行中**（C0 两条已 ✅ 通过并合并 `master`；主体 + S1 已下发",
                        "🟡 **进行中 —— 主体 + S1 第 1 回 ❌ 打回（尺子与可复现性）**（C0 两条已 ✅ 合并 `master`；主体 + S1 已下发", 1)
assert "第 1 回 ❌ 打回" in T[k], T[k][:90]
log.append("P4e 条目标题标记打回")

CONC = (
    "\n#### Review 结论（Qoder，2026-10-01 主体 + S1 第 1 回）——❌ **打回**"
    "（功能与红线成立，卡在尺子与可复现性）\n"
    "\n"
    "**我这次独立跑的**：边界 46 文件全在白名单、禁改项 0 变更、三个检索常量未动；"
    "`cases.json` 按 id 语义比对 48→55（v2.4）**旧用例零丢失零改动**；"
    "自起 :8922 显式 `--base` 跑整轮 → **53/55、退出码 1**，红的两条全在 `stream_sse`，"
    "其余 qa 18/18、refusal 6/6、kb_hidden 3/3、refusal_indomain 6/6、intent 2/2、rewrite 2/2、"
    "**web_grounded 4/4（开/关双向）**、隔离 47 会话 ok、R@k 1.0、忠实度 0.8889；"
    "冒烟 **exit 0 / 65→65**。另用双实例直测流式（:8920 早窗 / :8921 `EARLY_WINDOW_CHARS=0` 全缓冲）："
    "**span 早窗 343/574/208ms vs 全缓冲 31/48ms**，delta 数 21~38；断开后该会话消息 **0 残留**。"
    "18 条 qa 逐条按闸门口径复核：**0 条**「有来源却零可核查事实」。\n"
    "\n"
    "**成立、不必重做**：合规红线（实际请求体只有 4 个键、`input` 恒等问题文本，"
    "且探针自带 E6/E6b 反向对照——夹一条库内 chunk 必须判红，这让它不是空转）；"
    "「**本地有据不出网**」比我原规格更合规；引用语义（分区 + `site_name_derived` + 代码注入整段声明 + "
    "双路径剥离 `[W<n>]` + 反向断言）；abort 回滚；迁移幂等探针。\n"
    "\n"
    "**四条必修（S2）**：① `STREAM_MIN_SPAN_MS` 降到 ≤150 或改相对判据，并交"
    "「全缓冲 6/6 FAIL、早窗 6/6 PASS」两份连测（阈值 300 是我给的，压在真流式分布内）；"
    "② 报告 JSON 记 `env_flags` + `ss-03` 的 FAIL 文案直接给出该设的变量 + canonical 命令写进记账，"
    "并**如实上报不带钩子那一档的真实结果**（不许藏 53/55）；"
    "③ 归因我这轮多出的 11 条 `ungrounded`（已排除 qa，疑在 `cc-01` 43 轮这类长上下文），"
    "改为**按用例记 gate 命中/失败数**；若确认长上下文大量空话正被 `judge_qa` 放过，"
    "**那是新产品缺陷，本单不许改判据掩盖，列出来我另开单**；"
    "④ 记账更正：忠实度观测区间应扩到 **0.8889~0.9722**（我这轮 0.8889 比已记下限更低，属 judge 抽样非回归）。\n"
    "\n"
    "**责任在我**：单据里「确认 ②③ 都 FAIL」是我写错的——旧实现同样吐 21~43 个 delta，只是挤在 30~80ms，"
    "所以「delta 数 > 1」**无区分力**；实现方如实报告「② 在旧实现上是 PASS」并留双份证据，处理正确。"
    "另两条见上面 ①②。\n"
)
T.insert(k + 1, CONC)
log.append("第 1 回 Review 结论插入")

# ---------------- HANDOFF.md ----------------
P2 = "HANDOFF.md"
H = io.open(P2, encoding="utf-8").read().splitlines(True)
h0 = len([l for l in H if l.strip()])
p = [k for k, l in enumerate(H) if "**下一步 = 等 WorkBuddy 交回「P4e 主体 + S1」**" in l]
assert len(p) == 1, p
H[p[0]] = H[p[0]].replace(
    "**下一步 = 等 WorkBuddy 交回「P4e 主体 + S1」**(分支 `task/P4e-websearch-main`;"
    "S1 是 merge-blocking,必须交**先红后绿两份流式证据 + 三档延迟数字**)",
    "**P4e 主体 + S1 第 1 回复核 = ❌ 打回**(2026-10-01)。功能与红线我实测通过"
    "(出网请求体只有 4 键且 `input` 恒等问题文本、合规探针带 E6/E6b 反向对照、`web_grounded` 4/4 开↔关、"
    "早窗 span 343/574/208ms vs 全缓冲 31/48ms、断开后消息 0 残留、18 条 qa 零「有来源无事实」)，"
    "卡住合并的是**尺子与可复现性**:`STREAM_MIN_SPAN_MS=300`(我给的数)落在真流式实测分布内会随机判红;"
    "「55/55」依赖默认关闭的测试钩子而**报告 JSON 不记 env 标志**(我实测不带钩子是 53/55、退出码 1);"
    "我这轮 `badcases.json` 多出的 **11 条 `ungrounded`** 必须归因(疑在 cc-01 这类 43 轮长上下文)。"
    "打回指令 `docs/p4e/workbuddy-reject-order-main.md`。"
    "**下一步 = 等 WorkBuddy 交回 S2 四条(阈值/可审计/归因/记账)**")
log.append("HANDOFF 下一步更新")

PIT = (
    "63. **给别人的验收阈值，必须自己先跑一遍分布**（2026-10-01 P4e S1）：我裁决「渐进性」判据时定了 "
    "`E2E-TTFB ≥ 300ms`，实现方照做并交回 55/55；可我自己直测早窗档三次是 **343 / 574 / 208ms**，"
    "整轮里也跑出 239ms → **阈值正好压在真流式的分布里面**，而全缓冲档是 31~79ms，两侧真正需要的阈值是 120~150。"
    "更难看的是他们 `docs/P4E.md` 自报早窗中位 **305.4ms**——距离我定的线只有 5ms，**这把尺子从写下那天起就在掷硬币**，"
    "会把刚清掉的「随机红基线」重新带回来（坑 39/45 的延长线：判据不仅要能判红，还要**在噪声两侧都留余量**）。"
    "同一批里还有两个同源缺口：① 我在单据里断言「delta 数 > 1 也该 FAIL」，实测旧实现有 21~43 个 delta，"
    "**这条判据根本没有区分力**，实现方如实报告「② 在旧实现上是 PASS」而没有顺着我的话改用例——这是对的；"
    "② 我要求「全绿且退出码 0」却没写清绿的前提是 `NOVA_GROUNDING_STREAM_FORCE_UNGROUNDED=1`（默认关），"
    "而评测报告 JSON 只记 version/base/summary，**不记 env 标志** → 一份 55/55 无法自证是什么配置跑出来的。"
    "铁律：① **任何阈值定完立刻跑 ≥5 次取分布**，报告最小值与判据线的距离；距离小于噪声半宽就改用相对判据；"
    "② **canonical 命令与生效的 env 标志要和结果同文件留证**（报告里加 `env_flags`）；"
    "③ 交付方报告「你给的判据之一无区分力」时，那是最有价值的反馈，别当顶撞，要写进规格更正。\n"
)
p62 = [k for k, l in enumerate(H) if l.startswith("62. **行尾统一已落地")]
assert len(p62) == 1, p62
H.insert(p62[0] + 1, PIT)
log.append("HANDOFF 坑 63 插入")

h1 = len([l for l in H if l.strip()])
assert h1 > h0
io.open(P, "w", encoding="utf-8", newline="").write("".join(T))
io.open(P2, "w", encoding="utf-8", newline="").write("".join(H))
n = [k for k, l in enumerate(io.open(P2, encoding="utf-8").read().splitlines()) if False]
print(" | ".join(log))
print("TASKS non-blank %d -> %d | HANDOFF %d -> %d" % (nb0, len([l for l in T if l.strip()]), h0, h1))
