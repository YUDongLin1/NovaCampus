#!/usr/bin/env python3
"""P4e C0-① 实测探针：qa-12 融合层截断漏召的**修法选型**（不猜，实测后定）。

复核方已定断点（`review_qa12_attribution.py`）：doc9「EVAL-研究生奖学金评定办法」
向量层第 6(0.6809)、关键词层未进 top20 → RRF 分仅 1/67 → **未进 FUSION_TOP_K=8**，
8 个槽位被两篇本科生办法的块占满 → 根本没进 rerank → 答案错误否定断言。

本探针在**库副本**上把 4 个候选方案跑同一问句，逐层打印并给出最终 sources：
  A  baseline           :现状(_rrf_fuse(...)[:FUSION_TOP_K])
  B  per-doc 多样化(截断前):_rrf_fuse 全序上按 doc 限流,再截断(FUSION_TOP_K 不变)
  C  B + 扩 FUSION_TOP_K  :多样化后再放宽槽位(12)
  D  只扩 FUSION_TOP_K    :不多样化,单纯 8→12(对照组,证明"扩槽位"是否足够)

⚠ 合规:问句是评测集里已有的公开政策问句,不含任何学工/学生个人信息;
  本脚本**只读**库副本(config.DB_PATH 指向 temp 副本),不写任何库。
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

QUERY = "研究生奖助学金评审是怎么规定的?"
TARGET_DOC = 9
OUT = ROOT / "docs" / "p4e" / "evidence" / "qa12_fusion_probe.json"


def _is_target(s: dict) -> bool:
    return str(s.get("title", "")).startswith("EVAL-研究生奖学金")


def diversify(fused: list[tuple[int, float]], chunks: list[dict], top_k: int,
              max_per_doc: int) -> list[tuple[int, float]]:
    """截断**前**做 per-doc 限流：沿 RRF 全序取,每 doc 至多 max_per_doc 条,取满 top_k。
    不足 top_k 时**不回落**为无限制(保持"多样化优先"语义,宁缺毋滥)。"""
    out: list[tuple[int, float]] = []
    cnt: dict[int, int] = {}
    for i, s in fused:
        d = chunks[i]["doc_id"]
        if cnt.get(d, 0) >= max_per_doc:
            continue
        cnt[d] = cnt.get(d, 0) + 1
        out.append((i, s))
        if len(out) >= top_k:
            break
    return out


async def run_scheme(name: str, chunks: list[dict], qv: np.ndarray, *, fuse_top_k: int,
                     per_doc: int | None) -> dict:
    v = rag._vector_search(qv, chunks, rag.VECTOR_TOP_K)
    k = rag._keyword_search(QUERY, chunks, rag.KEYWORD_TOP_K, scope={})
    fused_all = rag._rrf_fuse(v, k)
    if per_doc is None:
        fused = fused_all[:fuse_top_k]
    else:
        fused = diversify(fused_all, chunks, fuse_top_k, per_doc)
    rep: dict = {
        "scheme": name, "fuse_top_k": fuse_top_k, "per_doc": per_doc,
        "n_fused_all": len(fused_all),
        "fused": [{"doc": chunks[i]["doc_id"], "title": chunks[i]["title"][:30], "rrf": round(s, 5)}
                  for i, s in fused],
        "fused_doc_hist": {},
    }
    for i, _ in fused:
        d = chunks[i]["doc_id"]
        rep["fused_doc_hist"][str(d)] = rep["fused_doc_hist"].get(str(d), 0) + 1
    idxs = [i for i, _ in fused]
    if not idxs:
        rep["final"] = []
        return rep
    try:
        rr = await rag.rerank(QUERY, [chunks[i]["content"] for i in idxs])
        raw = {idxs[pos]: sc for pos, sc in rr}
        rep["rerank"] = [{"doc": chunks[i]["doc_id"], "title": chunks[i]["title"][:30],
                          "score": round(raw[i], 4), "pass": raw[i] >= rag.RERANK_MIN_SCORE}
                         for i, _ in fused if i in raw]
    except Exception as e:  # noqa: BLE001
        rep["rerank_error"] = str(e)[:160]
        raw = {}
    # 复刻 search_with_quality 的后半段(blend → 阈值 → per-doc 限流 → FINAL_TOP_K)
    rrf_pos = {i: p for p, (i, _) in enumerate(fused)}
    n_f = max(len(fused), 1)
    blended = sorted(((i, rag.RERANK_BLEND * sc + (1 - rag.RERANK_BLEND) * (1.0 - rrf_pos.get(i, n_f) / n_f))
                      for i, sc in raw.items()), key=lambda x: -x[1])
    picked = [(i, s) for i, s in blended if raw[i] >= rag.RERANK_MIN_SCORE] or fused
    cnt: dict[int, int] = {}
    final: list[tuple[int, float]] = []
    for i, s in picked:
        d = chunks[i]["doc_id"]
        if cnt.get(d, 0) >= rag.MAX_PER_DOC:
            continue
        cnt[d] = cnt.get(d, 0) + 1
        final.append((i, s))
        if len(final) >= rag.FINAL_TOP_K:
            break
    rep["final"] = [{"n": n + 1, "doc": chunks[i]["doc_id"], "title": chunks[i]["title"][:34],
                     "score": round(s, 4)} for n, (i, s) in enumerate(final)]
    rep["target_in_final"] = any(_is_target({"title": chunks[i]["title"]}) for i, _ in final)
    rep["top_score"] = round(max((s for _, s in final), default=0.0), 4)
    return rep


async def main() -> dict:
    dst = os.path.join(tempfile.gettempdir(), "p4e_qa12_probe.db")
    shutil.copyfile(str(config.DB_PATH), dst)
    config.DB_PATH = Path(dst)
    db.connect()
    chunks = db.all_chunks_for_search(config.ROLE_RANK["student"])
    print(f"可见分块 = {len(chunks)} | 库副本 = {dst}")

    qv = np.array((await rag.embed_texts([QUERY]))[0], dtype="float32")
    out: dict = {"query": QUERY, "n_chunks": len(chunks),
                 "target_doc": TARGET_DOC,
                 "target_titles": sorted({c["title"] for c in chunks if c["doc_id"] == TARGET_DOC}),
                 "schemes": []}
    # A 基线 / B 多样化(8) / C 多样化(12) / D 只扩槽位(12)
    plans = [
        ("A_baseline_fuse8", dict(fuse_top_k=rag.FUSION_TOP_K, per_doc=None)),
        ("B_diversify_fuse8", dict(fuse_top_k=rag.FUSION_TOP_K, per_doc=rag.MAX_PER_DOC)),
        ("C_diversify_fuse12", dict(fuse_top_k=12, per_doc=rag.MAX_PER_DOC)),
        ("D_widen_only_fuse12", dict(fuse_top_k=12, per_doc=None)),
    ]
    for name, kw in plans:
        rep = await run_scheme(name, chunks, qv, **kw)
        out["schemes"].append(rep)
        print(f"\n=== {name} (fuse_top_k={kw['fuse_top_k']}, per_doc={kw['per_doc']}) ===")
        print("  融合候选按 doc 计数 =", rep["fused_doc_hist"])
        for r in rep.get("rerank", []):
            print(f"  rerank doc{r['doc']:>3} {r['score']:.4f} {'PASS' if r['pass'] else '----'} {r['title']}")
        print("  >> 最终 sources:")
        for f in rep["final"]:
            print(f"     [{f['n']}] doc{f['doc']:>3} {f['score']:.4f} {f['title']}")
        print(f"  >> 目标(doc{TARGET_DOC})进最终来源 = {rep['target_in_final']}")
    out["any_scheme_hits"] = any(s["target_in_final"] for s in out["schemes"])
    print("\n[结论] 至少一个方案能让目标进最终来源 =", out["any_scheme_hits"])
    return out


if __name__ == "__main__":
    rep = asyncio.run(main())
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    print("[report]", OUT)
