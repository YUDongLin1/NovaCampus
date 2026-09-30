#!/usr/bin/env python3
"""P4d-fix ③：忠实度稳定性采样——**同一批答案只重跑 judge**，不重跑产品。

背景（打回指令 ③）：忠实度被观察到同一份代码两轮给出 0.8824 / 0.9412 两个均值，
原实现归因为"judge 学段声明盲区"，被复核方用四条独立证据推翻（graph 开关下答案逐字
相同、judge 调用点零改动、停用词 A/B 来源集合相同、同代码两轮结果不同）。
真实成因是 **judge 抽样抖动**——LLM-as-judge 的分数不是测量值（坑 50）。

本探针：
  1. 现场跑一遍 18 条 qa，**把 (question, answer, sources 含正文) 落盘**（评测报告
     为控体积不存 sources 正文，所以要单独采一次；答案与评测轮同源同温度）；
  2. 对这批**完全相同的输入**重复调 judge N 次；
  3. 输出每条的分数分布 + 全局均值的分布。
  → 同一输入分数跳动 = judge 不稳定的确证；若完全一致，则抖动在产品侧（答案不同），
     需另行归因。**不修改 faithfulness.py**（禁改项），只如实记录分布。

用法: novaagent/.venv/Scripts/python.exe docs/p4d/probe_faithfulness_spread.py [rounds]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx

HERE = Path(__file__).parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT / "evals"))

import faithfulness  # noqa: E402  禁改：只读复用

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
BASE = "http://127.0.0.1:8902"
SNAP = HERE / "evidence" / "after" / "faithfulness_inputs.json"


def collect() -> list[dict]:
    spec = json.loads((ROOT / "evals" / "cases.json").read_text(encoding="utf-8"))
    qa = [c for c in spec["cases"] if c["type"] == "qa"]
    out: list[dict] = []
    with httpx.Client(timeout=180, trust_env=False) as c:
        toks = {}
        for u, p in (("student", "student123"), ("counselor", "counselor123"), ("admin", "admin123")):
            toks[u] = c.post(f"{BASE}/api/login", json={"username": u, "password": p}).json()["token"]
        for case in qa:
            r = c.post(f"{BASE}/api/chat",
                       headers={"Authorization": f"Bearer {toks[case['role']]}"},
                       json={"question": case["question"]})
            r.raise_for_status()
            d = r.json()
            srcs = [{"ref": s.get("ref", ""), "title": s.get("title", ""),
                     "content": s.get("content", "")} for s in (d.get("sources") or [])]
            out.append({"id": case["id"], "question": case["question"],
                        "answer": d.get("answer", ""), "sources": srcs})
            print(f"  采集 {case['id']:8s} answer_len={len(d.get('answer',''))} sources={len(srcs)}")
    SNAP.parent.mkdir(parents=True, exist_ok=True)
    SNAP.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def main() -> int:
    rounds = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    if SNAP.exists():
        items = json.loads(SNAP.read_text(encoding="utf-8"))
        print(f"[input] 复用已采集快照 {SNAP.name}（{len(items)} 条）")
    else:
        print(f"[input] 现场采集 {len(json.loads((ROOT / 'evals' / 'cases.json').read_text(encoding='utf-8'))['cases'])} 条 qa ...")
        items = collect()
    print(f"[judge] 对同一输入重跑 {rounds} 轮（不重跑产品、不改 faithfulness.py）\n")

    per_case: dict[str, list[float]] = {}
    methods: set[str] = set()
    for it in items:
        scores = []
        for _ in range(rounds):
            s, m = faithfulness.judge(it["question"], it["answer"], it["sources"])
            methods.add(m)
            if s is not None:
                scores.append(s)
        per_case[it["id"]] = scores
        if scores:
            rng = f"{min(scores)}~{max(scores)}"
            unstable = " ⚠不稳定" if min(scores) != max(scores) else ""
            print(f"  {it['id']:8s} 重跑={scores} 区间={rng}{unstable}")
        else:
            print(f"  {it['id']:8s} 全部为 None(无来源/空答案,不计入均值)")

    means = []
    for i in range(rounds):
        vals = [per_case[it["id"]][i] for it in items if i < len(per_case[it["id"]])]
        if vals:
            means.append(round(sum(vals) / len(vals), 4))
    print("\n" + "=" * 72)
    print(f"judge 方法: {sorted(methods)}")
    print(f"忠实度均值分布（{rounds} 轮,完全相同输入）: {means}")
    if means:
        verdict = ("→ **同一输入的均值即跳动,确证 judge 抽样不稳定(坑 50)**"
                   if max(means) != min(means) else "→ 本次同输入均值稳定")
        print(f"  区间 {min(means)} ~ {max(means)}  极差 {round(max(means) - min(means), 4)}  {verdict}")
    unstable_cases = [cid for cid, s in per_case.items() if s and min(s) != max(s)]
    print(f"  分值跳动的用例: {unstable_cases or '无'}")

    dest = HERE / "evidence" / "after" / "faithfulness_spread.json"
    dest.write_text(json.dumps(
        {"rounds": rounds, "methods": sorted(methods), "per_case": per_case,
         "mean_spread": means, "mean_range": [min(means), max(means)] if means else None,
         "mean_polarity": round(max(means) - min(means), 4) if means else None,
         "unstable_cases": unstable_cases,
         "note": "同输入重跑 judge；未修改 faithfulness.py；分数是抽样不是测量值"},
        ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[evidence] {dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())