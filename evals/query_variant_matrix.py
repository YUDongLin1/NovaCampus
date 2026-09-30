#!/usr/bin/env python3
"""问法变体矩阵:同一知识点(学平险),测什么措辞会让检索崩掉(CASE_STUDY 的量化依据)

直接调 rag / graph 内部(不依赖 :8900 服务)。**双栏输出**:
  - 单遍列(raw):rag.search 一次检索。逐层记录向量秩/关键词命中/融合入榜/rerank 峰值/最终条数。
    这一列是 F2 崩塌的**原始证据**,语义与 P4c 之前完全一致(BEFORE/AFTER 可直接对读)。
  - 编排列(pipeline):graph.retrieve_with_retry 走 retrieve→grade→rewrite→retrieve(P4d 新增能力)。
    这一列回答"改写上线后是否救回"。`NOVA_MAX_REWRITE=0` 时该列退化为单遍,可做消融对照。

判定"目标材料"= 标题含"学平险"或正文含"学生平安"的分块。
"""
import asyncio
import io
import os
import sys

sys.path.insert(0, ".")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError, OSError):
    pass

import numpy as np

from novaagent import config, db, graph, rag

# P4d: 支持命令行指定输出路径(默认仍写历史路径);本单 before/after 需同名配对落盘
REPORT = sys.argv[1] if len(sys.argv) > 1 else "../docs/p4/evidence/query_variant_matrix.txt"

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


def _is_target(chunk_or_source: dict) -> bool:
    return "学平险" in (chunk_or_source.get("title") or "") \
        or "学生平安" in (chunk_or_source.get("content") or "")


async def probe(chunks, q: str) -> dict:
    """单遍列:逐层诊断(语义与 P4c 版本一致,便于与 BEFORE 对读)。"""
    target = [i for i, c in enumerate(chunks) if _is_target(c)]
    qv = np.array((await rag.embed_texts([q]))[0], dtype="float32")
    v = rag._vector_search(qv, chunks, rag.VECTOR_TOP_K)
    vpos = {i: r + 1 for r, (i, _) in enumerate(v)}
    k = rag._keyword_search(q, chunks, rag.KEYWORD_TOP_K)
    kpos = {i: r + 1 for r, (i, _) in enumerate(k)}
    fused = rag._rrf_fuse(v, k)[: rag.FUSION_TOP_K]
    fpos = {i: r + 1 for r, (i, _) in enumerate(fused)}
    idxs = [i for i, _ in fused]
    best = None
    if idxs:
        try:
            rr = await rag.rerank(q, [chunks[i]["content"] for i in idxs])
            scores = {idxs[pos]: sc for pos, sc in rr}
            tg = [scores[i] for i in target if i in scores]
            best = max(tg) if tg else None
        except Exception:
            best = None
    res = await rag.search(q, config.ROLE_RANK["student"])
    hit = [s for s in res if _is_target(s)]
    return {
        "q": q, "n": len(q), "v_rank": [vpos.get(i) for i in target],
        "k_rank": [kpos.get(i) for i in target], "f_rank": [fpos.get(i) for i in target],
        "rerank_best": best, "n_sources": len(res), "n_hit_target": len(hit),
        "top_score": res[0]["score"] if res else None,
    }


async def probe_pipeline(q: str) -> dict:
    """编排列:graph.retrieve_with_retry(retrieve→grade→rewrite→retrieve)。

    注意:该列**不含 intent 节点**(矩阵测的是检索链本身,不掺意图判定的一次 LLM 调用),
    因此 `NOVA_MAX_REWRITE=0` 时与单遍列完全等价——这正是消融对照的依据。
    """
    out = await graph.retrieve_with_retry(q, config.ROLE_RANK["student"])
    res = out["sources"]
    hit = [s for s in res if _is_target(s)]
    rew = [t for t in out["trace"] if t.get("node") == "rewrite"]
    return {
        "n_sources": len(res), "n_hit_target": len(hit),
        "attempts": out["attempts"], "rewritten": bool(out["rewritten"]),
        "rewrite_to": rew[-1]["to"] if rew else "",
        "trace_nodes": [t.get("node") for t in out["trace"]],
    }


async def main() -> None:
    db.connect()
    chunks = db.all_chunks_for_search(config.ROLE_RANK["student"])
    tgt = [i for i, c in enumerate(chunks) if _is_target(c)]
    rows = []
    for label, q in VARIANTS:
        r = await probe(chunks, q)
        r["label"] = label
        r["pipeline"] = await probe_pipeline(q)
        rows.append(r)
        p = r["pipeline"]
        print("[%s] 单遍: 向量秩=%s 关键词秩=%s 融合秩=%s rerank=%s -> sources=%d 命中=%d"
              % (label, r["v_rank"], r["k_rank"], r["f_rank"],
                 ("%.4f" % r["rerank_best"]) if r["rerank_best"] is not None else "None",
                 r["n_sources"], r["n_hit_target"]))
        print("%-14s 编排: attempts=%d 改写=%s%s -> sources=%d 命中=%d"
              % ("", p["attempts"], "是" if p["rewritten"] else "否",
                 ("(→%s)" % p["rewrite_to"]) if p["rewrite_to"] else "",
                 p["n_sources"], p["n_hit_target"]))

    out = io.open(REPORT, "w", encoding="utf-8")
    out.write("问法变体矩阵 · 同一知识点(学平险) · 目标分块=%s《%s》等 %d 块\n" % (
        tgt, chunks[tgt[0]]["title"], len(tgt)))
    out.write("RERANK_MIN_SCORE=%s FUSION_TOP_K=%s FINAL_TOP_K=%s MAX_PER_DOC=%s MAX_REWRITE=%s "
              "GRADE_MIN_SCORE=%s GRADE_MIN_ABOVE=%s\n" % (
                  rag.RERANK_MIN_SCORE, rag.FUSION_TOP_K, rag.FINAL_TOP_K, rag.MAX_PER_DOC,
                  config.MAX_REWRITE, config.GRADE_MIN_SCORE, config.GRADE_MIN_ABOVE))
    out.write("\n【列 A】单遍检索(逐层诊断,与 P4c BEFORE 同语义)\n")
    out.write("%-14s %-4s %-14s %-16s %-12s %-10s %-9s %-9s %s\n" % (
        "措辞类型", "字数", "向量层秩", "关键词层秩", "融合层秩", "目标rerank峰值", "返回条数", "命中目标", "判定"))
    for r in rows:
        verdict = "OK" if r["n_hit_target"] else (
            "崩塌(rerank<%.2f)" % rag.RERANK_MIN_SCORE
            if r["rerank_best"] is not None and r["rerank_best"] < rag.RERANK_MIN_SCORE
            else ("崩塌(未进融合)" if None in r["f_rank"] else "崩塌(其他)"))
        out.write("%-14s %-4d %-14s %-16s %-12s %-10s %-9d %-9d %s\n" % (
            r["label"], r["n"], r["v_rank"], r["k_rank"], r["f_rank"],
            ("%.4f" % r["rerank_best"]) if r["rerank_best"] is not None else "-",
            r["n_sources"], r["n_hit_target"], verdict))
    out.write("\n【列 B】编排检索(retrieve→grade→rewrite→retrieve, P4d 新增)\n")
    out.write("%-14s %-9s %-7s %-30s %-9s %-9s %s\n" % (
        "措辞类型", "检索轮数", "发生改写", "末次改写式", "返回条数", "命中目标", "判定"))
    for r in rows:
        p = r["pipeline"]
        out.write("%-14s %-9d %-7s %-30s %-9d %-9d %s\n" % (
            r["label"], p["attempts"], "是" if p["rewritten"] else "否",
            (p["rewrite_to"] or "-")[:30], p["n_sources"], p["n_hit_target"],
            "OK" if p["n_hit_target"] else "未救回"))
    out.write("\n结论口径:向量层秩=目标分块在 top20 中的名次(None=未进 top20);"
              "命中目标=最终 sources 里属于目标文档的条数;判定 OK 要求命中目标>=1。\n")
    out.write("列 A 是原始崩塌证据(单遍检索能力);列 B 是 P4d 编排后的**用户实际可得结果**。\n")
    out.write("消融对照:NOVA_MAX_REWRITE=0 时列 B 退化为列 A,可证明提升全部来自改写重试。\n")
    out.close()
    ok_a = sum(1 for r in rows if r["n_hit_target"])
    ok_b = sum(1 for r in rows if r["pipeline"]["n_hit_target"])
    print("[SUM] 单遍 %d/%d | 编排(含改写,MAX_REWRITE=%d) %d/%d"
          % (ok_a, len(rows), config.MAX_REWRITE, ok_b, len(rows)))


asyncio.run(main())
