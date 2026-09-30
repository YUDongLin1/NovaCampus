#!/usr/bin/env python3
"""P4d-fix Review 独立探针：qa-12 变红的根因逐层归因（不采信实现方 15.7 的自述）。

要裁决的问题：④ 非答案检测把 qa-12 从 PASS 打成 FAIL，
  到底是「真实产品缺陷」（库内有对的研究生材料却召回不到 → 生成侧做了错误的否定断言），
  还是「尺子过严」（其实检索没问题、答案也有据，只是不配引用标记）？

做法：读 agent.db 的**只读副本**（不碰 :8900 正在用的库，也绝不写库），
对 qa-12 问句逐层打印 doc9/chunk19「EVAL-研究生奖学金评定办法」的秩，
并打印最终 sources。rerank/embedding 走真实外呼（问句本身不含语料，属正常检索路径）。
"""
from __future__ import annotations

import asyncio
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "novaagent"))
sys.path.insert(0, str(ROOT / "evals"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError, OSError):
    pass

import numpy as np  # noqa: E402

from novaagent import config, db, rag  # noqa: E402

QUERY = "研究生奖助学金评审是怎么规定的?"
# 目标：doc9「EVAL-研究生奖学金评定办法」正文块；对照：doc95/96 本科生奖助学金
TARGET_DOC = 9
OUT = ROOT / "docs" / "p4d" / "evidence" / "review" / "qa12_attribution.json"


def main_copy() -> str:
    dst = os.path.join(tempfile.gettempdir(), "p4dfix_review_qa12.db")
    shutil.copyfile(str(config.DB_PATH), dst)
    return dst


async def run() -> dict:
    dst = main_copy()
    config.DB_PATH = Path(dst)
    db.connect()

    chunks = db.all_chunks_for_search(config.ROLE_RANK["student"])
    tgt = [i for i, c in enumerate(chunks) if c.get("doc_id") == TARGET_DOC]
    if not tgt:
        tgt = [i for i, c in enumerate(chunks) if str(c.get("title", "")).startswith("EVAL-研究生奖学金")]
    print("可见分块 =", len(chunks), "| 目标 doc%d 的块索引 =" % TARGET_DOC, tgt,
          [chunks[i]["title"][:30] for i in tgt])
    print("副本文件 =", dst)

    rep: dict = {"query": QUERY, "n_chunks": len(chunks), "target_chunk_indexes": tgt,
                 "target_titles": [chunks[i]["title"] for i in tgt]}

    qv = np.array((await rag.embed_texts([QUERY]))[0], dtype="float32")
    v = rag._vector_search(qv, chunks, rag.VECTOR_TOP_K)
    vi = [x[0] for x in v]
    rep["vector_top8"] = [(chunks[i]["title"][:28], round(s, 4)) for i, s in v[:8]]
    rep["target_vector_rank"] = [(i, (vi.index(i) + 1 if i in vi else None)) for i in tgt]
    print("向量 top8 =", rep["vector_top8"])
    print("目标向量秩 =", rep["target_vector_rank"])

    k = rag._keyword_search(QUERY, chunks, rag.KEYWORD_TOP_K)
    ki = [x[0] for x in k]
    rep["keyword_top8"] = [(chunks[i]["title"][:28], round(s, 3)) for i, s in k[:8]]
    rep["target_keyword_rank"] = [(i, (ki.index(i) + 1 if i in ki else None)) for i in tgt]
    print("关键词 top8 =", rep["keyword_top8"])
    print("目标关键词秩 =", rep["target_keyword_rank"])

    fused = rag._rrf_fuse(v, k)[: rag.FUSION_TOP_K]
    fi = [x[0] for x in fused]
    rep["fused_titles"] = [(chunks[i]["title"][:28], round(s, 5)) for i, s in fused]
    rep["target_in_fused"] = [(i, (fi.index(i) + 1 if i in fi else None)) for i in tgt]
    print("融合 =", rep["fused_titles"])
    print("目标是否进融合 =", rep["target_in_fused"])

    idxs = [i for i, _ in fused]
    if idxs:
        rr = await rag.rerank(QUERY, [chunks[i]["content"] for i in idxs])
        rep["rerank"] = [(chunks[idxs[p]]["title"][:28], round(sc, 4),
                          sc >= rag.RERANK_MIN_SCORE) for p, sc in rr]
        print("rerank =", rep["rerank"])

    res = await rag.search(QUERY, config.ROLE_RANK["student"])
    rep["final_sources"] = [(s.get("ref"), s["title"][:34], s.get("score")) for s in res]
    rep["target_in_final"] = any(str(s["title"]).startswith("EVAL-研究生奖学金") for s in res)
    print(">> rag.search 最终返回 =", len(res), rep["final_sources"])
    print(">> 目标(研究生奖学金)是否进入最终来源 =", rep["target_in_final"])

    # 补充：doc9 正文是否含「评审」「助学金」——实现方称不含，须独立复核
    co = db.conn() if hasattr(db, "conn") else None
    rep["target_content_flags"] = {}
    for i in tgt:
        body = chunks[i]["content"]
        rep["target_content_flags"][chunks[i]["title"][:24]] = {
            kw: (kw in body) for kw in ("研究生", "奖学金", "评审", "助学金", "评定")}
    print("目标正文关键词命中 =", rep["target_content_flags"])

    db.close() if hasattr(db, "close") else None
    return rep


if __name__ == "__main__":
    rep = asyncio.run(run())
    OUT.parent.mkdir(parents=True, exist_ok=True)
    import json
    json.dump(rep, open(str(OUT), "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("[report]", OUT)
