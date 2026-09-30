#!/usr/bin/env python3
"""P4e S2 交回回执:追加到 docs/TASKS.md(P4f 之前,紧接第一轮回执之后)。

用法: novaagent/.venv/Scripts/python.exe docs/p4e/patch_tasks_receipt_s2.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TASKS = ROOT / "docs" / "TASKS.md"
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError, OSError):
    pass

ANCHOR = "### P4f 辅导员定制（persona）+ 侧边栏重构　📋 READY（待 P4e，设计见 M8）\n"

RECEIPT = """#### P4e S2 交回（WorkBuddy，2026-10-01，第一回被打回后的修复轮）—— **IN_REVIEW**，持棒交回 Qoder

**提交**：`d660271`（S2-①②④）、`5f965f9`（S2-③）。分支仍 `task/P4e-websearch-main`，**未合并 master**。
**工作区**：提交后仅剩运行产物未跟踪（`reports/eval_report_*.json` 三份、`docs/p4e/evidence/*.json` 五份待入），`badcases.json` 已还原。

---

**S2-① 渐进性阈值** ✅ **先修测量，再定阈值**（只降阈值治不好）

复核方指出 300ms 压在真流式分布里（早窗档实测 208/239/343/574，其中 208/239 都 <300 → 随机红）。
我先把两档分布测出来，发现**只调阈值根本解决不了**：

| 问句 | 全缓冲档 span（应 FAIL） | 早窗档 span（应 PASS） | 缝隙 |
|---|---|---|---|
| 原双段问句（答案 110~230 字） | 68 / 97 / 100 / 133 / 151 / 164 ms | 212 / 245 / 252 / 274 / 567 / 627 ms（复核方另测 208/239） | **仅 27%**，120/150/180 都会串档 |
| **三段式长问句**（答案 ~500 字、130~170 delta） | **82 / 94 / 96 / 97 / 98 / 108 ms** | **3044 / 3272 / 3275 / 3309 / 3511 / 4410 ms** | **~28 倍** |

→ 把 `ss-01/02/03` 的问句改成三段式（「材料？审批流程？期满怎么复学？请把每一步的时限和经办部门一并说明。」），
`STREAM_MIN_SPAN_MS` 300 → **150**（≤150 满足要求），此时下侧余量 39%、上侧余量 20 倍。
**验收（两档各连测 6 次）**：全缓冲档 **0/6（6/6 FAIL）**、早窗档 **6/6 PASS**
→ `docs/p4e/evidence/stream_sse_s2_{full6,early6}_long.json`。

⚠ **未采用**复核方给的备选相对判据 `span ≥ max(120, 0.10×E2E)`：本语料 E2E 3.0~6.4s → 300~640ms，
恰好又是"压在分布里"的量级；且该比例会随**检索段变慢**而变严（E2E 5.3s 时要求 span≥530ms），对抖动不稳健。

**S2-② 官方绿可复现、可审计** ✅
- ① `/api/health` 暴露服务端**生效配置** `flags`（gate/早窗/force 钩子/联网默认/超时/graph/model/eval_temperature）；
  评测报告顶层新增 **`env_flags`**（`server` 为服务端权威值 + `client_env` 为客户端 `NOVA_*`）。
  报告顶层键现为 `version/base/summary/results/total_pass/total/env_flags/grounding_gate/eval_isolation`。
- ② `ss-03` 未命中闸门时的 FAIL 文案**直接给出该设哪个变量**（实测输出已含
  "本用例需服务端以 NOVA_GROUNDING_STREAM_FORCE_UNGROUNDED=1 启动…canonical 命令见 docs/TASKS.md … 与 docs/EVAL_BASELINE.md §十九"）。
- ③ canonical 命令写死在 **`docs/EVAL_BASELINE.md` §十九**（含"取退出码不接管道"的正/误写法）
  与本节下方。**⚠ EVAL_BASELINE.md 不在常设白名单，仅在复核方 S2-②③ 显式授权下改，一次性、不留先例。**

**S2-③ 归因新增的 `ungrounded`** ✅ **有结论，不是产品缺陷**

评测报告现在**逐用例 + 逐轮**记账（`result.grounding` 与报告顶层 `grounding_gate`），实测两轮 canonical：

| 轮次 | 闸门命中 | 重生后仍不合格 | 分布 |
|---|---|---|---|
| 第 1 轮 | 15 | **12** | `cc-01` **12/12 全部来自种植轮**（turn5/13/16/17/19/21/22/28/33/37/41/42）；qa-17 1（重生成功） |
| 第 2 轮 | 12 | **9** | `cc-01` 9/9 种植轮；`rewrite-02` 1、`ss-01` 1、`ss-03` 1（**重生均成功，regen_failed=0**） |
| **不带钩子档** | 8 | **0** | 全部重生成功 |

**结论**：`cc-01` 有 42 个**种植轮**（`plant.turns=42`，用于把上下文顶过压缩预算），这些轮的
"问句"是填充文本、答案本就不需要引用与数字，闸门按真实答案的标准判并重生 1 次、仍不合格 → 记 `ungrounded` badcase。
**末轮（真正被 `judge_history_answer` 判的那轮）从未命中闸门**，`cc-01` 四条事实（7341/958823/17340/88号）全部命中、用例 PASS。
→ **不是**"长上下文答案靠无引用无数字通过 judge_qa"；是闸门在**评测填充轮**上的正常触发被记成了 badcase 噪声（坑 56 的技术债延伸）。
**按复核方要求未改判据掩盖**，列待裁决（见下）。

**S2-④ 两处记账** ✅
- ① 忠实度观测区间 **0.8889 ~ 0.9722**（复核方整轮 0.8889 低于我原记的 0.9444 下限；judge 抽样抖动非回归）。已写入 `docs/P4E.md` 与 `EVAL_BASELINE.md` §19.4。
- ② `docs/p4e/evidence/QA12_E2E_DISCREPANCY.md` 顶部加「⚠ 当前结论」块，标明该文件为**历史纪要**、`qa-17` 已裁决落地、只有"端口"那条是长期纪律。

---

**集中验证（全部落地后）**

| 档位 | 命令（canonical 见 §十九） | 结果 |
|---|---|---|
| **canonical（带钩子）** | `NOVA_GROUNDING_STREAM_FORCE_UNGROUNDED=1 bash docs/p4d/run_with_server.sh 8953 ../evals/run_evals.py --base http://127.0.0.1:8953 > /tmp/eval_canonical2.log 2>&1; echo "[EXIT=$?]"` | **`55/55(100%)`、`[CANONICAL2_EXIT=0]`**；R@k 1.0、忠实度 0.9722、拒答 1.0、隔离 47 会话 ok；`env_flags.server.grounding_stream_force_ungrounded=true` |
| **默认（不带钩子）** | 同上但**不带** env，端口 8954 | **`54/55`、exit 1**：仅 `ss-03`（闸门未命中，文案已指明该设哪个变量）；**`ss-01` span=3075ms PASS**（对照：打回前同一档是 239ms FAIL） |
| canonical 第 1 轮（端口 8951） | 同 canonical | 54/55、exit 1：唯一红是 **`qa-08` 措辞轮换**（R@k 1.0、忠实度 1.0、来源全对；单独连测 **5/5 PASS**）→ 坑 16 已知方差，非回归；第 2 轮 55/55 |
| 冒烟 | `bash docs/p4d/run_with_server.sh 8955 ../novaagent/tests/smoke_test.py --base http://127.0.0.1:8955 > /tmp/smoke2.log 2>&1; echo "[EXIT=$?]"` | **`[SMOKE2_EXIT=0]`、`documents 65 → 65`**、[16a] deny_url 回归通过 |

**取退出码一律重定向后 `echo "[EXIT=$?]"`，未接管道**（坑 55）。
整轮前做了单请求自证（`/api/health` flags 齐全 + 流式 `grounding_retry` + `grounding_gate.released_chars=692`）。
`badcases.json` 按主键集合比对（`cases` 主键差集仅新增 `ungrounded` 一案、history 91 vs 70）后 `git checkout --` 还原，
`git hash-object` == `HEAD` blob `7c22c069` == `master` blob。

**端口/进程**：本轮起 `8940/8941`（分布定标）、`8942/8943`（短问句两档，已弃用证据）、`8944/8945`（长问句两档 6 连测）、`8950`（自证）、`8951/8953`（canonical 两轮）、`8952`（qa-08 连测）、`8954`（不带钩子）、`8955`（冒烟），
全部由 `run_with_server.sh` 的 `trap ... EXIT` 收在同一命令生命周期内；收尾 `netstat -ano | grep LISTENING` 复查。

**待裁决（未自行拍板）**
1. **闸门在评测"种植轮"上的触发**要不要豁免（改判据/改记账都属"改判据"，故未动）。建议：种植轮显式标记，badcase 记账区分 turn 类型 —— 请裁决是否另开单。
2. **`NOVA_GROUNDING_STREAM_FORCE_UNGROUNDED` 测试钩子**（沿用上轮裁决项，仍未拍板）。
3. 联网对域外闲聊类问句不生效（沿用上轮）。
4. 联网耗时方差大（沿用上轮）。
5. `qa-08` 轮换波动是**已知方差**，不建议改用例改绿（沿用 HANDOFF 坑 16 口径）。
6. `docs/p4e/evidence/stream_sse_s2_full6.json` 是**短问句 + 漏设 env**的无效样本，已删除不再作为证据。

"""

for_name = "P4e"


def main() -> int:
    src = TASKS.read_text(encoding="utf-8")
    n = src.count(ANCHOR)
    if n != 1:
        print(f"[FAIL] 锚点命中 {n} 次(期望 1)")
        return 1
    TASKS.write_text(src.replace(ANCHOR, RECEIPT + ANCHOR, 1), encoding="utf-8")
    print("[OK] S2 回执已写入 docs/TASKS.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
