#!/usr/bin/env python3
"""P4e S2-③:逐用例 grounding 闸门记账(单独成 commit,便于复核单独审)。

支持 --reverse 用于「先提 S2-①②④、再提 S2-③」的分 commit 流程。

用法:
  novaagent/.venv/Scripts/python.exe docs/p4e/patch_s2_gate_accounting.py [--reverse]
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

P4_OLD = '''                                                                  "history_gate", "followup_no_new_sources",
                                                                  "history_count")}})'''
P4_NEW = '''                                                                  "history_gate", "followup_no_new_sources",
                                                                  "history_count", "grounding_gate")}})'''

P5_OLD = '''                                  ("used", "budget", "compressed", "truncated", "compress_ms",
                                   "compress_blocks", "history_gate", "history_count")}})'''
P5_NEW = '''                                  ("used", "budget", "compressed", "truncated", "compress_ms",
                                   "compress_blocks", "history_gate", "history_count",
                                   "grounding_gate")}})'''

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

P10_OLD = '''             "eval_isolation": {"ok": iso_ok, "checked_conversations": len(conv_cases),
                                "errors": iso_errors}},'''
P10_NEW = '''             "grounding_gate": gate_summary,
             "eval_isolation": {"ok": iso_ok, "checked_conversations": len(conv_cases),
                                "errors": iso_errors}},'''

PAIRS = [("P4", P4_OLD, P4_NEW), ("P5", P5_OLD, P5_NEW), ("P6", P6_OLD, P6_NEW),
         ("P7", P7_OLD, P7_NEW), ("P8", P8_OLD, P8_NEW), ("P9", P9_OLD, P9_NEW),
         ("P10", P10_OLD, P10_NEW)]


def main() -> int:
    rev = "--reverse" in sys.argv
    src = EVALS.read_text(encoding="utf-8")
    for name, old, new in PAIRS:
        a, b = (new, old) if rev else (old, new)
        n = src.count(a)
        if n != 1:
            print(f"[FAIL] {name} {'反向' if rev else '正向'}锚点命中 {n} 次(期望 1)")
            return 1
        src = src.replace(a, b, 1)
    EVALS.write_text(src, encoding="utf-8")
    print(f"[OK] S2-③ 闸门记账已{'移除' if rev else '应用'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
