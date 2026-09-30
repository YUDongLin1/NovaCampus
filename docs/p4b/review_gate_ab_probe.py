#!/usr/bin/env python3
"""P4b 合并前把关:① 历史门控的**残留风险**A/B 实测。

Review 时我认可了"可采信池只收带 sources 的 assistant 回答+摘要"(堵住了用户断言洗白),
但 `history_gate_hit` 的"回指命中"档很宽(含它/该/此 且与池内共享 1 个 2-gram 或 2 个单字即放行)。
于是存在一条通道:**门控放行、池内却没有该主题内容** → 此时"不编造"又只剩 prompt 约束。

本脚本用同一句话做 A/B,唯一变量是"有没有历史":
  A 首问(无历史)  → 期望走确定性拒答模板(有「系统模板生成」指纹)
  B 追问(有历史)  → 看它是仍然拒,还是改用自有知识给出具体数字/天数
选句原则:与历史主题词面高度相邻(必然命中门控),但知识库确实没覆盖。
    /d/anaconda3/python.exe docs/p4b/review_gate_ab_probe.py
"""
import io
import json
import re
import sys

import httpx

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

BASE = "http://127.0.0.1:8900"
OUT = r"E:\AILearn\NovaCampus\docs\p4b\evidence\after\review_gate_ab.json"
TEMPLATE_MARK = "系统模板生成"
# 候选问句:先各跑一次首问,确认"知识库未覆盖"(即真无据),再拿它做追问 A/B
CANDIDATES = [
    "研究生休学期间宿舍床位保留多少天?",
    "研究生休学后复学要提前几周提交申请?",
    "研究生休学期间学费按什么比例退还?",
]


def login(user, pwd):
    r = httpx.post(BASE + "/api/login", json={"username": user, "password": pwd}, timeout=20)
    r.raise_for_status()
    return {"Authorization": "Bearer " + r.json()["token"]}


def ask(H, q, cid=None):
    body = {"question": q}
    if cid:
        body["conversation_id"] = cid
    d = httpx.post(BASE + "/api/chat", json=body, headers=H, timeout=180).json()
    return d


def classify(d):
    a = d.get("answer", "")
    srcs = d.get("sources") or []
    ctx = d.get("context") or {}
    nums = re.findall(r"\d+", a)
    return {"answer_head": a[:260], "n_sources": len(srcs), "template_fingerprint": TEMPLATE_MARK in a,
            "history_gate": ctx.get("history_gate"), "followup_no_new_sources": ctx.get("followup_no_new_sources"),
            "digits_in_answer": sorted(set(nums))[:12], "says_not_covered": ("未覆盖" in a or "暂无" in a
                                                                            or "未检索" in a)}


def main():
    H = login("counselor", "counselor123")
    res = {}
    # 先确定哪一句真的"知识库无覆盖"(首问被拒),用它做 A/B
    probe = {}
    for q in CANDIDATES:
        d = ask(H, q)
        c = classify(d)
        probe[q] = c
        print("[首问探测] %s → 模板拒答=%s 来源=%d" % (q[:24], c["template_fingerprint"], c["n_sources"]))
    uncovered = [q for q, c in probe.items() if c["template_fingerprint"] and c["n_sources"] == 0]
    res["first_turn_probe"] = probe
    if not uncovered:
        print("[WARN] 三句首问都不是无据,换句再测"); json.dump(res, io.open(OUT, "w", encoding="utf-8"),
                                                               ensure_ascii=False, indent=2); return
    q = uncovered[0]

    # A/B:同一句,一次首问、一次作为追问
    a = classify(ask(H, q))
    cid = httpx.post(BASE + "/api/conversations", json={"title": "REVIEW-GATE-AB"}, headers=H, timeout=20).json()["id"]
    warm = ask(H, "研究生申请休学需要提交哪些材料?", cid)          # 造历史(带 sources 的 assistant 回答)
    b = classify(ask(H, q, cid))
    res["ab"] = {"question": q, "A_first_turn": a, "B_followup": b,
                 "warm_turn_sources": len(warm.get("sources") or [])}
    print("\n=== 同一句「%s」 ===" % q[:30])
    print("A 首问  : 模板拒答=%s 声称未覆盖=%s 答案数字=%s" %
          (a["template_fingerprint"], a["says_not_covered"], a["digits_in_answer"]))
    print("B 追问  : 模板拒答=%s 声称未覆盖=%s 门控=%s 答案数字=%s" %
          (b["template_fingerprint"], b["says_not_covered"], b["history_gate"], b["digits_in_answer"]))
    print("B 答案头: %s" % b["answer_head"].replace("\n", " ")[:200])
    leaked = (not b["says_not_covered"]) and bool(b["digits_in_answer"])
    res["verdict"] = {"gate_passed_but_pool_lacks_topic": bool(b["history_gate"] == "hit" and not b["template_fingerprint"]),
                      "B_gives_specific_numbers": leaked,
                      "conclusion": "追问轮给出具体数字而首问明确无据 → 门控放行后仍靠 prompt 兜底,存在自有知识编造通道"
                      if leaked else "追问轮仍如实说明未覆盖,未观测到编造"}
    print("\n[判定] %s" % json.dumps(res["verdict"], ensure_ascii=False)[:220])
    httpx.delete(BASE + "/api/conversations/%d" % cid, headers=H, timeout=20)
    json.dump(res, io.open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("[OK] 证据写入 %s" % OUT)


if __name__ == "__main__":
    main()
