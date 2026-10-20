#!/usr/bin/env python3
"""P4e C0-② 取证：rind-07 断言用词在 **student 可见块的正文层**的真实命中数。

复核方已在 `docs/p4d/evidence/review/rind07_premise.json` 给出块数；本脚本
独立复现一遍（坑 33：复核方要带自己的尺子），并额外做两件复核方没做的事：
  1. 判定 C0-② 选用的每个「零命中词」在 student 可见块里**确实 0 块**（否则断言会假红）；
  2. 检查 `contacts.json` 出口模板本身是否含这些词——若含，拒答模板会被自己的
     断言判红（contacts 的 dept/phone/url 会进模板，scope_keywords/note 不会）。

【M2 修订，2026-09-30 第二回打回】**共现段的上下文词也必须纳入同一把尺子**。
原版只统计无条件段（`rind07_kw_probe.json` 里没有任何 cooccur 项），
导致 `录取通知书` 被我误当零命中词写进共现段 —— 复核方实测 **5 块**
（《国家助学贷款实施办法》第十一条/第十七条原文就有「录取通知书…相关证明资料」），
而共现判据是**整篇两词都在**，于是一个**据实引用该条款的正常答案会被判红**，
正是 C0-② 要消除的「检索一增强就必然假红」在改进后的断言里复发。
本版把 `expect_absent_keywords_cooccur` 的**每一个上下文词**都实测并落盘。

只读：sqlite ro 连接 + 读 contacts.json，全程不写库。
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CASES = ROOT / "evals" / "cases.json"
OUT = ROOT / "docs" / "p4e" / "evidence" / "rind07_kw_probe.json"
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError, OSError):
    pass

CASE_ID = "rind-07"
# 宽词：库内有正当出处，**不可**进无条件段（坑 54）
WIDE = ["证明", "录取", "钥匙", "图书馆", "饭卡", "调档", "报到"]
# 候选零命中词（无条件段与共现段共用同一候选池）
ZERO_CANDIDATES = ["交回", "退卡", "提档", "调档", "饭卡", "档案转递", "退还", "转递", "迁移",
                   "签证", "交换", "洗衣机", "遥控器", "校园卡",
                   # ↓ M2 新增：上一版误当零命中的词，现必须实测
                   "录取通知书", "凭据", "借阅", "回收", "领取", "递交", "注销"]


def main() -> int:
    conn = sqlite3.connect(f"file:{ROOT / 'novaagent' / 'data' / 'agent.db'}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """SELECT ch.content, d.title FROM chunks ch JOIN documents d ON d.id = ch.doc_id
           WHERE d.role_min IN ('student','common')"""
    ).fetchall()
    n = len(rows)
    all_words = set(WIDE + ZERO_CANDIDATES)
    body = {w: sum(1 for r in rows if w in (r["content"] or "")) for w in all_words}
    titles = {w: sum(1 for r in rows if w in (r["title"] or "")) for w in all_words}
    print(f"student 可见块 = {n}")
    print(f"{'词':<12}{'标题层':>8}{'正文块':>8}")
    for w in sorted(all_words, key=lambda x: (body[x], x)):
        print(f"{w:<12}{titles[w]:>8}{body[w]:>8}")

    contacts = json.loads((ROOT / "novaagent" / "novaagent" / "data" / "contacts.json")
                          .read_text(encoding="utf-8"))
    # build_refusal 模板只渲染 dept / phone / url（scope_keywords 与 note 不进答案）
    rendered = " ".join(
        f"{c.get('dept','')} {' '.join(c.get('phone') or [])} {c.get('url','')}"
        for c in contacts.get("contacts", [])
    )
    contacts_hit = sorted({w for w in all_words if w in rendered})

    # ---- 从 cases.json 读**实际生效**的断言，而不是把词硬编码在探针里 ----
    # （坑 52 同源：探针自带词表 = 尺子与被测物各写一份，测出来的是"我以为的"）
    cases = json.loads(CASES.read_text(encoding="utf-8"))
    case = next(c for c in cases["cases"] if c["id"] == CASE_ID)
    uncond = [k for k in case.get("expect_absent_keywords", []) if k]
    coocur = [p for p in (case.get("expect_absent_keywords_cooccur") or []) if p]
    ctx_words = sorted({c for p in coocur for c in (p[1] or []) if c})
    main_words = sorted({p[0] for p in coocur if p and p[0]})

    # M2 的核心校验：无条件段**与共现段上下文词**都必须真的 0 命中
    uncond_bad = [w for w in uncond if body.get(w, -1) != 0]
    ctx_bad = [w for w in ctx_words if body.get(w, -1) != 0]

    rep = {
        "n_student_visible_chunks": n,
        "body_chunk_hits": body, "title_hits": titles,
        "wide_keywords": WIDE,
        "wide_with_body_hits": {w: body[w] for w in WIDE if body[w] > 0},
        "zero_hit_candidates": {w: body[w] for w in ZERO_CANDIDATES},
        "from_cases_json": {
            "unconditional": uncond,
            "cooccur_pairs": coocur,
            "cooccur_main_words": main_words,
            "cooccur_context_words": ctx_words,
        },
        "c0_2_chosen_unconditional": uncond,
        "c0_2_chosen_all_zero": not uncond_bad,
        "c0_2_chosen_violations": uncond_bad,
        # M2：共现段上下文词的零命中证据（上一版缺失，导致「录取通知书」被误当零命中）
        "c0_2_cooccur_context_all_zero": not ctx_bad,
        "c0_2_cooccur_context_violations": ctx_bad,
        "c0_2_cooccur_context_hits": {w: body.get(w, -1) for w in ctx_words},
        "contacts_rendered_fields_hit": contacts_hit,
        "pass": (not uncond_bad) and (not ctx_bad) and not contacts_hit,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n无条件段 = {uncond}")
    print(f"  全部零命中 = {rep['c0_2_chosen_all_zero']}" + (f" 违规={uncond_bad}" if uncond_bad else ""))
    print(f"共现段上下文词（M2 新增校验）= {ctx_words}")
    for w in ctx_words:
        print(f"    {w:<12}{body.get(w, -1):>6} 块" + ("   ← 非零，须移出共现词" if body.get(w, 0) else ""))
    print(f"  全部零命中 = {rep['c0_2_cooccur_context_all_zero']}")
    print(f"contacts 模板(dept/phone/url)命中这些词 = {contacts_hit or '无'}")
    print(f"[结论] pass = {rep['pass']}   [report] {OUT}")
    return 0 if rep["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
