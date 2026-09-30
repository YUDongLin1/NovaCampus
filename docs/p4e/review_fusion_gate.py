#!/usr/bin/env python3
"""P4e 中途复核（Qoder 独立跑，只读）：C0-① `FUSION_TOP_K` 8→12 的真实影响面。

为什么必须自己跑：实现方**拒绝了我给的修法①**（截断前 per-doc 多样化），理由是会打死 qa-17，
改用纯扩槽位，并声称"对全部 18 条 qa 与 8 条矩阵零行为变化(除目标增召)"。
按本项目纪律，别人推翻我的方案我要用**自己的实测**判断，不采信回执。

最大风险不是 qa-12 修没修好，而是**候选变多会不会让该拒答的问题拿到来源**：
P4a 拒答硬门控按 `n_above_threshold`/`top_score` 判定，`refusal_indomain`（尤其 `rind-07`）
期望 sources=0。扩槽位是"纯加法"，但加法会喂给 rerank 更多块 → 更多块可能过 0.3。

用法：A/B 靠实现方新加的 env 开关 `NOVA_FUSION_TOP_K`（不改代码、不写库）。
只读 agent.db 的**副本**；证据写到仓库外（WorkBuddy 正持棒，我不往工作树里写任何东西）。
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(r"E:/AILearn/NovaCampus")
OUT_DIR = os.environ.get("QODER_REVIEW_OUT") or str(ROOT / "docs" / "p4e" / "evidence" / "review")
OUT = Path(OUT_DIR) / "p4e_midflight_fusion_ab.json"
OUT.parent.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(ROOT / "novaagent"))
sys.path.insert(0, str(ROOT / "evals"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError, OSError):
    pass

import numpy as np  # noqa: E402

from novaagent import config, db, rag  # noqa: E402

DB_COPY = os.path.join(tempfile.gettempdir(), "p4e_review_fusion_ab.db")
shutil.copyfile(str(ROOT / "novaagent" / "data" / "agent.db"), DB_COPY)
config.DB_PATH = Path(DB_COPY)

TARGET_DOC_TITLE = "EVAL-研究生奖学金评定办法"


def cases_of(*types):
    spec = json.loads((ROOT / "evals" / "cases.json").read_text(encoding="utf-8"))
    return [c for c in spec["cases"] if c["type"] in types]


async def one(query: str, slots: int) -> dict:
    rag.FUSION_TOP_K = slots
    min_rank = config.ROLE_RANK["student"]
    chunks = db.all_chunks_for_search(min_rank)
    qv = np.array((await rag.embed_texts([query]))[0], dtype="float32")
    v = rag._vector_search(qv, chunks, rag.VECTOR_TOP_K)
    k = rag._keyword_search(query, chunks, rag.KEYWORD_TOP_K)
    fused_all = rag._rrf_fuse(v, k)
    fused = fused_all[:slots]
    vi = [i for i, _ in v]
    tgt = [i for i, c in enumerate(chunks) if str(c.get("title", "")).startswith(TARGET_DOC_TITLE)]
    res = await rag.search_with_quality(query, min_rank)
    sources, quality = res if isinstance(res, tuple) else (res, {})
    return {
        "slots": slots,
        "target_chunk_idx": tgt,
        "target_vector_rank": [(i, (vi.index(i) + 1 if i in vi else None)) for i in tgt],
        "target_in_fused": [i in [x[0] for x in fused] for i in tgt],
        "n_sources": len(sources),
        "titles": [s["title"][:30] for s in sources],
        "target_in_final": any(str(s["title"]).startswith(TARGET_DOC_TITLE) for s in sources),
        "top_score": quality.get("top_score"),
        "n_above_threshold": quality.get("n_above_threshold"),
        "fused_candidates": quality.get("fused_candidates"),
        "fused_candidate_docs": quality.get("fused_candidate_docs"),
    }


async def main() -> None:
    db.connect()
    print("KB 副本 =", DB_COPY)
    print("rag.FUSION_TOP_K 默认(实现方新代码) =", rag.FUSION_TOP_K,
          "| config 开关 NOVA_FUSION_TOP_K =", os.environ.get("NOVA_FUSION_TOP_K", "(unset)"))
    print("RERANK_MIN_SCORE =", rag.RERANK_MIN_SCORE, "config =", config.RERANK_MIN_SCORE)

    qa12 = next(c for c in cases_of("qa") if c["id"] == "qa-12")
    qa17 = next(c for c in cases_of("qa") if c["id"] == "qa-17")
    rinds = [c for c in cases_of("refusal_indomain") if c["id"] != "rind-02"]
    rind07 = next(c for c in cases_of("refusal_indomain") if c["id"] == "rind-07")
    rewrite = cases_of("rewrite")

    probes = [("qa-12", qa12["question"]), ("qa-17", qa17["question"]),
              ("rind-07", rind07["question"])] + [(c["id"], c["question"]) for c in rinds] + \
             [("rewrite-01", rewrite[0]["question"]), ("rewrite-02", rewrite[1]["question"])]

    rep = {}
    print("\n%-11s %-6s %s" % ("probe", "slots", "n_sources top n_above fused(docs) target_in_final"))
    for name, q in probes:
        for slots in (8, 12):
            r = await one(q, slots)
            rep.setdefault(name, {})[str(slots)] = r
            print("%-11s %-6s %-3d  top=%s n_above=%s fused=%s/docs=%s%s"
                  % (name, slots, r["n_sources"], r["top_score"], r["n_above_threshold"],
                     r["fused_candidates"], r["fused_candidate_docs"],
                     ("  TARGET_IN_FINAL=" + str(r["target_in_final"])) if name in ("qa-12",) else ""))
        a, b = rep[name]["8"], rep[name]["12"]
        flag = "SAME" if (a["n_sources"] == b["n_sources"] and a["titles"] == b["titles"]) else "CHANGED"
        print("           -> 8 vs 12: %s" % flag)
        if flag == "CHANGED":
            print("             8  :", a["titles"])
            print("             12 :", b["titles"])

    # 断言（会判红）
    print("\n=== 复核断言 ===")
    fails = []
    t12 = rep["qa-12"]["12"]
    if not t12["target_in_final"]:
        fails.append("qa-12: 扩槽位后目标块 doc9 仍未进最终 sources → C0-① 未真修好")
    r7_8, r7_12 = rep["rind-07"]["8"], rep["rind-07"]["12"]
    if r7_12["n_sources"] > r7_8["n_sources"] and r7_8["n_sources"] == 0:
        fails.append("rind-07: 8 槽时 sources=0，12 槽变成 %d → 该拒答的问题拿到了来源(会破坏 refusal_indomain)"
                     % r7_12["n_sources"])
    for name in ("ref-01", "ref-02", "ref-03", "ref-04", "ref-05", "ref-06",
                 "rind-01", "rind-03", "rind-04", "rind-05", "rind-06"):
        if name in rep and rep[name]["8"]["n_sources"] != rep[name]["12"]["n_sources"]:
            fails.append("%s: 来源数变化 %d→%d，需判性质" % (name, rep[name]["8"]["n_sources"],
                                                            rep[name]["12"]["n_sources"]))
    for line in fails:
        print("  [FAIL]", line)
    if not fails:
        print("  [OK] qa-12 增召成功；rind-07 与各拒答用例在 8/12 槽下行为一致")
    print("\n[verdict] %s" % ("PASS" if not fails else "%d 项需处理" % len(fails)))

    rep["_verdict"] = {"fails": fails, "RERANK_MIN_SCORE": rag.RERANK_MIN_SCORE,
                       "fusion_default": rag.FUSION_TOP_K}
    json.dump(rep, open(str(OUT), "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("[report]", OUT)
    sys.exit(1 if fails else 0)


asyncio.run(main())
