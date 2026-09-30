#!/usr/bin/env python3
"""P4e M4 验证：生成出口 grounding 闸门对 qa-17 的实际效果（连测 N 次）。

【背景】C0 交回时 qa-17 在正确 12 槽下 5 连测 FAIL=2/5（非抖动）——生成侧偶发只输出
「学段声明 + 免责」而不复述正文条款。第二回打回裁决：**不选 A（放宽判据）**，
选 **B 的代码化版本**（铁律「判定放代码，不放 prompt」，P4a C1 / 坑 21）：
有来源却零 [n] 零数字 → 判无效 → 触发**一次**重生 → 仍不合格则保留答案 + trace flag + 记 badcase。

【本探针做什么】起本分支代码的服务，连测 qa-17 N 次，逐次记录：
  - 答案是否 grounded（有 [n] 或数字）
  - ctx_info.grounding_gate 是否命中（闸门有没有出手）
  - 评测侧非答案判据会不会判红（与 evals/run_evals.py 同一把尺子）
  - 关键词/来源是否仍正确（闸门不得破坏检索侧）
并额外做**反向用例**：故意问一个库里没有的（走拒答路径），确认闸门**不介入**拒答。

用法（路径相对 novaagent/，run_with_server.sh 内部会 cd）：
  bash docs/p4d/run_with_server.sh 8902 ../docs/p4e/probe_qa17_gate.py --base http://127.0.0.1:8902 --n 10
落盘：docs/p4e/evidence/qa17_gate.json    退出码：0（取证脚本恒 0，判红是发现不是脚本失败）
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs" / "p4e" / "evidence" / "qa17_gate.json"
CASE_ID = "qa-17"
FACTUAL = re.compile(r"\[\d+\]|\d")
# 与 evals/run_evals.py NON_ANSWER_MARKS 逐字一致（不 import 评测脚本：它有模块级 BASE 副作用）
MARKS = (
    "未在知识库", "未检索到", "没有检索到", "未覆盖", "没有覆盖", "未收录", "未包含",
    "知识库中未", "暂无", "没有找到", "无法回答", "不在知识库", "没有相关",
    "请以", "建议咨询", "请咨询", "无法提供", "以学校现行", "以研究生主管部门", "以保卫处",
)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError, OSError):
    pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8900")
    ap.add_argument("--n", type=int, default=10)
    args = ap.parse_args()
    base = args.base.rstrip("/")

    cases = json.loads((ROOT / "evals" / "cases.json").read_text(encoding="utf-8"))["cases"]
    case = next(c for c in cases if c["id"] == CASE_ID)
    # 反向用例：库里没有的（问宿舍退房流程）→ 应走拒答模板，闸门**不得**介入
    refuse_probe = "我毕业要退宿舍，需要办理哪些手续？"

    runs = []
    with httpx.Client(timeout=240) as c:
        r = c.post(f"{base}/api/login", json={"username": "student", "password": "student123"})
        r.raise_for_status()
        h = {"Authorization": f"Bearer {r.json()['token']}"}

        for i in range(1, args.n + 1):
            r = c.post(f"{base}/api/chat", headers=h, json={"question": case["question"]})
            r.raise_for_status()
            d = r.json()
            ans = d.get("answer", "")
            srcs = d.get("sources", []) or []
            ctx = d.get("context", {}) or {}
            gate = ctx.get("grounding_gate")
            marks = [m for m in MARKS if m in ans]
            has_fact = bool(FACTUAL.search(ans))
            would_fail = bool(marks) and not has_fact
            runs.append({
                "i": i, "answer_len": len(ans),
                "grounded": has_fact,
                "gate_hit": bool(gate),
                "gate_ok_after_regen": (gate or {}).get("ok_after_regen"),
                "gate_flag": (gate or {}).get("flag"),
                "refs": sorted(set(re.findall(r"\[(\d+)\]", ans)), key=int),
                "n_sources": len(srcs),
                "source_titles": [s.get("title") for s in srcs],
                "eval_would_fail": would_fail,
                "kw_hit": {k: (k in ans) for k in case["expect_keywords"]},
                "answer": ans,
            })
            print(f"[{i}/{args.n}] len={len(ans)} grounded={has_fact} gate={bool(gate)} "
                  f"ok_after={runs[-1]['gate_ok_after_regen']} refs={runs[-1]['refs']} "
                  f"evalFAIL={would_fail}", flush=True)

        # 反向用例：拒答路径不得被闸门介入
        r = c.post(f"{base}/api/chat", headers=h, json={"question": refuse_probe})
        r.raise_for_status()
        d = r.json()
        refuse_run = {
            "question": refuse_probe,
            "n_sources": len(d.get("sources", []) or []),
            "gate_present": "grounding_gate" in (d.get("context", {}) or {}),
            "answer_len": len(d.get("answer", "")),
        }
        print(f"[refusal-probe] sources={refuse_run['n_sources']} "
              f"gate_present={refuse_run['gate_present']}", flush=True)

    eval_fail = sum(1 for x in runs if x["eval_would_fail"])
    gate_hits = sum(1 for x in runs if x["gate_hit"])
    regen_ok = sum(1 for x in runs if x["gate_hit"] and x["gate_ok_after_regen"])
    payload = {
        "case_id": CASE_ID,
        "base": base,
        "n_runs": len(runs),
        "gate_hits": gate_hits,
        "regen_ok": regen_ok,
        "eval_fail": eval_fail,
        "verdict": ("PASS:闸门把 qa-17 全部兜住(FAIL=0)" if eval_fail == 0
                    else f"FAIL:仍有 {eval_fail}/{len(runs)} 次判红"),
        "invariant": {
            "R@k_all_1.0": all(all(x["kw_hit"].values()) for x in runs),
            "sources_all_correct": all(any("荣誉称号" in (t or "") for t in x["source_titles"])
                                       for x in runs),
        },
        "refusal_path_untouched": (not refuse_run["gate_present"]),
        "refusal_probe": refuse_run,
        "runs": runs,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[summary] 闸门命中 {gate_hits}/{len(runs)}（其中重生后合格 {regen_ok}）")
    print(f"[summary] 评测判红 {eval_fail}/{len(runs)} → {payload['verdict']}")
    print(f"[summary] R@k 全 1.0={payload['invariant']['R@k_all_1.0']} "
          f"来源全对={payload['invariant']['sources_all_correct']}")
    print(f"[summary] 拒答路径未被闸门介入={payload['refusal_path_untouched']}")
    print(f"[out] {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
