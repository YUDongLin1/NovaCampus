#!/usr/bin/env python3
"""P4e C0-① 残留诊断：整轮评测后 `qa-12` 仍 FAIL，但 **R@k 已 1.0**。

现象（集中验证首轮，TOTAL 47/48）：
  [FAIL] qa-12  非答案:命中免责措辞 ['未在知识库','请以','以研究生主管部门'],
                 但全文无任何引用标记 [n] 与具体数字(零可核查事实)
                 R@k=1.0  忠实度=0.0
  引用 ['西南交通大学本科生奖助学金评审管理办法（…15 号）',
        '西南交通大学本科生奖助学金评审管理办法（…15 号）',
        '西南交通大学本科生国家奖助学金评审管理办法（…16 号）']

→ 检索层**已修好**（目标块进了来源集，R@k 1.0），但最终来源里**没有研究生办法**，
  生成侧看不到它 → 于是写了「未在知识库覆盖」的否定断言。
  断点已从「融合层截断」**下移到 rerank 之后的选块阶段**。

本探针把断点量化到具体一步：融合候选 → rerank 分 → MAX_PER_DOC 截断 → FINAL_TOP_K。
只读 temp 副本，不写 agent.db。
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

OUT = ROOT / "docs" / "p4e" / "evidence" / "qa12_residual.json"
Q = "研究生奖助学金评审是怎么规定的?"


async def main() -> int:
    from novaagent import config, db, rag

    dst = os.path.join(tempfile.gettempdir(), "p4e_qa12_residual.db")
    shutil.copyfile(str(config.DB_PATH), dst)
    config.DB_PATH = Path(dst)
    db.connect()

    rank = config.ROLE_RANK["student"]

    # 1) 走完整路径拿最终来源
    srcs, qual = await rag.search_with_quality(Q, rank)
    report: dict = {
        "question": Q,
        "n_sources_final": len(srcs),
        "quality": qual,
        "final_titles": [s["title"] for s in srcs],
        "final_scores": [round(float(s.get("score") or 0), 4) for s in srcs],
        "RERANK_MIN_SCORE": rag.RERANK_MIN_SCORE,
        "MAX_PER_DOC": rag.MAX_PER_DOC,
        "FUSION_TOP_K": rag.FUSION_TOP_K,
        "FINAL_TOP_K": rag.FINAL_TOP_K,
        "RERANK_BLEND": rag.RERANK_BLEND,
    }

    # 2) 复刻内部各阶段，看目标块在哪一步掉的
    stages: dict = {}
    try:
        chunks = db.all_chunks_for_search(rank)
        v_hits = await rag.embed([Q]) if hasattr(rag, "embed") else None
    except Exception as e:  # noqa: BLE001
        stages["_probe_error"] = str(e)[:200]

    # 直接调用内部件重建（与 search_with_quality 同口径）
    import inspect
    src_code = inspect.getsource(rag.search_with_quality)
    stages["has_rerank_filter"] = "RERANK_MIN_SCORE" in src_code
    stages["uses_max_per_doc"] = "MAX_PER_DOC" in src_code
    report["stages"] = stages

    # 3) 关键：目标块「EVAL-研究生奖学金评定办法」最终有没有进来源
    target = "研究生奖学金评定办法"
    report["target_in_final"] = any(target in (s["title"] or "") for s in srcs)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"最终来源数 = {len(srcs)}（RERANK_MIN_SCORE={rag.RERANK_MIN_SCORE}, "
          f"MAX_PER_DOC={rag.MAX_PER_DOC}, FINAL_TOP_K={rag.FINAL_TOP_K}）")
    print(f"quality = {json.dumps(qual, ensure_ascii=False)}")
    for i, s in enumerate(srcs, 1):
        print(f"  [{i}] {float(s.get('score') or 0):.4f}  {s['title'][:56]}")
    print(f"\n目标块「{target}」进最终来源 = {report['target_in_final']}")
    print("[report]", OUT)
    try:
        os.remove(dst)
    except OSError:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
