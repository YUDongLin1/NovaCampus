#!/usr/bin/env python3
"""P4e C0-② 取证：rind-07 断言用词在 **student 可见块的正文层**的真实命中数。

复核方已在 `docs/p4d/evidence/review/rind07_premise.json` 给出块数；本脚本
独立复现一遍（坑 33：复核方要带自己的尺子），并额外做两件复核方没做的事：
  1. 判定 C0-② 选用的每个「零命中词」在 student 可见块里**确实 0 块**（否则断言会假红）；
  2. 检查 `contacts.json` 出口模板本身是否含这些词——若含，拒答模板会被自己的
     断言判红（contacts 的 dept/phone/url 会进模板，scope_keywords/note 不会）。

只读：sqlite ro 连接 + 读 contacts.json，全程不写库。
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs" / "p4e" / "evidence" / "rind07_kw_probe.json"
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError, OSError):
    pass

WIDE = ["证明", "录取", "钥匙", "图书馆", "饭卡", "调档", "报到"]
ZERO_CANDIDATES = ["交回", "退卡", "提档", "调档", "饭卡", "档案转递", "退还", "转递", "迁移",
                   "签证", "交换", "洗衣机", "遥控器", "校园卡"]


def main() -> int:
    conn = sqlite3.connect(f"file:{ROOT / 'novaagent' / 'data' / 'agent.db'}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """SELECT ch.content, d.title FROM chunks ch JOIN documents d ON d.id = ch.doc_id
           WHERE d.role_min IN ('student','common')"""
    ).fetchall()
    n = len(rows)
    body = {w: sum(1 for r in rows if w in (r["content"] or "")) for w in set(WIDE + ZERO_CANDIDATES)}
    titles = {w: sum(1 for r in rows if w in (r["title"] or "")) for w in set(WIDE + ZERO_CANDIDATES)}
    print(f"student 可见块 = {n}")
    print(f"{'词':<10}{'标题层':>8}{'正文块':>8}")
    for w in sorted(set(WIDE + ZERO_CANDIDATES), key=lambda x: (body[x], x)):
        print(f"{w:<10}{titles[w]:>8}{body[w]:>8}")

    contacts = json.loads((ROOT / "novaagent" / "novaagent" / "data" / "contacts.json")
                          .read_text(encoding="utf-8"))
    # build_refusal 模板只渲染 dept / phone / url（scope_keywords 与 note 不进答案）
    rendered = " ".join(
        f"{c.get('dept','')} {' '.join(c.get('phone') or [])} {c.get('url','')}"
        for c in contacts.get("contacts", [])
    )
    contacts_hit = sorted({w for w in WIDE + ZERO_CANDIDATES if w in rendered})

    chosen = ["交回", "退卡", "提档", "调档", "饭卡", "档案转递"]
    bad = [w for w in chosen if body[w] != 0]
    rep = {
        "n_student_visible_chunks": n,
        "body_chunk_hits": body, "title_hits": titles,
        "wide_keywords": WIDE,
        "wide_with_body_hits": {w: body[w] for w in WIDE if body[w] > 0},
        "zero_hit_candidates": {w: body[w] for w in ZERO_CANDIDATES},
        "c0_2_chosen_unconditional": chosen,
        "c0_2_chosen_all_zero": not bad,
        "c0_2_chosen_violations": bad,
        "contacts_rendered_fields_hit": contacts_hit,
        "pass": (not bad) and not contacts_hit,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nC0-② 选用的无条件词 = {chosen}")
    print(f"  全部零命中 = {rep['c0_2_chosen_all_zero']}" + (f" 违规={bad}" if bad else ""))
    print(f"contacts 模板(dept/phone/url)命中这些词 = {contacts_hit or '无'}")
    print(f"[结论] pass = {rep['pass']}   [report] {OUT}")
    return 0 if rep["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
