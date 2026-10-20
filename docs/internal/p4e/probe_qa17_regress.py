#!/usr/bin/env python3
"""P4e C0-① 诊断：为什么"候选层硬限流 per_doc=2"打死了 qa-17，以及替代策略。

【实测到的问题】首版修法(截断前硬限流 per_doc=2)让 qa-17
  「我是研究生…学生个人荣誉称号申请…」R@k 1.0 → 0.0(来源数 2→0)。
  假设:qa-17 的高分块是该 doc 的**第 3/4 块**(RRF 分低但 rerank 语义分高),
  候选层限流在 rerank **之前**就把它剔掉了 → 一刀切候选多样性过严。

本探针逐条打印:每条 qa 用例在 RRF 全序前 8 里的 **doc 分布**,
并对三种策略跑最终 sources:
  S1 hard        候选层硬限流 per_doc=2(首版,已知打死后 qa-17)
  S2 floor_d3    **多样性保底**:先取 RRF 前 K,若不同 doc 数 < D_MIN 则从全序继续补 doc,
                 补到 D_MIN 个不同 doc 或槽位满;槽位不预留、不丢任何原有高分块
  S3 原样(before)
库只读(temp 副本)。
"""
from __future__ import annotations

import asyncio
import json
import os
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

import numpy as np  # noqa: E402

from novaagent import config, db, rag  # noqa: E402

OUT = ROOT / "docs" / "p4e" / "evidence" / "fusion_strategy_probe.json"
D_MIN = 3  # 多样性保底目标:至少 3 个不同文档进候选


def strat_hard(fused_all, chunks, k, per_doc=2):
    out, cnt = [], {}
    for i, s in fused_all:
        d = chunks[i]["doc_id"]
        if cnt.get(d, 0) >= per_doc:
            continue
        cnt[d] = cnt.get(d, 0) + 1
        out.append((i, s))
        if len(out) >= k:
            return out
    if len(out) < k:
        seen = {i for i, _ in out}
        for i, s in fused_all:
            if i in seen:
                continue
            out.append((i, s))
            if len(out) >= k:
                break
    return out


def strat_floor(fused_all, chunks, k, d_min=D_MIN):
    """多样性保底:先原样取前 k 条(不丢任何 RRF 高位块),若其中不同 doc 数 < d_min,
    再从全序继续往后取**尚未出现过的 doc** 的块,补到 d_min 个不同 doc 或槽位满。
    不替换已有条目 → 原有高分块一个不丢,只做"加法"。"""
    picked = list(fused_all[:k])
    if len(picked) >= k:
        return picked
    seen = {i for i, _ in picked}
    docs = {chunks[i]["doc_id"] for i, _ in picked}
    for i, s in fused_all[k:]:
        if len(docs) >= d_min or len(picked) >= k:
            break
        d = chunks[i]["doc_id"]
        if d in docs or i in seen:
            continue
        docs.add(d)
        picked.append((i, s))
        seen.add(i)
    picked.sort(key=lambda x: -x[1])
    return picked


async def run_one(chunks, q, scheme, min_rank):
    qv = np.array((await rag.embed_texts([q]))[0], dtype="float32")
    v = rag._vector_search(qv, chunks, rag.VECTOR_TOP_K)
    k = rag._keyword_search(q, chunks, rag.KEYWORD_TOP_K, scope={})
    fused_all = rag._rrf_fuse(v, k)
    head = fused_all[:rag.FUSION_TOP_K]
    if scheme == "before":
        fused = head
    elif scheme == "hard":
        fused = strat_hard(fused_all, chunks, rag.FUSION_TOP_K)
    else:
        fused = strat_floor(fused_all, chunks, rag.FUSION_TOP_K)
    doc_hist: dict[str, int] = {}
    for i, _ in fused:
        d = str(chunks[i]["doc_id"])
        doc_hist[d] = doc_hist.get(d, 0) + 1
    if not fused:
        return {"n": 0, "docs": doc_hist, "titles": []}
    try:
        rr = await rag.rerank(q, [chunks[i]["content"] for i, _ in fused])
        raw = {fused[pos][0]: sc for pos, sc in rr}
    except Exception:  # noqa: BLE001
        raw = {}
    rrf_pos = {i: p for p, (i, _) in enumerate(fused)}
    n_f = max(len(fused), 1)
    if raw:
        blended = sorted(((i, rag.RERANK_BLEND * sc + (1 - rag.RERANK_BLEND) * (1 - rrf_pos.get(i, n_f) / n_f))
                          for i, sc in raw.items()), key=lambda x: -x[1])
        picked = [(i, s) for i, s in blended if raw[i] >= rag.RERANK_MIN_SCORE]
    else:
        picked = sorted(fused, key=lambda x: -x[1])
    cnt, final = {}, []
    for i, s in picked:
        d = chunks[i]["doc_id"]
        if cnt.get(d, 0) >= rag.MAX_PER_DOC:
            continue
        cnt[d] = cnt.get(d, 0) + 1
        final.append((i, s))
        if len(final) >= rag.FINAL_TOP_K:
            break
    return {"n": len(final), "docs": doc_hist,
            "n_docs_in_cand": len(doc_hist),
            "titles": [chunks[i]["title"][:36] for i, _ in final],
            "top_score": round(max((s for _, s in final), default=0.0), 4)}


async def main() -> dict:
    dst = os.path.join(tempfile.gettempdir(), "p4e_strategy.db")
    shutil.copyfile(str(config.DB_PATH), dst)
    config.DB_PATH = Path(dst)
    db.connect()
    cases = json.loads((ROOT / "evals" / "cases.json").read_text(encoding="utf-8"))["cases"]
    targets = [c for c in cases if c["id"] in ("qa-12", "qa-17", "qa-09", "qa-10", "qa-13", "qa-04",
                                               "qa-15", "rind-02", "qa-08")]
    out: dict = {"d_min": D_MIN, "rows": []}
    for c in targets:
        row: dict = {"id": c["id"], "question": c["question"], "expect": c.get("expect_sources")}
        for scheme in ("before", "hard", "floor_d3"):
            row[scheme] = await run_one(chunks, c["question"], scheme,
                                        config.ROLE_RANK[c.get("role", "student")]) \
                if False else await run_one(
                    db.all_chunks_for_search(config.ROLE_RANK[c.get("role", "student")]),
                    c["question"], scheme, config.ROLE_RANK[c.get("role", "student")])
        out["rows"].append(row)
        print(f"\n=== {c['id']} {c['question'][:40]} (expect={c.get('expect_sources')})")
        for scheme in ("before", "hard", "floor_d3"):
            r = row[scheme]
            print(f"  {scheme:<9} n={r['n']} 候选doc数={r.get('n_docs_in_cand', 0)} "
                  f"doc分布={r['docs']} top={r.get('top_score')}")
            for t in r["titles"]:
                print(f"        - {t}")
    return out


if __name__ == "__main__":
    rep = asyncio.run(main())
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n[report]", OUT)
