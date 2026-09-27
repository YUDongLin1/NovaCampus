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
FUSION_TOP_K = 8
FINAL_TOP_K = 5
RERANK_MIN_SCORE = 0.3   # 低于该相关度的分块不作为回答依据(拒答机制)
MAX_PER_DOC = 2          # 同一文档最多引用条数,保证来源多样性


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


def _keyword_search(query: str, chunks: list[dict], top_k: int) -> list[tuple[int, float]]:
    """关键词检索:T6 ⑥b 优先 FTS5(bm25 排序,限定角色可见集);当 db.fts_search
    返回 None(FTS5 不可用/异常/零命中/短查询)时回退内存 2-gram 计次
    (原逻辑,拒答阈值行为不变)。中文按 2-gram 兼顾分词。"""
    q = query.strip()
    if not q:
        return []
    roles = sorted({c["role_min"] for c in chunks})
    fts = db.fts_search(q, roles, top_k) if roles else None
    if fts is not None:
        id_to_idx = {c["id"]: i for i, c in enumerate(chunks)}
        return [(id_to_idx[cid], sc) for cid, sc in fts if cid in id_to_idx]
    # 回退:内存 2-gram 计次(FTS5 不可用/异常/零命中;拒答阈值行为不变)
    terms = {q} if len(q) <= 4 else {q, *(q[i : i + 2] for i in range(0, len(q) - 1))}
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


async def search(query: str, min_rank: int) -> list[dict]:
    """混合检索 + rerank。返回 [{ref, title, content, score, role_min}]。"""
    chunks = db.all_chunks_for_search(min_rank)
    if not chunks:
        return []
    qvec = np.array((await embed_texts([query]))[0], dtype="float32")
    v_ranked = _vector_search(qvec, chunks, VECTOR_TOP_K)
    k_ranked = _keyword_search(query, chunks, KEYWORD_TOP_K)
    fused = _rrf_fuse(v_ranked, k_ranked)[:FUSION_TOP_K]
    if not fused:
        return []
    idxs = [i for i, _ in fused]
    try:
        reranked = await rerank(query, [chunks[i]["content"] for i in idxs])
        picked = [(idxs[i], s) for i, s in reranked]
    except Exception:  # rerank 不可用时优雅降级到 RRF 序
        picked = fused
    # 相关度阈值过滤:全部低于阈值视为"知识库未覆盖",触发拒答
    picked = [(i, s) for i, s in picked if s >= RERANK_MIN_SCORE]
    if not picked:
        return []
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
    return [
        {
            "ref": n + 1,
            "title": chunks[i]["title"],
            "content": chunks[i]["content"],
            "score": round(s, 4),
            "role_min": chunks[i]["role_min"],
        }
        for n, (i, s) in enumerate(final)
    ]
