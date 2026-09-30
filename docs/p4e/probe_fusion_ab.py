#!/usr/bin/env python3
"""P4e C0-① A/B 对照：FUSION_TOP_K 8 → 12(纯扩槽位、不剔除)对全库检索的影响面。

回答三个问题(都要实测,不许推定):
  A1 目标修好了吗   —— qa-12 的 doc9「EVAL-研究生奖学金评定办法」是否进最终 sources;
  A2 伤到别人了吗   —— 18 条带 expect_sources 的 qa/scoped_qa 逐条比对 sources 集合与 R@k;
                      **含 qa-17 回归守卫**(它是"高分块排在同文档第 3+ 位"的反例,
                      首版"截断前硬限流"就是被它否掉的);
  A3 变体矩阵还 8/8 吗 —— 8 条学平险问法走 graph.retrieve_with_retry 编排后是否仍全部命中。

A/B 靠改模块属性 `rag.FUSION_TOP_K` 切换(同进程内严格同输入对照,库只读 temp 副本)。
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "novaagent"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError, OSError):
    pass

from novaagent import config, db, graph, rag  # noqa: E402

OUT = ROOT / "docs" / "p4e" / "evidence" / "fusion_ab.json"
AFTER_K = int(config.env("NOVA_FUSION_TOP_K", "12"))  # rag.py 里的生效值

# 与 run_evals.compute_recall 同口径的多形态归一(独立复刻,避免 import 评测脚本的副作用)
_NORM_MAP = {"（": "(", "）": ")", "［": "[", "］": "]", "【": "[", "】": "]",
             "〔": "[", "〕": "]", "《": "", "》": "", "〈": "", "〉": "",
             "「": "", "」": "", "，": ",", "。": ".", "、": ",", "：": ":", "；": ";"}
_PAREN_ANY = re.compile(r"[（(［\[【〔][^（()）\[\]【〔〕]{0,20}[）)］\]】〕]")


def _forms(s: str) -> list[str]:
    base = "".join(_NORM_MAP.get(c, c) for c in s)
    for ws in (" ", "\t", "\n", "\r", "　"):
        base = base.replace(ws, "")
    a = _PAREN_ANY.sub(lambda m: m.group(0)[1:-1], base)
    b, prev = base, None
    while prev != b:
        prev = b
        b = _PAREN_ANY.sub("", b)
    return sorted({f for f in (base, a, b) if f})


def recall(case: dict, sources: list[dict]) -> float | None:
    expect = case.get("expect_sources") or []
    if not expect:
        return None
    titles: list[str] = []
    for s in sources:
        titles.extend(_forms(s.get("title", "")))
    hit = sum(1 for sub in expect if any(f in t for f in _forms(sub) for t in titles))
    return round(hit / len(expect), 4)


VARIANTS = [
    ("纯术语", "学平险"),
    ("术语+一般问", "学校有学平险吗"),
    ("术语+具体意图", "学平险在哪里买"),
    ("真实原句(学生口吻)", "我们学校有学平险吗，我看我们计财处只有医保这项"),
    ("背景前置倒装", "我看计财处只有医保这一项，那学校还给学平险吗"),
    ("口语加称呼情境", "老师，我想问下咱们学校那个学平险是要单独交钱买吗，我没在缴费项目里看到"),
    ("书面正式名", "学生平安保险是否由学校统一办理？"),
    ("多子句书面全称", "关于学生在校期间的意外与医疗保障，除了城乡居民基本医疗保险之外，学校是否还统一办理学生平安保险？"),
]


def _is_target(s: dict) -> bool:
    return "学平险" in (s.get("title") or "") or "学生平安" in (s.get("content") or "")


def _is_grad_scholarship(s: dict) -> bool:
    return str(s.get("title", "")).startswith("EVAL-研究生奖学金")


async def main() -> dict:
    dst = os.path.join(tempfile.gettempdir(), "p4e_fusion_ab.db")
    shutil.copyfile(str(config.DB_PATH), dst)
    config.DB_PATH = Path(dst)
    db.connect()

    cases = json.loads((ROOT / "evals" / "cases.json").read_text(encoding="utf-8"))["cases"]
    qa_cases = [c for c in cases if c["type"] in ("qa", "scoped_qa") and c.get("expect_sources")]

    out: dict = {"n_chunks": len(db.all_chunks_for_search(config.ROLE_RANK["student"])),
                 "ab_axis": "rag.FUSION_TOP_K 8(before) vs 12(after)", "qa_ab": [], "matrix": []}

    for c in qa_cases:
        rank = config.ROLE_RANK[c.get("role", "student")]
        row: dict = {"id": c["id"], "question": c["question"], "expect_sources": c["expect_sources"]}
        for tag, k in (("before", 8), ("after", rag.FUSION_TOP_K)):
            rag.FUSION_TOP_K = k
            res, qual = await rag.search_with_quality(c["question"], rank)
            row[tag] = {"fuse_k": k, "n": len(res), "r_at_k": recall(c, res),
                        "top_score": qual.get("top_score"),
                        "fused_candidates": qual.get("fused_candidates"),
                        "fused_candidate_docs": qual.get("fused_candidate_docs"),
                        "titles": [s["title"][:40] for s in res]}
        row["changed"] = row["before"]["titles"] != row["after"]["titles"]
        row["r_delta"] = (None if row["before"]["r_at_k"] is None or row["after"]["r_at_k"] is None
                          else round(row["after"]["r_at_k"] - row["before"]["r_at_k"], 4))
        out["qa_ab"].append(row)
        mark = "CHANGED" if row["changed"] else "same   "
        print(f"[{mark}] {row['id']:<8} R@k {row['before']['r_at_k']} -> {row['after']['r_at_k']}"
              f"  n={row['before']['n']}->{row['after']['n']}"
              f"  候选 {row['before']['fused_candidates']}/{row['before']['fused_candidate_docs']}doc"
              f" -> {row['after']['fused_candidates']}/{row['after']['fused_candidate_docs']}doc"
              f"  {c['question'][:30]}")
    rag.FUSION_TOP_K = 12

    # qa-12 目标块专项断言(C0-① 验收锚点)
    q12_q = next(c["question"] for c in cases if c["id"] == "qa-12")
    rag.FUSION_TOP_K = 8
    q12_before, _ = await rag.search_with_quality(q12_q, config.ROLE_RANK["student"])
    rag.FUSION_TOP_K = AFTER_K
    q12_after, q12_after_q = await rag.search_with_quality(q12_q, config.ROLE_RANK["student"])
    out["qa12_target"] = {
        "target": "EVAL-研究生奖学金评定办法",
        "in_before": any(_is_grad_scholarship(s) for s in q12_before),
        "in_after": any(_is_grad_scholarship(s) for s in q12_after),
        "after_titles": [s["title"][:40] for s in q12_after],
        "after_candidate_docs": q12_after_q.get("fused_candidate_docs"),
    }
    print("\n[qa-12 专项] 目标块(研究生奖学金评定办法) in_before =",
          out["qa12_target"]["in_before"], "| in_after =", out["qa12_target"]["in_after"])
    for s in q12_after:
        print(f"    [{s['ref']}] {s['score']:.4f} {s['title'][:44]}")

    for name, q in VARIANTS:
        r = await graph.retrieve_with_retry(q, config.ROLE_RANK["student"])
        hit = any(_is_target(s) for s in r["sources"])
        out["matrix"].append({"variant": name, "question": q, "hit": hit,
                              "n_sources": len(r["sources"]), "attempts": r["attempts"],
                              "rewritten": r["rewritten"], "final_query": r["final_query"]})
        print(f"[matrix] {'HIT ' if hit else 'MISS'} {name:<20} n={len(r['sources'])} "
              f"attempts={r['attempts']} rewritten={r['rewritten']}")

    n_changed = sum(1 for r in out["qa_ab"] if r["changed"])
    out["summary"] = {
        "qa_total": len(out["qa_ab"]), "qa_changed": n_changed,
        "qa_r_down": [r["id"] for r in out["qa_ab"] if (r["r_delta"] or 0) < 0],
        "qa_r_up": [r["id"] for r in out["qa_ab"] if (r["r_delta"] or 0) > 0],
        "qa_zero_after": [r["id"] for r in out["qa_ab"] if r["after"]["n"] == 0],
        "qa12_target_in_after": out["qa12_target"]["in_after"],
        "matrix_hit": sum(1 for m in out["matrix"] if m["hit"]), "matrix_total": len(out["matrix"]),
    }
    print("\n[汇总]", json.dumps(out["summary"], ensure_ascii=False))
    return out


if __name__ == "__main__":
    rep = asyncio.run(main())
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    print("[report]", OUT)
