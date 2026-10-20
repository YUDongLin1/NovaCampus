#!/usr/bin/env python3
"""P4e S2-①/②/③:evals 侧三条尺子与可审计性修复。

  S2-① STREAM_MIN_SPAN_MS 300 → 150(阈值必须落在两侧分布之外,依据见常量注释)
  S2-② ss-03 未命中闸门的 FAIL 文案直接给出该设哪个 env;报告 JSON 加 env_flags
  S2-③ 逐用例记录 grounding_gate 命中数 / 重生失败数(不再靠 badcases 反推,坑 18/56)

用法: novaagent/.venv/Scripts/python.exe docs/p4e/patch_s2_eval.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVALS = ROOT / "evals" / "run_evals.py"
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError, OSError):
    pass

# ---------------- S2-① 阈值 ----------------
P1_OLD = '''#   ③ E2E - TTFB >= STREAM_MIN_SPAN_MS —— 防「12 个 delta 挤在最后 36ms」(真流式被关掉)。
#      ⚠ 单据原文写的是「之差 > 0」,但实测旧实现 E2E-TTFB 也有 36ms(12 个 delta 集中在最后),
#        「>0」判不出旧实现 → 必须给阈值。300ms 的取值理由见 docs/P4E.md §S1。
'''
P1_NEW = '''#   ③ E2E - TTFB >= STREAM_MIN_SPAN_MS —— 防「21 个 delta 挤在最后 73ms」(真流式被关掉)。
#
#      【阈值为什么从 300 降到 150】300 是复核方拍的数,实测**压在真流式分布里面**:
#        全缓冲档(M4 旧行为) 逐次 span: 66.5 / 71.7 / 87.8 / 94.3 / 103.2 / 109.4 ms
#                                      (历史另见 70.9 / 71.4 / 118.9 / 73 / 79 / 31 / 48)
#        早窗档(默认)         逐次 span: 212.3 / 244.6 / 252.0 / 274.2 / 567.3 / 626.8 ms
#                                      (复核方另测 208 / 239 / 343 / 574)
#      → 全缓冲观测上界 118.9ms、早窗观测下界 208ms。取 **150ms**:
#        下侧余量 31ms(26%)、上侧余量 58ms(28%),两侧都留有余量。
#        取 300 时早窗档 208~274ms 那几次会**随机 FAIL** —— 等于把刚清掉的随机红又带回来。
#      证据: docs/p4e/evidence/stream_latency_span_{full,early80}.json(两档各连测 6 次)。
#
#      ⚠ 单据原文写的是「之差 > 0」,实测旧实现也有 31~119ms(>0),判不出 → 必须给阈值。
#      ⚠ **未采用**复核方给的备选相对判据 `span >= max(120, 0.10 × E2E)`:本语料 E2E ≈ 3.0~3.5s,
#        0.10×E2E = 300~350ms —— 恰好就是被判定为"压在分布里"的那个值。相对判据要成立,
#        比例需降到 ≈0.04(0.04×3153 ≈ 126ms)。此处取绝对阈值更可解释,故不采用。
STREAM_MIN_SPAN_MS = 150
'''
# 常量定义行本身也要改(上面的注释块只替换注释,真正的赋值在下一行)
P1B_OLD = 'STREAM_MIN_SPAN_MS = 300\n'
P1B_NEW = ''

# ---------------- S2-② ss-03 文案 ----------------
P2_OLD = '''        if not gate.get("hit"):
            bad.append(f"grounding_gate 未命中(gate={gate or '无'}) → 无法验证重生通道")
'''
P2_NEW = '''        if not gate.get("hit"):
            bad.append(
                "grounding_gate 未命中 → 无法验证重生通道。"
                "本用例需服务端以 NOVA_GROUNDING_STREAM_FORCE_UNGROUNDED=1 启动才**必然**命中;"
                "canonical 命令见 docs/TASKS.md P4e 回执与 docs/EVAL_BASELINE.md §十九。"
                f"当前 gate={gate or '无'}")
'''

# ---------------- S2-② 报告 env_flags ----------------
P3_OLD = '''        n = seed_corpus_if_needed(c, counselor)
        if n:
            print(f"[seed] 播种评测语料 {n} 篇")
'''
P3_NEW = '''        # P4e S2-②: **服务端**配置才是权威(客户端 env 可能与服务端不一致,坑 57 同源)
        server_flags: dict = {}
        try:
            hr = c.get(f"{BASE}/api/health")
            hr.raise_for_status()
            server_flags = (hr.json() or {}).get("flags") or {}
        except Exception as e:  # noqa: BLE001
            print(f"[warn] 取服务端 flags 失败({type(e).__name__}),env_flags 只含客户端 env")
        env_flags = {
            "server": server_flags,
            "client_env": {k: v for k, v in os.environ.items() if k.startswith("NOVA")},
        }
        print(f"[env_flags] server={server_flags}")
        n = seed_corpus_if_needed(c, counselor)
        if n:
            print(f"[seed] 播种评测语料 {n} 篇")
'''

P3B_OLD = '''            {"version": spec["version"], "base": BASE, "summary": summary,
             "total_pass": total_pass, "total": total, "results": results,
             "eval_isolation": {"ok": iso_ok, "checked_conversations": len(conv_cases),
                                "errors": iso_errors}},'''
P3B_NEW = '''            {"version": spec["version"], "base": BASE, "summary": summary,
             "total_pass": total_pass, "total": total, "results": results,
             # P4e S2-②: 报告自带"当时是什么配置",否则后人拿到 55/55 无法判断怎么跑出来的
             "env_flags": env_flags,
             "grounding_gate": gate_summary,
             "eval_isolation": {"ok": iso_ok, "checked_conversations": len(conv_cases),
                                "errors": iso_errors}},'''

# ---------------- S2-③ 逐用例闸门口径 ----------------
P4_OLD = '''                                                                  "history_gate", "followup_no_new_sources",
                                                                  "history_count")}})'''
P4_NEW = '''                                                                  "history_gate", "followup_no_new_sources",
                                                                  "history_count", "grounding_gate")}})'''

P5_OLD = '''                                  ("used", "budget", "compressed", "truncated", "compress_ms",
                                   "compress_blocks", "history_gate", "history_count")}})'''
P5_NEW = '''                                  ("used", "budget", "compressed", "truncated", "compress_ms",
                                   "compress_blocks", "history_gate", "history_count",
                                   "grounding_gate")}})'''

# collect_gate 函数(插在 run() 之前)
P6_OLD = "\ndef run() -> int:\n    global BASE\n"
P6_NEW = '''

def collect_gate(case_id: str, last_ctx: dict, turn_ctxs: list) -> dict:
    """P4e S2-③:逐用例统计 grounding 闸门命中数 / 重生后仍不合格数。

    为什么不再用 `evals/badcases.json` 反推(坑 18/56):badcases 是**服务端**按 50 条滚动
    写的,分不清是哪条用例、哪一轮(种植轮也算)贡献的 —— 复核方因此只能猜"最可疑是 cc-01"。
    这里改成评测侧直接记账:每个用例、每一轮(含 context_compress 的 43 个种植请求)都留痕。
    """
    out = {"hits": 0, "regen_failed": 0, "stages": []}
    pairs = [(last_ctx or {}, "final")]
    for i, tc in enumerate(turn_ctxs or []):
        pairs.append((tc or {}, f"turn{i + 1}"))
    for ctx, stage in pairs:
        g = (ctx or {}).get("grounding_gate")
        if not isinstance(g, dict) or not g.get("hit"):
            continue
        out["hits"] += 1
        if g.get("flag") == "ungrounded_after_regen":
            out["regen_failed"] += 1
        if len(out["stages"]) < 40:
            out["stages"].append({"stage": stage, "n_sources": g.get("n_sources"),
                                  "ok_after_regen": g.get("ok_after_regen"),
                                  "flag": g.get("flag")})
    return out


def run() -> int:
    global BASE
'''

P7_OLD = '''            results.append({**case, "pass": ok, "detail": detail,
                            "recall_at_k": recall,
                            "faithfulness": faith, "faithfulness_method": fmethod,
                            "conversation_id": conversation_id,
                            "first_question": first_question,
                            "turns_sent": turns_sent,
                            "last_context": last_ctx,
                            "turn_contexts": turn_ctxs if case["type"] in CHAT_TURN_TYPES else [],
                            "latency_ms": round((time.time() - t0) * 1000)})'''
P7_NEW = '''            gstat = collect_gate(case["id"], last_ctx, turn_ctxs)
            gate_summary["total_hits"] += gstat["hits"]
            gate_summary["total_regen_failed"] += gstat["regen_failed"]
            if gstat["hits"]:
                gate_summary["by_case"][case["id"]] = gstat
            results.append({**case, "pass": ok, "detail": detail,
                            "recall_at_k": recall,
                            "faithfulness": faith, "faithfulness_method": fmethod,
                            "conversation_id": conversation_id,
                            "first_question": first_question,
                            "turns_sent": turns_sent,
                            "last_context": last_ctx,
                            "turn_contexts": turn_ctxs if case["type"] in CHAT_TURN_TYPES else [],
                            "grounding": gstat,
                            "latency_ms": round((time.time() - t0) * 1000)})'''

P8_OLD = '''        results = []
        for case in cases:
'''
P8_NEW = '''        results = []
        # P4e S2-③: 闸门命中/重生失败按用例记账(打印在末尾,便于定位 cc-01 那 43 个请求)
        gate_summary: dict = {"total_hits": 0, "total_regen_failed": 0, "by_case": {}}
        for case in cases:
'''

P9_OLD = '''        print(f"  Recall@k 均值: {summary['recall_at_k_avg']} | 忠实度均值: {summary['faithfulness_avg']}"
              f"({summary['faithfulness_method']}) | 拒答准确率: {summary['refusal_accuracy']}")
'''
P9_NEW = '''        print(f"  Recall@k 均值: {summary['recall_at_k_avg']} | 忠实度均值: {summary['faithfulness_avg']}"
              f"({summary['faithfulness_method']}) | 拒答准确率: {summary['refusal_accuracy']}")
        print(f"[P4e S2-③ grounding 闸门] 命中 {gate_summary['total_hits']} 次, "
              f"重生后仍不合格 {gate_summary['total_regen_failed']} 次")
        for cid_, gs in gate_summary["by_case"].items():
            print(f"    - {cid_:10s} hits={gs['hits']} regen_failed={gs['regen_failed']} "
                  f"stages={[(s['stage'], s.get('flag')) for s in gs['stages'][:6]]}")
'''

# import os
P10_OLD = "import json\nimport re\nimport sys\nimport time\n"
P10_NEW = "import json\nimport os\nimport re\nimport sys\nimport time\n"

PAIRS = [("P1", P1_OLD, P1_NEW, 1), ("P1B", P1B_OLD, P1B_NEW, 1),
         ("P2", P2_OLD, P2_NEW, 1), ("P3", P3_OLD, P3_NEW, 1), ("P3B", P3B_OLD, P3B_NEW, 1),
         ("P4", P4_OLD, P4_NEW, 1), ("P5", P5_OLD, P5_NEW, 1),
         ("P6", P6_OLD, P6_NEW, 1), ("P7", P7_OLD, P7_NEW, 1),
         ("P8", P8_OLD, P8_NEW, 1), ("P9", P9_OLD, P9_NEW, 1), ("P10", P10_OLD, P10_NEW, 1)]


def main() -> int:
    src = EVALS.read_text(encoding="utf-8")
    for name, old, new, cnt in PAIRS:
        n = src.count(old)
        if n != cnt:
            print(f"[FAIL] {name} 命中 {n} 次(期望 {cnt})")
            return 1
        src = src.replace(old, new, 1)
    EVALS.write_text(src, encoding="utf-8")
    print("[OK] evals: S2-① 阈值 150 / S2-② 文案+env_flags / S2-③ 逐用例闸门口径")
    return 0


if __name__ == "__main__":
    sys.exit(main())
