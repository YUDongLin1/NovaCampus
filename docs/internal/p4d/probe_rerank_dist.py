#!/usr/bin/env python3
"""P4d 诊断:rerank 分数分布(决定"分级阈值/保底候选"该怎么定)。

对矩阵里的失败问句,打印**融合候选全体**的 rerank 分(list 顺序=融合位次),
并标注哪些候选是目标材料(标题含"学平险"或正文含"学生平安")。
同时打印向量层 top1 候选与查询的余弦相似度,判断"向量层是否本已排到前列"。
"""
import asyncio
import sys

sys.path.insert(0, ".")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError, OSError):
    pass

import numpy as np

from novaagent import config, db, rag

QUERIES = [
    ("术语+具体意图", "学平险在哪里买"),
    ("真实原句(学生口吻)", "我们学校有学平险吗，我看我们计财处只有医保这项"),
    ("背景前置倒装", "我看计财处只有医保这一项，那学校还给学平险吗"),
    ("口语加称呼情境", "老师，我想问下咱们学校那个学平险是要单独交钱吗，我没在缴费项目里看到"),
    ("书面正式名", "学生平安保险是否由学校统一办理？"),
    ("[对照]能过的多子句", "关于学生在校期间的意外与医疗保障，除了城乡居民基本医疗保险之外，学校是否还统一办理学生平安保险？"),
    ("[对照]域外(kb_hidden)", "我们学校有没有量子计算实验室开放日预约"),
]


def is_target(c: dict) -> bool:
    return "学平险" in (c.get("title") or "") or "学生平安" in (c.get("content") or "")


async def main() -> None:
    db.connect()
    chunks = db.all_chunks_for_search(config.ROLE_RANK["student"])
    for label, q in QUERIES:
        qv = np.array((await rag.embed_texts([q]))[0], dtype="float32")
        v = rag._vector_search(qv, chunks, rag.VECTOR_TOP_K)
        k = rag._keyword_search(q, chunks, rag.KEYWORD_TOP_K)
        fused = rag._rrf_fuse(v, k)[: config.FUSION_TOP_K if hasattr(config, "FUSION_TOP_K") else rag.FUSION_TOP_K]
        idxs = [i for i, _ in fused]
        rr = await rag.rerank(q, [chunks[i]["content"] for i in idxs])
        scores = {idxs[pos]: sc for pos, sc in rr}
        ordered = sorted(scores.items(), key=lambda x: -x[1])
        # 向量层 top1 的余弦相似度
        vtop = v[0][1] if v else None
        print("=" * 100)
        print(f"[{label}] {q}")
        print(f"  融合候选={len(idxs)} 向量top1余弦={vtop:.4f}")
        for rank, (ci, sc) in enumerate(ordered, 1):
            tag = "★目标" if is_target(chunks[ci]) else "     "
            fused_rank = idxs.index(ci) + 1
            print(f"   rerank#{rank} score={sc:.4f} 融合位次={fused_rank:2d} {tag} "
                  f"《{chunks[ci]['title'][:34]}》 {chunks[ci]['content'][:34]!r}")


asyncio.run(main())
