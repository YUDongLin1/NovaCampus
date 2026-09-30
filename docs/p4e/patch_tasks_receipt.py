#!/usr/bin/env python3
"""P4e 主体 + S1 交回回执写进 docs/TASKS.md(P4e 条目下、P4f 之前)。

用法: novaagent/.venv/Scripts/python.exe docs/p4e/patch_tasks_receipt.py
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

RECEIPT = """#### P4e 主体 + S1 交回（WorkBuddy，2026-10-01）—— **IN_REVIEW**，持棒交回 Qoder

**状态**：`IN_REVIEW`｜**当前持棒 = Qoder**｜分支 **`task/P4e-websearch-main`**｜**未合并 `master`**（基线仍是 `master` `9685b0d`）
**提交**：`c65f771`（S1-① 早窗提交 + S1-② 流式覆盖）、`467bbae`（P4e 主体：websearch/开关/分区/合规）+ 本回执与 `docs/P4E.md`
**工作区**：提交后仅剩 `reports/eval_report_20261001_003548.json` 一个**未跟踪运行产物**（按既有纪律不入库），其余干净；`evals/badcases.json` 已还原（见下）

---

**S1-① 早窗提交（merge-blocking）** ✅

| 项 | 落点 | 证据/字段 |
|---|---|---|
| 早窗控制器 | `novaagent/novaagent/agent.py` `_StreamGate`（`feed/_release/flush/grounded/need_regen`） | 纯逻辑无 IO，可单测 |
| delta 放行规则 | 同文件 `chat_stream_for`：`for seg in gate.feed(safe): yield delta` | 出现首个 `[n]`/数字 **或** 累计满 N 字即补发 |
| 重生仍走流式 | 重生改 `llm.chat_stream(regen_messages(...))`，逐段下发 | 探针实测 retry 后 10~50 个 delta |
| 显式重试事件 | `yield {"type":"grounding_retry","released_chars":N,"n_sources":k}` | `evidence/stream_sse_after.json` |
| 前端不假装没发生 | `web/js/chat.js`：`grounding_retry` → 初稿折进 `.gate-draft`（保留可见）+ 状态行「（初稿未给出可核查依据，已重新组织答案如下）」，重生结果另起一段；`css/theme.css` `.gate-draft/.gate-status` | 同文件 |
| env 开关 | `config.py` `NOVA_GROUNDING_EARLY_WINDOW_CHARS`（默认 **80**，0=退回全缓冲）、`NOVA_GROUNDING_GATE`（0=关闸门）、`NOVA_GROUNDING_STREAM_FORCE_UNGROUNDED`（测试钩子，默认关） | 同文件 |
| 闸门语义未弱化 | 仍最多重生一次、仍写 `ctx_info["grounding_gate"]`（含 `early_window_chars`/`released_chars`）、重生后仍不合格 → 保留答案 + `flag=ungrounded_after_regen` + `record_ungrounded` | `probe_stream_gate_unit.py` U1~U4 |

**N=80 的理由**：可核查事实在据实作答时几乎总在首句内出现（本项目 qa 答案首句 40~120 字），80 字让「首个事实」大概率落在窗口内；最坏也只憋 1~2 句而非整段 200~400 字。60/80 两档都实测了（见下表）。

**三档延迟对照**（`docs/p4e/evidence/stream_latency_{full,early80,early60,off}.json`，warmup1 + 连测3 取中位，各档独立端口独立实例）：

| 档位 | env | TTFB 中位 | E2E 中位 | **span 中位** | delta 中位 |
|---|---|---|---|---|---|
| 全缓冲（M4 旧行为） | `NOVA_GROUNDING_EARLY_WINDOW_CHARS=0` | 3380.6ms | 3452.0ms | **88.9ms** | 21 |
| **早窗 80（默认）** | `=80` | 2786.6ms | 3092.0ms | **305.4ms** | 25 |
| 早窗 60（N 取值对照） | `=60` | 2810.5ms | 3267.8ms | **457.3ms** | 27 |
| 关闭（无闸门） | `NOVA_GROUNDING_GATE=0` | 2355.5ms | 3001.6ms | **638.8ms** | 27 |

相对 P4d 基线 **TTFD 2161ms**：早窗 +625.6ms、全缓冲 +1219.6ms、关闭 +194.5ms。
**如实读数**：span 88.9 → 305.4ms（3.4×）、TTFB −17.6% → 真流式恢复；但**未回到关闭档**，差的 ~430ms 是闸门真实代价（本问句答案仅 110~140 字，80 字窗口覆盖大半、首个事实出现偏晚）。全缓冲档 span 88.9ms 与复核方独立实测 36ms 同量级，相互印证。

**S1-② 流式端点自动化覆盖** ✅ **先红后绿两份输出**（同一把尺子：`docs/p4e/probe_stream_sse.py` 直接 `import run_evals` 复用 `run_stream_case`，坑 59）

| 用例 | 红（`evidence/stream_sse_before.json`，0/3） | 绿（`_after.json`，3/3） |
|---|---|---|
| ss-01 ①②③ | `E2E-TTFB=73ms < 300ms`（TTFB 2992 / E2E 3064 / deltas 21） | `TTFB=2658 E2E=3576 span=918 deltas=37 retry=True` |
| ss-02 ④ | 断开后仍残留 1 条 user + 1 条 assistant（**旧实现根本没有中断窗口**） | 会话 1270 消息数 0 → 回滚成立 |
| ss-03 ⑤ | 无 `grounding_retry`（旧实现无此事件） | `deltas=50 retry=True gate=True`，落库答案 == done.answer |

⚠ **对单据预期的一处如实更正**：单据写「确认 ②③ 确实 FAIL」，实测 **② 在旧实现上是 PASS**（旧实现有 21 个 delta，只是全挤在最后 73ms）——「delta 数 > 1」防的是「整段合成一个 delta」，**防不住「21 个 delta 集中下发」**；真正判红的是 ③。故 ③ 的阈值**未按单据原文的「> 0」**（旧实现也有 73ms > 0）而取 **300ms**：关闭档 638.8 / 早窗档 305.4 / 全缓冲档 88.9，300ms 能把三档干净分开。
另：`probe_stream_gate_unit.py` 在**库副本**上进程内驱动 `chat_stream_for`，12 条断言（U1~U7）确定性全过、退出码 0，**不依赖任何钩子**。

**M-A 引用语义（分区展示 + 整段级标注）** ✅

| 项 | 落点 | 证据 |
|---|---|---|
| 联网来源单独分区、真实 URL 可点 | `websearch.build_web_sources()` → `{index, ref:"W1..Wk", url, site_name, site_name_derived, note}`；前端 `chat.js renderMeta` 渲染「联网来源（公网检索，未经本校核实）」分区，与「知识库来源」分区分开 | `probe_web_citation_ruler.py` R6/R6b/R6c |
| `site_name` 由 `urlparse().netloc` 推导并标注 | `websearch.derive_site_name()` + `site_name_derived=True`；UI 显示「站点名由 URL 推导（上游只返回 URL）」 | 同上 |
| `index` 仅作列表编号、不与本地 `[1..n]` 混 | `ref` 用 `W1..Wk`，本地用数字 | 评测 `run_web_grounded_case` 断言 `ws["ref"] not in local_refs` |
| **不得**把 `[W<n>]` 绑到具体句子 | `agent.strip_web_citations()`（非流）+ `_StreamRefFilter(drop_web=)`（流内）双路径**代码剥离**；反向断言 `run_evals._W_CITATION_RE` | **wg-01 首轮实测模型写出 `[W3]`、反向断言当场判红** → 与 P4a 同源「prompt 挡不住，必须落代码」 |
| 整段级声明「未经本校核实」 | `agent.WEB_DECLARE` 由**代码注入**（同 P4a C8 手法），流式另发一个 delta | `probe_web_citation_ruler.py` R7；评测 `expect_web_declaration` |
| 理由入档 | **`docs/P4E.md` §2.2** | 上游零角标/零内联 URL/`annotations` 空 → 无「句子↔URL」映射，自建映射是假精确 |

**M-B 开关** ✅ 默认**关闭**（`config.WEB_SEARCH_ENABLED` 默认 False）；优先级 = **单次请求覆盖 `body.web_search` > 用户级 `user_settings.web_search_enabled` > 全局默认**；`main._web_search_override` / `main._web_on`；`/api/me/settings` GET 暴露 `web_search_enabled`、PUT 接受 `web_search`；UI composer 开关**当前状态可见**（「开/关」）且改动即持久化。迁移只在 `db.py` 启动期 `_migrate()` 内（幂等），`probe_db_migration.py` 在**库副本**上连跑两遍 schema/数据逐字段一致（8 条全过，退出码 0），既有用户默认 `''`→ 回落全局「关」，不误开。

**M-C 降级可观测** ✅ 联网只是**本地拒答后的补充通道**（本地有据**不出网**）；超时/失败/零来源 → 维持拒答 + 追加「（已尝试联网检索，但本次联网搜索不可用或未返回结果…）」；`ctx_info` 恒记 **`web_called / web_ms / web_n_sources / web_error`**（另加 `web_enabled / web_fallback / web_unavailable / web_citations_stripped`）；失败一律 `logger.warning`，不静默兜底（坑 46/47）。超时默认 60s 的实测依据：同一问句两次 12.3s / 79.4s，DOI 问句 68.4s。

**M-D 评测 `web_grounded` 4 条（开/关对照）** ✅

| 用例 | 开关 | 断言 | 实测 |
|---|---|---|---|
| wg-01 | 开 | `web_called=True`、联网 ≥1 条且 URL 可点、`site_name_derived`、含「未经本校核实」、命中 GDP/国内生产总值 | `web_ms=11647, 联网 8 条` |
| wg-02 | **关** | 走 P4a 确定性模板（指纹「系统模板生成」）、**绝不发起联网请求** | `web_called=False, 联网 0 条` |
| wg-03 | 开 | 同上（第二条：CPI / 居民消费价格指数） | `web_ms=4503, 联网 7 条` |
| wg-04 | **关** | 同 wg-02 | `web_called=False` |

四条**都带反向断言**（正文不得出现逐句绑定的 `[W<n>]`，命中即 FAIL）。问句为构造的公开知识题（校园框定型），**非真实学工问句**。
⚠ 问句**为什么加校园框定**：纯域外问法「ISO 4217…」被意图分类器判为 `chitchat` → 走 `direct` 直答，**根本到不了「本地拒答 → 联网」这条链**（实测 `intent='chitchat', retrieval_skipped=True`）。

**M-E 合规红线（C 级，读代码追）** ✅ `docs/p4e/probe_web_compliance.py`，抓 `httpx.AsyncClient.post` 拿**实际请求体**：顶层键 == `{model, input, tools, tool_choice}`；`input` **逐字等于**当前问题文本；请求体每个字符串值不含库内 chunk / 会话历史（预埋姓名+学号+手机号）/ 系统提示词 / 联网区块模板 / `contacts.json`。**21 条全过、退出码 0**：L2a 本地有据 → 新增联网 0 次；L2c 开关关 → 0 次；E6 反向（chunk 塞进 input → 同一把尺子判红）；E6b 干净体判绿。⚠ 尺子修过一次：`json.dumps` 会把 chunk 的 `\\n` 转义导致含换行样本**永远匹配不上**、尺子静默空转（坑 45 同形状），现改为递归比对字符串原值。

---

**集中验证（全部落地后一轮）**

| 项 | 结果 | 怎么测的 |
|---|---|---|
| 整轮评测 | **`55/55(100%)`、退出码 0** | `NOVA_GROUNDING_STREAM_FORCE_UNGROUNDED=1 bash docs/p4d/run_with_server.sh 8931 ../evals/run_evals.py --base http://127.0.0.1:8931 > /tmp/eval_full.log 2>&1; echo "[EVAL_EXIT=$?]"` → **`[EVAL_EXIT=0]`，重定向前**、**没有接管道**（坑 55） |
| 分类 | qa 18/18、refusal 6/6、permission_api 4/4、kb_hidden 3/3、refusal_indomain 6/6、multiturn 1/1、refusal_followup 1/1、history_false_premise 1/1、context_compress 1/1、scoped_qa 3/3、intent 2/2、rewrite 2/2、**stream_sse 3/3**、**web_grounded 4/4** | 同上日志 |
| Recall@k / 忠实度 / 拒答 | **1.0 / 0.9444(llm) / 1.0**；忠实度按区间 0.9444~0.9722 读，未作闸门 | 同上 |
| 评测隔离 | **47 个带会话用例全量核对通过**（message id 全局唯一、首问逐字匹配、user 条数=应发轮数） | 同上 |
| 整轮前自证 | 单请求 `/api/chat` 见 `web_enabled/web_called/web_ms/web_n_sources/web_error` + 响应顶层 `web_sources`；`/api/chat/stream` 见 `grounding_retry`（`released_chars=88`）与 `grounding_gate.early_window_chars=80` → **确认连的是新实例**（坑 57） | `/tmp/selfcheck.py`，端口 8930 |
| 冒烟 | **exit 0、`documents 65 → 65`**、[16a] `deny_url` 回归通过 | `bash docs/p4d/run_with_server.sh 8932 ../novaagent/tests/smoke_test.py --base http://127.0.0.1:8932 > /tmp/smoke.log 2>&1; echo "[SMOKE_EXIT=$?]"` → **`[SMOKE_EXIT=0]`，未接管道** |
| 库计数 | 评测+冒烟跑完后 `kb_doctor` → **documents=65 / chunks=487**（未并发跑只读探针，坑 58） | 独立串行跑 |
| 坑 56 | `evals/badcases.json` 按**主键集合**比对：cases 主键差集双向为空、history 70→70、非 `history/last_seen` 字段无变化 → 纯运行时副作用，已 `git checkout --` 还原；`git hash-object` == `HEAD` blob `7c22c069` == `master` blob | 见下注 |

> ⚠ 关于 `af6fe699…`：上一轮回执记的 badcases 基线 md5 与我按 `git show master:evals/badcases.json | md5sum` 得到的 `b5c5245…` 不一致（工作区 CRLF vs blob LF，坑 36）。本轮改用 **git blob 身份**判等价（权威口径），结论：工作区 == HEAD == master，**未提交任何 badcases 改动**。

**端口/进程交代**（坑 61 姿势）

- 本轮起过的端口：`8912`（红灯基线）、`8913`（绿灯）、`8914/8915/8916`（首轮三档，已删 `early` 那份证据）、`8917/8918/8919/8920`（修正后四档）、`8921/8923/8924/8925/8926`（web_grounded 迭代）、`8922`（意图路由排查）、`8930`（整轮前自证）、`8931`（整轮评测）、`8932`（冒烟）。
- **全部由 `docs/p4d/run_with_server.sh` 的 `trap 'kill $SRV' EXIT` 收在同一条命令生命周期内**，命令结束后随 shell 退出。
- **收尾复查**（`netstat -ano | grep LISTENING`）：8900~8939 区间**仅剩 `127.0.0.1:8900`（PID 41956，他人常驻，15:40 起）在听**，我起的端口**无一存活**；`:8900` 与 weekly MCP `:18080` **全程未动**。
- 未使用 Git Bash `kill <Windows PID>`（坑 61）；如需强制清理会用 `taskkill //PID x //F` 并复查端口。

**禁改项**：`git diff --numstat master..HEAD -- sims/ mcp/ weknora/ evals/faithfulness.py novaagent/novaagent/refusal.py` → **输出为空**。

**遗留与需裁决项（未自行拍板）**

1. **`NOVA_GROUNDING_STREAM_FORCE_UNGROUNDED` 测试钩子**：为让 stream_sse ⑤ 必然被执行而加（默认关、仅流式首版、重生仍走真实 LLM）。若不接受生产代码里留测试钩子，替代方案是只保留 `probe_stream_gate_unit.py` 的进程内桩件，评测侧 ⑤ 退化为「闸门命中 ⇔ retry 出现」的一致性断言（恒绿但证明力弱）。**请裁决**。
2. **联网对「域外闲聊类问句」不生效**：被意图分类器判 `chitchat` 的问句走 `direct` 直答，联网开了也不触发。覆盖需扩意图类别（如 `web_fact`），会动 `INTENT_PROMPT` 与既有 intent/rewrite 用例 —— **建议下单一并做，本单未做**。
3. **v2.4 口径变更（48 → 55 条）尚未在 `docs/EVAL_BASELINE.md` 与 `HANDOFF.md`「评测基线」行记账**：这两个文件**不在本单白名单**，故未改（坑 40 要求同步）。**请裁决由谁补**。
4. **联网耗时方差极大**（同问句 12.3s / 79.4s），`web_grounded` 已挑实测快的问句，但整轮时长仍随网络波动（本轮 7m25s）。
5. `docs/p4e/evidence/QA12_E2E_DISCREPANCY.md` 状态已过时（C0 遗留），本单未改写历史纪要。
6. `reports/eval_report_20261001_003548.json` 按纪律不入库（运行产物）。

"""

for_name = "P4e"


def main() -> int:
    src = TASKS.read_text(encoding="utf-8")
    n = src.count(ANCHOR)
    if n != 1:
        print(f"[FAIL] 锚点命中 {n} 次(期望 1)")
        return 1
    TASKS.write_text(src.replace(ANCHOR, RECEIPT + ANCHOR, 1), encoding="utf-8")
    print("[OK] 回执已写入 docs/TASKS.md(P4e 条目下)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
