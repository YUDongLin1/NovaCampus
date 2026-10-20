#!/usr/bin/env python3
"""P4d 合并前把关:实弹复现 rind-02 与忠实度 0.0 的 qa-12/qa-13。

为什么自己跑:报告 results 里不存 answer,只存 pass/detail/分数;
"拒答未含出口"与"忠实度 0.0"这两种失败,**光看数字分不清是 judge 噪声还是改写引入无据内容**。
本脚本把三条问句走 live API 打一遍,打印 answer 全文 + sources + retrieval_trace,
并对 qa 类做一条**可机检的接地检查**:答案里的数字/年份是否至少有一条能在 sources 正文里找到。

    NO_PROXY="127.0.0.1,localhost" novaagent/.venv/Scripts/python.exe -X utf8 docs/p4d/review_rind02_faithfulness.py
"""
import os
import io
import json
import re
import sys

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


try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

BASE = "http://127.0.0.1:8900"
OUT = r"E:\AILearn\NovaCampus\docs\p4d\evidence\after\review_rind02_faithfulness.json"
CASES = {"rind-02": "我们学校有学平险吗，我看我们计财处只有医保这项",
         "qa-12": None, "qa-13": None}
EXPECT_CONTACT = {"rind-02": "87600392"}
NUM = re.compile(r"\d{2,}")


def main():
    spec = json.load(io.open(r"E:\AILearn\NovaCampus\evals\cases.json", encoding="utf-8"))
    for c in spec["cases"]:
        if c["id"] in CASES:
            CASES[c["id"]] = c["question"]
    H = {"Authorization": "Bearer " + httpx.post(BASE + "/api/login",
         json={"username": "student", "password": STUDENT_PW}, timeout=20).json()["token"]}
    res = {}
    for cid, q in CASES.items():
        r = httpx.post(BASE + "/api/chat", json={"question": q}, headers=H, timeout=180)
        d = r.json()
        ans = d.get("answer") or ""
        srcs = d.get("sources") or []
        src_text = "\n".join((s.get("content") or "") for s in srcs) + "\n" + \
                   "\n".join((s.get("title") or "") for s in srcs)
        nums = set(NUM.findall(ans))
        grounded = {n for n in nums if n in src_text}
        ungrounded = sorted(nums - grounded)
        ctx = d.get("context") or {}
        trace = ctx.get("retrieval_trace") or []
        res[cid] = {"question": q, "n_sources": len(srcs),
                    "titles": [s.get("title") for s in srcs],
                    "answer": ans[:900], "answer_len": len(ans),
                    "has_refusal_mark": any(m in ans for m in ("暂无", "未检索", "无法", "未覆盖", "没有相关")),
                    "expect_contact": EXPECT_CONTACT.get(cid),
                    "contact_present": (EXPECT_CONTACT.get(cid) in ans) if EXPECT_CONTACT.get(cid) else None,
                    "digits_in_answer": sorted(nums), "digits_grounded_in_sources": sorted(grounded),
                    "digits_NOT_in_sources": ungrounded,
                    "intent": ctx.get("intent"), "attempts": ctx.get("attempts"),
                    "rewritten": ctx.get("rewritten"), "retrieval_skipped": ctx.get("retrieval_skipped"),
                    "trace_nodes": [t.get("node") for t in trace],
                    "trace_top_scores": [t.get("top_score") for t in trace if "top_score" in t],
                    "trace_rewrite_queries": [t.get("query") for t in trace if t.get("node") == "retrieve"]}
        print("[%s] sources=%d 拒答标记=%s 出口%s=%s | intent=%s attempts=%s 改写=%s 轨迹=%s"
              % (cid, len(srcs), res[cid]["has_refusal_mark"],
                 EXPECT_CONTACT.get(cid), res[cid]["contact_present"],
                 ctx.get("intent"), ctx.get("attempts"), ctx.get("rewritten"),
                 res[cid]["trace_nodes"]))
        print("     答案:", ans[:260].replace("\n", " / "))
        print("     答案数字:", sorted(nums), "| 未出现在 sources 里的:", ungrounded)
        print()
    json.dump(res, io.open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("[OK] 证据写入 %s" % OUT)


if __name__ == "__main__":
    main()
