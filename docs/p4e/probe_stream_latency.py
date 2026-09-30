#!/usr/bin/env python3
"""P4e S1-①:三档延迟对照(早窗 / 全缓冲 / 关闭),同一问句各测 N 次。

产出:TTFB(首字)、E2E(收到 done)、delta 事件数、以及服务端 ctx 里的检索段耗时。

三档由**服务端 env** 决定(本探针不改服务端行为):
  早窗   NOVA_GROUNDING_EARLY_WINDOW_CHARS=80  (默认档,S1 修复后)
  全缓冲 NOVA_GROUNDING_EARLY_WINDOW_CHARS=0   (M4 旧行为,回滚对照)
  关闭   NOVA_GROUNDING_GATE=0                 (P4e M4 之前,无闸门)

用法:
    NO_PROXY="127.0.0.1,localhost" \\
    novaagent/.venv/Scripts/python.exe docs/p4e/probe_stream_latency.py \\
        --base http://127.0.0.1:8914 --mode early --runs 3
退出码:0 = 跑完并落盘(不做通过/失败判定;判定在 docs/P4E.md)
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "evals"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError, OSError):
    pass

import httpx  # noqa: E402

import run_evals as R  # noqa: E402

OUT_DIR = ROOT / "docs" / "p4e" / "evidence"
# 与 stream_sse 用例同一问句(两问合并 → 答案长,渐进性可客观测量)
Q = "研究生申请休学需要提交哪些材料？审批流程又是怎样的？"
# P4d 记录的检索路径基线(TTFD 2161 / E2E 2898),见 docs/p4d/evidence/after/latency_compare.txt
P4D_BASELINE_TTFD = 2161
P4D_BASELINE_E2E = 2898


def one(c: httpx.Client, tok: str, warm: bool) -> dict:
    t0 = time.time()
    kinds, delta_t, deltas = [], [], []
    e2e = None
    ctx: dict = {}
    with c.stream("POST", f"{R.BASE}/api/chat/stream",
                  headers={"Authorization": f"Bearer {tok}"}, json={"question": Q}) as r:
        r.raise_for_status()
        for ev in R._sse_events(r):
            t = (time.time() - t0) * 1000
            k = ev.get("type")
            kinds.append(k)
            if k == "delta":
                delta_t.append(t)
                deltas.append(ev.get("content") or "")
            elif k == "done":
                ctx = ev.get("context") or {}
                e2e = t
    if e2e is None:
        e2e = (time.time() - t0) * 1000
    ttfb = delta_t[0] if delta_t else None
    trace = ctx.get("retrieval_trace") or []
    retr_ms = sum(t.get("ms") or 0 for t in trace if t.get("node") == "retrieve")
    return {
        "warm": warm,
        "ttfb_ms": round(ttfb, 1) if ttfb is not None else None,
        "e2e_ms": round(e2e, 1),
        "span_ms": round(e2e - ttfb, 1) if ttfb is not None else None,
        "n_delta": len(deltas),
        "answer_chars": sum(len(d) for d in deltas),
        "retrieval_ms": round(retr_ms, 1),
        "gate": (ctx.get("grounding_gate") or None),
        "released_chars": (ctx.get("grounding_gate") or {}).get("released_chars"),
        "early_window_chars": (ctx.get("grounding_gate") or {}).get("early_window_chars"),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8914")
    ap.add_argument("--mode", default="early")
    ap.add_argument("--runs", type=int, default=3)
    args = ap.parse_args()
    R.BASE = args.base.rstrip("/")

    rows: list = []
    with httpx.Client(timeout=180) as c:
        tok = R.login(c, "student", "student123")
        n = R.seed_corpus_if_needed(c, R.login(c, "counselor", "counselor123"))
        if n:
            print(f"[seed] 播种 {n} 篇")
        for i in range(-1, args.runs):  # 第 -1 次为 warmup,不计入统计
            try:
                r = one(c, tok, warm=(i < 0))
            except Exception as e:  # noqa: BLE001
                print(f"[ERROR] 第 {i} 次: {type(e).__name__}: {e}")
                continue
            print(f"  run{i if i >= 0 else '(warm)'}: TTFB={r['ttfb_ms']}ms E2E={r['e2e_ms']}ms "
                  f"span={r['span_ms']}ms deltas={r['n_delta']} chars={r['answer_chars']} "
                  f"retr={r['retrieval_ms']}ms gate={bool(r['gate'])}")
            if i >= 0:
                rows.append(r)
    if not rows:
        print("[FATAL] 无有效样本")
        return 2

    def med(k):
        v = [r[k] for r in rows if r.get(k) is not None]
        return round(statistics.median(v), 1) if v else None

    agg = {
        "mode": args.mode, "base": R.BASE, "runs": len(rows), "question": Q,
        "ttfb_ms_median": med("ttfb_ms"), "e2e_ms_median": med("e2e_ms"),
        "span_ms_median": med("span_ms"), "n_delta_median": med("n_delta"),
        "answer_chars_median": med("answer_chars"), "retrieval_ms_median": med("retrieval_ms"),
        "ttfb_ms_all": [r["ttfb_ms"] for r in rows],
        "e2e_ms_all": [r["e2e_ms"] for r in rows],
        "span_ms_all": [r["span_ms"] for r in rows],
        "n_delta_all": [r["n_delta"] for r in rows],
        "gate_hit_all": [bool(r["gate"]) for r in rows],
        "rows": rows,
        "p4d_baseline": {"ttfd_ms": P4D_BASELINE_TTFD, "e2e_ms": P4D_BASELINE_E2E},
    }
    print(f"\n[{args.mode}] 中位 TTFB={agg['ttfb_ms_median']}ms  E2E={agg['e2e_ms_median']}ms  "
          f"span={agg['span_ms_median']}ms  deltas={agg['n_delta_median']}")
    if agg["ttfb_ms_median"]:
        d = agg["ttfb_ms_median"] - P4D_BASELINE_TTFD
        print(f"  相对 P4d 检索基线 TTFD {P4D_BASELINE_TTFD}ms: {d:+.1f}ms")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    p = OUT_DIR / f"stream_latency_{args.mode}.json"
    p.write_text(json.dumps(agg, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[report] {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
