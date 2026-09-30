#!/usr/bin/env python3
"""P4d 诊断:确定性术语展开(expand_terms)在失败问句上的实效 —— 决定改写阶梯首档。

对照三档:
  A) 原句
  B) expand_terms(原句)      —— 现实现的"去噪 + 追加同义词"
  C) compact(原句)           —— 去噪 + 术语展开 + 意图词收紧(拟新增的确定性归一)
"""
import asyncio
import sys

sys.path.insert(0, ".")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError, OSError):
    pass

from novaagent import config, db, graph, rag

QUERIES = [
    "学平险在哪里买",
    "我们学校有学平险吗，我看我们计财处只有医保这项",
    "我看计财处只有医保这一项，那学校还给学平险吗",
    "老师，我想问下咱们学校那个学平险是要单独交钱吗，我没在缴费项目里看到",
    "学生平安保险是否由学校统一办理？",
    "关于学生在校期间的意外与医疗保障，除了城乡居民基本医疗保险之外，学校是否还统一办理学生平安保险？",
    "我们学校有没有量子计算实验室开放日预约",
]


def is_target(s: dict) -> bool:
    return "学平险" in (s.get("title") or "") or "学生平安" in (s.get("content") or "")


async def main() -> None:
    db.connect()
    min_rank = config.ROLE_RANK["student"]
    print(f"{'原句':32s} {'档':4s} {'改写式':50s} {'top':>7s} {'n_above':>7s} {'src':>4s} {'命中':>4s}")
    for q in QUERIES:
        forms = [("A", q), ("B", graph.expand_terms(q))]
        for tag, fq in forms:
            src, quality = await rag.search_with_quality(fq, min_rank)
            hits = sum(1 for s in src if is_target(s))
            print(f"{q[:30]:32s} {tag:4s} {fq[:48]:50s} "
                  f"{str(quality.get('top_score')):>7s} {quality.get('n_above_threshold'):>7d} "
                  f"{len(src):>4d} {hits:>4d}")
        print()


asyncio.run(main())
