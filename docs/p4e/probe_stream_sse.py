#!/usr/bin/env python3
"""P4e S1-② 流式端点探针:只跑 `stream_sse` 用例,产出「先红后绿」两份证据。

⚠ 本探针**不自带第二把尺子** —— 它直接 import `evals/run_evals.py` 的 `run_stream_case`
并复用其 `login`/`seed_corpus_if_needed`,保证「先红」与「后绿」过的是**同一把尺子**
(HANDOFF 坑 59:改进后的断言要和原断言过同一把尺子)。

用法(项目 venv):
    NO_PROXY="127.0.0.1,localhost" \\
    novaagent/.venv/Scripts/python.exe docs/p4e/probe_stream_sse.py \\
        --base http://127.0.0.1:8912 --tag before
退出码:0 = 3 条全过;1 = 有 FAIL;2 = 执行异常。
证据落盘:docs/p4e/evidence/stream_sse_<tag>.json
"""
from __future__ import annotations

import argparse
import json
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

import run_evals as R  # noqa: E402  (模块级只有 BASE/常量与 faithfulness 导入,无副作用)

OUT_DIR = ROOT / "docs" / "p4e" / "evidence"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8912")
    ap.add_argument("--tag", default="before")
    ap.add_argument("--only", default="")
    args = ap.parse_args()
    R.BASE = args.base.rstrip("/")

    spec = json.loads((ROOT / "evals" / "cases.json").read_text(encoding="utf-8"))
    cases = [c for c in spec["cases"] if c["type"] == "stream_sse"]
    if args.only:
        cases = [c for c in cases if c["id"] in args.only.split(",")]
    print(f"[probe] base={R.BASE}  cases={[c['id'] for c in cases]}  tag={args.tag}")

    out: dict = {"tag": args.tag, "base": R.BASE, "cases": [], "pass": 0, "total": 0}
    with httpx.Client(timeout=180) as c:
        tokens = {"admin": R.login(c, "admin", "admin123"),
                  "counselor": R.login(c, "counselor", "counselor123"),
                  "student": R.login(c, "student", "student123")}
        n = R.seed_corpus_if_needed(c, tokens["counselor"])
        if n:
            print(f"[seed] 播种 {n} 篇")
        for case in cases:
            t0 = time.time()
            try:
                ok, detail, answer, sources, cid, ctx = R.run_stream_case(c, tokens, case)
            except Exception as e:  # noqa: BLE001
                ok, detail, answer, sources, cid, ctx = False, f"{type(e).__name__}: {e}", "", [], None, {}
            mark = "[PASS]" if ok else "[FAIL]"
            print(f"{mark} {case['id']:8s} [{case.get('stream_kind')}] {detail}")
            out["cases"].append({"id": case["id"], "kind": case.get("stream_kind"), "pass": ok,
                                 "detail": detail, "answer_len": len(answer or ""),
                                 "n_sources": len(sources or []), "conversation_id": cid,
                                 "context": ctx, "ms": round((time.time() - t0) * 1000)})
            out["total"] += 1
            out["pass"] += int(ok)
    print(f"\n[probe] stream_sse {out['pass']}/{out['total']}  (tag={args.tag})")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    p = OUT_DIR / f"stream_sse_{args.tag}.json"
    p.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[report] {p}")
    return 0 if out["pass"] == out["total"] else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # noqa: BLE001
        print(f"[FATAL] {type(e).__name__}: {e}")
        sys.exit(2)
