#!/usr/bin/env python3
"""诊断:为什么"学平险"问句检索不到已入库的 2 个分块(HANDOFF 坑 16 的标准动作)"""
import asyncio
import sys

sys.path.insert(0, ".")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError, OSError):
    pass

import numpy as np

from novaagent import config, db, rag

# P4d: 默认改为矩阵里**失败**的三条(术语+具体意图 / 学生原句 / 书面正式名),
# 用于证明"向量层本已排到前列、rerank + 一刀切阈值把它放大成零来源";命令行可覆盖。
QUERIES = [
    "学平险在哪里买",
    "我们学校有学平险吗，我看我们计财处只有医保这项",
    "学生平安保险是否由学校统一办理？",
]
if len(sys.argv) > 1:
    QUERIES = sys.argv[1:]


async def diag(q: str) -> None:
    print("=" * 78)
    print("Q:", q)
    min_rank = config.ROLE_RANK["student"]
    chunks = db.all_chunks_for_search(min_rank)
    print("  可见分块总数 =", len(chunks), "| FTS 可用 =", db.fts_available())

    hits = [(i, c) for i, c in enumerate(chunks) if "学平险" in c["content"] or "学生平安" in c["content"]]
    print("  含'学平险/学生平安'的分块 =", [(i, c["title"][:28]) for i, c in hits])

    qv = np.array((await rag.embed_texts([q]))[0], dtype="float32")
    v = rag._vector_search(qv, chunks, rag.VECTOR_TOP_K)
    print("  向量 top5 =", [(chunks[i]["title"][:20], round(s, 4)) for i, s in v[:5]])
    print("  目标分块向量秩 =", [(i, [x[0] for x in v].index(i) + 1 if i in [x[0] for x in v] else None,
                                 round(qv @ chunks[i]["vector"] / (np.linalg.norm(qv) * np.linalg.norm(chunks[i]["vector"])), 4))
                                for i, _ in hits])

    k = rag._keyword_search(q, chunks, rag.KEYWORD_TOP_K)
    print("  关键词 top5 =", [(chunks[i]["title"][:20], round(s, 3)) for i, s in k[:5]])
    print("  目标分块关键词秩 =", [([x[0] for x in k].index(i) + 1 if i in [x[0] for x in k] else None) for i, _ in hits])

    fused = rag._rrf_fuse(v, k)[: rag.FUSION_TOP_K]
    print("  融合 top8 =", [(chunks[i]["title"][:20], round(s, 5)) for i, s in fused])
    print("  目标是否进融合 =", [i in [x[0] for x in fused] for i, _ in hits])

    idxs = [i for i, _ in fused]
    if idxs:
        try:
            rr = await rag.rerank(q, [chunks[i]["content"] for i in idxs])
            print("  rerank =", [(chunks[idxs[p]]["title"][:20], round(sc, 4),
                                 "PASS" if sc >= rag.RERANK_MIN_SCORE else "below0.3") for p, sc in rr])
        except Exception as e:
            print("  rerank 失败:", type(e).__name__, str(e)[:120])

    res = await rag.search(q, min_rank)
    print("  >> rag.search 最终返回 =", len(res), [(s["ref"], s["title"][:24], s["score"]) for s in res])


async def main() -> None:
    db.connect()
    for q in QUERIES:
        await diag(q)


asyncio.run(main())
