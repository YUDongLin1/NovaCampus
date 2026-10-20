#!/usr/bin/env python3
"""P4e M-D:只跑 `web_grounded` 用例(实现期的**针对性最小检查**,不跑整轮)。

复用 `evals/run_evals.py` 的 `run_web_grounded_case`(同一把尺子,坑 59)。

用法:
    NO_PROXY="127.0.0.1,localhost" \\
    novaagent/.venv/Scripts/python.exe docs/p4e/probe_web_grounded.py --base http://127.0.0.1:8921
退出码:0 = 4 条全过;1 = 有 FAIL。
"""
from __future__ import annotations

import os
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

import run_evals as R  # noqa: E402


# ---- 演示口令:一律从环境变量读,源码内不落明文(开源前脱敏要求) ----
def _demo_pw(role: str) -> str:
    r = role.upper()
    pwd = os.environ.get(f"NOVA_SEED_{r}_PASSWORD") or os.environ.get("NOVA_DEMO_PASSWORD", "")
    if not pwd:
        raise RuntimeError(
            f"未设置演示口令:请在 novaagent/.env 中写入 NOVA_DEMO_PASSWORD"
            f"(或 NOVA_SEED_{r}_PASSWORD)。")
    return pwd


ADMIN_PW = _demo_pw("admin")
COUNSELOR_PW = _demo_pw("counselor")
STUDENT_PW = _demo_pw("student")


OUT_DIR = ROOT / "docs" / "p4e" / "evidence"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8921")
    args = ap.parse_args()
    R.BASE = args.base.rstrip("/")
    spec = json.loads((ROOT / "evals" / "cases.json").read_text(encoding="utf-8"))
    cases = [c for c in spec["cases"] if c["type"] == "web_grounded"]
    print(f"[probe] base={R.BASE} cases={[c['id'] for c in cases]}")
    res = []
    with httpx.Client(timeout=180) as c:
        tokens = {"admin": R.login(c, "admin", ADMIN_PW),
                  "counselor": R.login(c, "counselor", COUNSELOR_PW),
                  "student": R.login(c, "student", STUDENT_PW)}
        n = R.seed_corpus_if_needed(c, tokens["counselor"])
        if n:
            print(f"[seed] 播种 {n} 篇")
        for case in cases:
            t0 = time.time()
            try:
                ok, detail, answer, sources, cid, ctx = R.run_web_grounded_case(c, tokens, case)
            except Exception as e:  # noqa: BLE001
                ok, detail, answer, sources, cid, ctx = False, f"{type(e).__name__}: {e}", "", [], None, {}
            print(f"{'[PASS]' if ok else '[FAIL]'} {case['id']:7s} web={case.get('web_search')} {detail}")
            res.append({"id": case["id"], "web_search": case.get("web_search"), "pass": ok,
                        "detail": detail, "answer_head": (answer or "")[:200],
                        "n_local_sources": len(sources or []), "context": ctx,
                        "ms": round((time.time() - t0) * 1000)})
    p = OUT_DIR / "web_grounded_probe.json"
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    npass = sum(r["pass"] for r in res)
    print(f"\n[probe] web_grounded {npass}/{len(res)}   [report] {p}")
    return 0 if npass == len(res) else 1


if __name__ == "__main__":
    sys.exit(main())
