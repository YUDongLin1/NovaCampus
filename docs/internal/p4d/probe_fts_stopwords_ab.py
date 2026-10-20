#!/usr/bin/env python3
"""P4d C5② 证据:关键词回退层(内存 2-gram 计次)加停用词过滤的 A/B 实测。

只在 FTS5 短语检索不可用时(短查询 <3 字 / 零命中 / FTS 异常)才会走到该层,
故选取**短查询**做对照。对照口径:该层 top-5 候选标题里"目标/无关"的构成,
以及融合层最终来源。
用法:NO_PROXY=... python probe_fts_stopwords_ab.py   (需在同一进程内翻转开关,故直接改 config)
"""
import asyncio
import sys

sys.path.insert(0, ".")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError, OSError):
    pass

from novaagent import config, db, rag

QUERIES = ["学平险", "医保", "报销", "学校",
           "我们学校这项规定是怎么说的",
           "我想知道学校对于这项工作的具体规定是什么",
           "请问我们学校这项事务应该怎么办理呢"]
UNRELATED = ("辅导员", "公寓", "考核", "岗位", "宿舍")


def head_title(chunks, idx):
    return chunks[idx]["title"][:30]


async def main() -> None:
    db.connect()
    chunks = db.all_chunks_for_search(config.ROLE_RANK["student"])
    for q in QUERIES:
        fts = db.fts_search(q, sorted({c["role_min"] for c in chunks}), rag.KEYWORD_TOP_K)
        mode = "FTS5" if fts is not None else "内存2-gram回退"
        print("=" * 92)
        print(f"[{q}] 命中路径={mode}")
        for label, enabled in (("停用词过滤 开", True), ("停用词过滤 关", False)):
            config.KEYWORD_STOPWORDS_ENABLED = enabled
            k = rag._keyword_search(q, chunks, rag.KEYWORD_TOP_K)
            tops = [head_title(chunks, i) for i, _ in k[:5]]
            noise = sum(1 for t in tops if any(u in t for u in UNRELATED))
            print(f"  {label}: top5={tops}")
            print(f"     其中通用/无关文档 {noise} 条")
        config.KEYWORD_STOPWORDS_ENABLED = True


asyncio.run(main())
