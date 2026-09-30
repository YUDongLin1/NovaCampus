"""RAG 检索链路:切分 → 嵌入 → 混合检索(向量余弦 + 关键词)→ RRF 融合 → rerank

MVP 决策(均有升级路径,见 PLAN.md):
- 向量库:SQLite BLOB + 内存 numpy 余弦(语料 <1e4 块);升级:sqlite-vec/pgvector
- 关键词:LIKE 扫描计次(语料小,正确优先);升级:FTS5 trigram / BM25
- 融合:RRF(k=60);重排:硅基流动 bge-reranker-v2-m3
"""
from __future__ import annotations

import httpx
import numpy as np

from . import config, db

EMBED_BATCH = 16
RRF_K = 60
VECTOR_TOP_K = 20
KEYWORD_TOP_K = 20
FINAL_TOP_K = 7          # T10 杠杆②: 5→7,容纳通用+专门两类来源,种子"复学一周"细节块进入上下文
RERANK_MIN_SCORE = config.RERANK_MIN_SCORE  # P4a: 阈值常量迁至 config,保留别名兼容既有引用
RERANK_BLEND = 0.6       # T10 杠杆③: 最终排序 = 0.6*rerank分 + 0.4*RRF秩归一(防单文档霸榜)
MAX_PER_DOC = 2          # T10 修订: 维持 2——实测=1 会把种子文档的"复学一周"块挤出上下文(仅剩材料块)
# P4e C0-①: 融合候选槽位由 8 扩到 12(**只做加法、不剔除任何块**)。
# 断点:doc9「EVAL-研究生奖学金评定办法」向量层第 6(0.6809)但关键词层未进 top20,
# RRF 分仅 1/67 → 被 `[:FUSION_TOP_K=8]` 截掉,8 槽被两篇本科生办法占满 → 根本没进
# rerank → 答案错误否定断言"研究生相关规定未在知识库覆盖"
# (证据 docs/p4d/evidence/review/qa12_attribution.json)。
#
# ⚠ **为什么不用"截断前 per-doc 多样化"**(复核方列为修法①、且称结构性根源)——**实测打死了 qa-17**:
#   qa-17「我是研究生…学生个人荣誉称号申请…」的 before 候选分布是 doc77 占 6/8 槽,
#   它**唯一有效来源正是 doc77 的第 3+ 块**(top_score 0.6013);候选层限流到 2 之后
#   留存的两块 rerank 分都 <RERANK_MIN_SCORE → **来源数 2→0、R@k 1.0→0.0**
#   (证据 docs/p4e/evidence/fusion_strategy_probe.json)。
#   结论:rrf 高位块 ≠ rerank 高分块,**任何"剔除式"多样化都会误杀"高分块排在同文档第 3+ 位"的问法**。
#   扩槽位是纯加法,零剔除 → 对全部 18 条 qa 与 8 条变体矩阵零行为变化(除目标增召)。
#   另实测"扩槽位+多样化"(12 槽硬限流)会多召回 doc100「兼职辅导员管理办法」0.5383 过阈,
#   污染上下文 → 纯扩槽位更干净。
# ⚠ RERANK_MIN_SCORE **未动**(断点在它之前,本系列已三次确认这条纪律)。
FUSION_TOP_K = int(config.env("NOVA_FUSION_TOP_K", "12"))
# ⚠ 这里**不要**再加"FUSION_CANDIDATE_DOCS"之类的模块级观测常量(坑 52 同源):
#   候选集文档数走 `search_with_quality` 返回的 quality["fused_candidate_docs"] 字段,
#   由 graph.py 的 retrieve trace 读取。曾经在这里放过一个同名的模块常量,
#   全仓库零引用(纯死代码),已在 P4e C0 交回前删除。


def chunk_text(text: str, size: int = 500, overlap: int = 80) -> list[str]:
    """段落优先打包,超长段落硬切;保留重叠以便边界语义连续。"""
    text = text.strip()
    if not text:
        return []
    paras = [p.strip() for p in text.replace("\r\n", "\n").split("\n") if p.strip()]
    chunks: list[str] = []
    buf = ""
    for para in paras:
        while len(para) > size:  # 超长段落先硬切
            if buf:
                chunks.append(buf)
                buf = ""
            chunks.append(para[:size])
            para = para[size - overlap:]
        if len(buf) + len(para) + 1 <= size:
            buf = f"{buf}\n{para}" if buf else para
        else:
            if buf:
                chunks.append(buf)
            buf = para
    if buf:
        chunks.append(buf)
    # 加重叠:相邻块首尾拼接(简单实现,尾部 prepend 上一块末尾 overlap 字符)
    out = []
    for i, c in enumerate(chunks):
        if i > 0:
            tail = chunks[i - 1][-overlap:]
            c = f"{tail}{c}" if not c.startswith(tail) else c
        out.append(c)
    return out


async def embed_texts(texts: list[str]) -> list[list[float]]:
    vectors: list[list[float]] = []
    async with httpx.AsyncClient(timeout=60) as client:
        for i in range(0, len(texts), EMBED_BATCH):
            batch = texts[i : i + EMBED_BATCH]
            resp = await client.post(
                f"{config.EMBEDDING_BASE_URL}/embeddings",
                headers={"Authorization": f"Bearer {config.EMBEDDING_API_KEY}"},
                json={"model": config.EMBEDDING_MODEL, "input": batch},
            )
            resp.raise_for_status()
            data = sorted(resp.json()["data"], key=lambda d: d["index"])
            vectors.extend(d["embedding"] for d in data)
    return vectors


def _vector_search(query_vec: np.ndarray, chunks: list[dict], top_k: int) -> list[tuple[int, float]]:
    if not chunks:
        return []
    mat = np.stack([c["vector"] for c in chunks])
    qn = np.linalg.norm(query_vec)
    mn = np.linalg.norm(mat, axis=1)
    mn[mn == 0] = 1e-9
    sims = (mat @ query_vec) / (mn * (qn or 1e-9))
    top = np.argsort(-sims)[:top_k]
    return [(int(i), float(sims[i])) for i in top]


def _keyword_search(query: str, chunks: list[dict], top_k: int,
                    scope: dict | None = None) -> list[tuple[int, float]]:
    """关键词检索:T6 ⑥b 优先 FTS5(bm25 排序,限定角色可见集);当 db.fts_search
    返回 None(FTS5 不可用/异常/零命中/短查询)时回退内存 2-gram 计次
    (原逻辑,拒答阈值行为不变)。中文按 2-gram 兼顾分词。
    P4c C3: scope(folder_ids/categories/audience)同步下推到 FTS 层——否则 top_k
    会被 scope 外的块占满,指定小库时表现为"假性空结果"。"""
    q = query.strip()
    if not q:
        return []
    roles = sorted({c["role_min"] for c in chunks})
    fts = None
    if roles:
        sc = scope or {}
        fts = db.fts_search(q, roles, top_k,
                            folder_ids=sc.get("folder_ids"),
                            categories=sc.get("categories"),
                            audience=sc.get("audience"))
    if fts is not None:
        id_to_idx = {c["id"]: i for i, c in enumerate(chunks)}
        return [(id_to_idx[cid], sc) for cid, sc in fts if cid in id_to_idx]
    # 回退:内存 2-gram 计次(FTS5 不可用/异常/零命中;拒答阈值行为不变)
    # P4d C5②: **只对派生出的 2-gram 过滤停用词,"整句"永远保留**——
    #   ① 短查询(len<=4)的整句本身就是信号(如"学校"应当能命中《普通高等学校学生管理规定》),
    #      原始写法"过滤后 `or {q}` 兜底"会把过滤结果再加回来 = 空转(已实测,见
    #      docs/p4d/evidence/after/fts_stopwords_ab.txt);
    #   ② 长查询里"我们/学校/这项"这类通用 2-gram 会把无关块顶榜(实测教育部令霸榜),
    #      过滤它们才是本项要解决的问题。NOVA_KEYWORD_STOPWORDS=0 可关(A/B 对照)。
    terms: set[str] = {q}
    if len(q) > 4:
        grams = {q[i : i + 2] for i in range(0, len(q) - 1)}
        if config.KEYWORD_STOPWORDS_ENABLED:
            grams = {g for g in grams if g not in config.KEYWORD_STOPWORDS}
        terms |= grams
    scores: list[tuple[int, float]] = []
    for i, c in enumerate(chunks):
        s = sum(c["content"].count(t) for t in terms if len(t) >= 2)
        if s:
            scores.append((i, float(s)))
    scores.sort(key=lambda x: -x[1])
    return scores[:top_k]


def _rrf_fuse(*ranked_lists: list[tuple[int, float]]) -> list[tuple[int, float]]:
    fused: dict[int, float] = {}
    for lst in ranked_lists:
        for rank, (idx, _) in enumerate(lst):
            fused[idx] = fused.get(idx, 0.0) + 1.0 / (RRF_K + rank + 1)
    return sorted(fused.items(), key=lambda x: -x[1])


async def rerank(query: str, documents: list[str], top_n: int = FINAL_TOP_K) -> list[tuple[int, float]]:
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            f"{config.EMBEDDING_BASE_URL}/rerank",
            headers={"Authorization": f"Bearer {config.RERANK_API_KEY}"},
            json={"model": config.RERANK_MODEL, "query": query, "documents": documents, "top_n": top_n},
        )
        resp.raise_for_status()
        return [(r["index"], float(r["relevance_score"])) for r in resp.json()["results"]]


async def search(query: str, min_rank: int,
                 scope: dict | None = None) -> list[dict]:
    """混合检索 + rerank。返回 [{ref, title, content, score, role_min}]。
    P4c C3: scope={"folder_ids":[...]|None, "categories":[...]|None, "audience":str|None},
    与 RBAC 取交集(解析在 main.resolve_scope 完成,这里只做纯过滤)。"""
    sources, _ = await search_with_quality(query, min_rank, scope=scope)
    return sources


async def search_with_quality(query: str, min_rank: int,
                              scope: dict | None = None) -> tuple[list[dict], dict]:
    """混合检索 + rerank,并返回 P4a C1 拒答门控所需的质量信号。

    返回 (sources, quality):
      sources: [{ref, title, content, score, role_min}](同旧 search);
      quality: {top_score(候选中原始 rerank 峰值,降级路径为 None),
                n_above_threshold(候选中 rerank 分 ≥ RERANK_MIN_SCORE 的条数,
                                 按融合候选集合统计、在 MAX_PER_DOC/FINAL_TOP_K 截断之前),
                rerank_available(rerank 服务是否可用)}。
    P4c C3: scope 只会**收窄**候选集(db.all_chunks_for_search 在 RBAC 之上再过滤),
    不改本函数返回结构形状;folder_ids==[] 直接得空结果(硬约束 3: 不回落全库)。
    """
    quality = {"top_score": None, "n_above_threshold": 0, "rerank_available": False,
               # P4d C2: 融合候选条数——grade 判定与"是否值得改写"的输入(fused_candidates)
               "fused_candidates": 0,
               # P4e: 候选集覆盖的不同文档数(纯观测信号,不参与任何判定)
               "fused_candidate_docs": 0}
    sc = scope or {}
    chunks = db.all_chunks_for_search(min_rank,
                                      folder_ids=sc.get("folder_ids"),
                                      categories=sc.get("categories"),
                                      audience=sc.get("audience"))
    if not chunks:
        return [], quality
    qvec = np.array((await embed_texts([query]))[0], dtype="float32")
    v_ranked = _vector_search(qvec, chunks, VECTOR_TOP_K)
    k_ranked = _keyword_search(query, chunks, KEYWORD_TOP_K, scope=sc)
    fused = _rrf_fuse(v_ranked, k_ranked)[:FUSION_TOP_K]
    quality["fused_candidates"] = len(fused)
    # P4e: 观测候选集的文档集中度(纯信号,不参与判定;供 trace/评测看检索是否被单文档霸榜)
    quality["fused_candidate_docs"] = len({chunks[i]["doc_id"] for i, _ in fused})
    if not fused:
        return [], quality
    idxs = [i for i, _ in fused]
    raw_rerank: dict[int, float] = {}
    try:
        reranked = await rerank(query, [chunks[i]["content"] for i in idxs])
        raw_rerank = {idxs[pos]: sc for pos, sc in reranked}
    except Exception:  # rerank 不可用时优雅降级到 RRF 序(此路径不做 rerank 阈值拒答,阈值语义属 rerank 分)
        raw_rerank = {}
    if raw_rerank:
        quality["rerank_available"] = True
        quality["top_score"] = round(max(raw_rerank.values()), 4)
        quality["n_above_threshold"] = sum(1 for sc in raw_rerank.values() if sc >= RERANK_MIN_SCORE)
        # T10 ③: rerank 分数与 RRF 秩 blend——防止高相关但通用的单文档霸榜,
        # 让 FTS BM25+向量一致性(RRF 秩)参与最终排序,专门条款上移。
        rrf_pos = {i: p for p, (i, _) in enumerate(fused)}
        n_f = max(len(fused), 1)
        blended = sorted(
            (
                (i, RERANK_BLEND * sc + (1 - RERANK_BLEND) * (1.0 - rrf_pos.get(i, n_f) / n_f))
                for i, sc in raw_rerank.items()
            ),
            key=lambda x: -x[1],
        )
        # 拒答阈值:仍按 rerank 原始分门控(blend 只影响排序,不改拒答行为)
        picked = [(i, s) for i, s in blended if raw_rerank[i] >= RERANK_MIN_SCORE]
    else:  # rerank 不可用的降级路径:保留 RRF 序
        picked = sorted(fused, key=lambda x: -x[1])
    if not picked:
        return [], quality
    # 同文档限流,保证引用来源多样性
    doc_count: dict[int, int] = {}
    final: list[tuple[int, float]] = []
    for i, s in picked:
        doc_id = chunks[i]["doc_id"]
        if doc_count.get(doc_id, 0) >= MAX_PER_DOC:
            continue
        doc_count[doc_id] = doc_count.get(doc_id, 0) + 1
        final.append((i, s))
        if len(final) >= FINAL_TOP_K:
            break
    if not quality["rerank_available"]:
        quality["n_above_threshold"] = len(final)  # 降级路径无 rerank 分,以条数占位
    sources = [
        {
            "ref": n + 1,
            "title": chunks[i]["title"],
            "content": chunks[i]["content"],
            "score": round(s, 4),
            "role_min": chunks[i]["role_min"],
        }
        for n, (i, s) in enumerate(final)
    ]
    return sources, quality
