#!/usr/bin/env python3
"""P4e C0 交回前取证：复现 qa-17 在**正确 12 槽**下的答案原文与非答案判据命中情况。

【为什么需要这个探针】
qa-17 在正确 12 槽下稳定 8/10 FAIL(非抖动),但:
  - R@k = 1.0、来源正确(doc77 荣誉称号两块)、答案内容实质正确
  - 失败点唯一:命中免责措辞 + **零可核查事实**(无 [n] 且无数字)
按纪律**不擅自改判据/不改用例/不改生成侧 prompt**,故把答案原文与逐项判据
落盘,交 Qoder 按 A/B/C 裁决。

【口径】
- 库**只读**:直接打运行中的服务端,不改 agent.db,零副作用(不导入 rag/db 模块)
- 问句**不手写**:从 evals/cases.json 取 qa-17,杜绝手抄走样(同 C0 延迟探针纪律)
- 忠实度按**区间**读,不当点值闸门(禁改 faithfulness.py)

用法(必须先起本分支代码的服务,端口自定,须与 --base 一致):
  bash docs/p4d/run_with_server.sh 8902 docs/p4e/probe_qa17_answer.py --base http://127.0.0.1:8902
落盘:docs/p4e/evidence/qa17_answer.json   退出码:0(取证脚本,恒 0)
"""
from __future__ import annotations

import os
import argparse
import json
import re
import sys
from pathlib import Path

import httpx


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


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs" / "p4e" / "evidence" / "qa17_answer.json"
CASE_ID = "qa-17"
N = 5  # 连测次数:确认是"稳定形态"还是"抖动"

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError, OSError):
    pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8900")
    ap.add_argument("--n", type=int, default=N)
    args = ap.parse_args()
    base = args.base.rstrip("/")

    # 判据与 run_evals.py 保持逐字一致(不 import 评测脚本:它有模块级 BASE 副作用)
    NON_ANSWER_MARKS = (
        "未在知识库", "未检索到", "没有检索到", "未覆盖", "没有覆盖", "未收录", "未包含",
        "知识库中未", "暂无", "没有找到", "无法回答", "不在知识库", "没有相关",
        "请以", "建议咨询", "请咨询", "无法提供", "以学校现行", "以研究生主管部门", "以保卫处",
    )
    _FACTUAL = re.compile(r"\[\d+\]|\d")

    cases = json.loads((ROOT / "evals" / "cases.json").read_text(encoding="utf-8"))["cases"]
    case = next(c for c in cases if c["id"] == CASE_ID)

    runs = []
    with httpx.Client(timeout=180) as c:
        r = c.post(f"{base}/api/login", json={"username": "student", "password": STUDENT_PW})
        r.raise_for_status()
        headers = {"Authorization": f"Bearer {r.json()['token']}"}

        for i in range(1, args.n + 1):
            r = c.post(f"{base}/api/chat", headers=headers, json={"question": case["question"]})
            r.raise_for_status()
            d = r.json()
            ans = d.get("answer", "")
            srcs = d.get("sources", [])
            marks = [m for m in NON_ANSWER_MARKS if m in ans]
            refs = sorted(set(re.findall(r"\[(\d+)\]", ans)), key=int)
            digits = re.findall(r"\d+", ans)
            # 只取 retrieve 节点(联网/写库节点本轮不涉及)
            trace = [t for t in (d.get("retrieval_trace") or []) if "retrieve" in str(t.get("node", ""))
             or "fused" in json.dumps(t, ensure_ascii=False)]
            runs.append({
                "i": i,
                "answer_len": len(ans),
                "answer": ans,
                "n_sources": len(srcs),
                "source_titles": [s.get("title") for s in srcs],
                "non_answer_marks": marks,
                "refs": refs,
                "digits": digits,
                "has_fact": bool(_FACTUAL.search(ans)),
                "would_fail_non_answer": bool(marks) and not bool(_FACTUAL.search(ans)),
                "kw_hit": {k: (k in ans) for k in case["expect_keywords"]},
                "trace": trace[:2],
            })
            print(f"[{i}/{args.n}] len={len(ans)} src={len(srcs)} marks={marks} "
                  f"refs={refs} has_fact={runs[-1]['has_fact']} "
                  f"FAIL={runs[-1]['would_fail_non_answer']}", flush=True)

    fail = sum(1 for x in runs if x["would_fail_non_answer"])
    payload = {
        "case_id": CASE_ID,
        "question": case["question"],
        "note": case.get("note"),
        "base": base,
        "n_runs": len(runs),
        "non_answer_fail": fail,
        "fail_rate": f"{fail}/{len(runs)}",
        "conclusion": ("稳定失败(非抖动)" if fail >= len(runs) * 0.8 else
                       "抖动(多数 PASS)" if fail <= len(runs) * 0.2 else "中间态"),
        "invariant": {
            "R@k_all_1.0": all(x["kw_hit"] for x in runs),
            "sources_all_correct": all(any("荣誉称号" in (t or "") for t in x["source_titles"])
                                       for x in runs),
        },
        "runs": runs,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[summary] 非答案判据 FAIL = {fail}/{len(runs)} → {payload['conclusion']}")
    print(f"[summary] R@k 全 1.0 = {payload['invariant']['R@k_all_1.0']} | "
          f"来源全对 = {payload['invariant']['sources_all_correct']}")
    print(f"[out] {OUT}")
    return 0  # 取证脚本恒 0:判红是发现,不是脚本失败


if __name__ == "__main__":
    sys.exit(main())
