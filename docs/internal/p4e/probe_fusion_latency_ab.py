#!/usr/bin/env python3
"""P4e C0-① 延迟对照：扩 `FUSION_TOP_K` 8 → 12 的**检索耗时成本**。

单据要求：「retrieval 延迟对照（8 槽 vs 12 槽各测一次 retrieve 节点 ms，扩槽位有成本要说清）」。
`docs/p4e/evidence/fusion_ab.json` 已证明**行为**侧零回退（R@k 无一下降），本探针补**成本**侧：
扩 4 个槽位意味着多 4 个候选进 rerank，`bge-reranker-v2-m3` 是逐条打分，理论上线性增加耗时。

做法：**同一批问句、同一库、同一天跑两遍**（进程内切换 `rag.FUSION_TOP_K`），
每条问句 warmup 1 次后连测 N 次取中位数，抵消首次模型加载与网络抖动。
库以只读方式打开（`mode=ro` 副本），**不写 agent.db**（红线：`agent.db` 不得被脚本改）。

⚠ 取退出码不要接管道（坑 55）：`| tail` 会让脚本收到 SIGTERM。本脚本自己落盘摘要。
用法：
    novaagent/.venv/Scripts/python.exe docs/p4e/probe_fusion_latency_ab.py
"""
from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "novaagent"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError, OSError):
    pass

OUT = ROOT / "docs" / "p4e" / "evidence" / "fusion_latency_ab.json"

# 问句**不手写**：直接从 evals/cases.json 取「带 expect_sources 的 qa/scoped_qa」，
# 与 docs/p4e/probe_fusion_ab.py 的 18 条严格同源 → 延迟数字与行为侧 A/B 可直接对照。
# ⚠ 注意：跑本探针**不要**在整轮评测中间态取数（负责人已因此把「证明 42 块」读成 44）；
#   本探针自身只读 temp 副本，与服务端评测互不干扰，但仍建议串行执行。

WARMUP = 1
REPEAT = 3


async def main() -> int:
    import os  # noqa: PLC0415
    import shutil  # noqa: PLC0415
    import tempfile  # noqa: PLC0415

    from novaagent import config, db, rag  # noqa: PLC0415

    # 与 probe_fusion_ab.py **完全同法**：只改 `config.DB_PATH` 再 `db.connect()`
    # （db 模块在 connect 时从 config.DB_PATH 取路径；不要去改 db.DB_PATH，那会绕过
    #   连接初始化，表现为 `AttributeError: 'NoneType' object has no attribute 'execute'`）。
    # 真实 agent.db 全程只被 copy 读取一次（红线：agent.db 不得被脚本改）。
    dst = os.path.join(tempfile.gettempdir(), "p4e_fusion_latency.db")
    shutil.copyfile(str(config.DB_PATH), dst)
    config.DB_PATH = Path(dst)
    db.connect()
    print(f"[db] 只读副本 = {dst}")

    cases = json.loads((ROOT / "evals" / "cases.json").read_text(encoding="utf-8"))["cases"]
    ranked = [c for c in cases
              if c.get("type") in ("qa", "scoped_qa") and c.get("expect_sources")]
    # 第二参数是 min_rank(= config.ROLE_RANK[role]),**不是** role —— 与 probe_fusion_ab.py 同口径
    queries = [(c["id"], c["question"], config.ROLE_RANK[c.get("role", "student")])
               for c in ranked]
    print(f"[cases] 带 expect_sources 的 qa/scoped_qa = {len(queries)} 条（与 probe_fusion_ab.py 同源）")

    results: dict[str, list[float]] = {}
    detail: list[dict] = []

    for slot_k in (8, 12):
        rag.FUSION_TOP_K = slot_k
        label = f"FUSION_TOP_K={slot_k}"
        for i, (cid, q, rank) in enumerate(queries):
            for _ in range(WARMUP):
                await rag.search_with_quality(q, rank)
            samples: list[float] = []
            n_src = 0
            for _ in range(REPEAT):
                t0 = time.perf_counter()
                srcs, _q = await rag.search_with_quality(q, rank)
                samples.append((time.perf_counter() - t0) * 1000.0)
                n_src = len(srcs)
            med = statistics.median(samples)
            results.setdefault(label, []).append(med)
            detail.append({"slot_k": slot_k, "case_id": cid, "ms_median": round(med, 1),
                           "ms_all": [round(s, 1) for s in samples], "n_sources": n_src})
        print(f"[{label}] done")

    # 汇总
    summary = {}
    for label, vals in results.items():
        summary[label] = {
            "n_queries": len(vals),
            "median_ms": round(statistics.median(vals), 1),
            "mean_ms": round(statistics.fmean(vals), 1),
            "p90_ms": round(sorted(vals)[max(0, int(len(vals) * 0.9) - 1)], 1),
            "min_ms": round(min(vals), 1),
            "max_ms": round(max(vals), 1),
        }
    m8 = summary["FUSION_TOP_K=8"]["median_ms"]
    m12 = summary["FUSION_TOP_K=12"]["median_ms"]
    delta_ms = round(m12 - m8, 1)
    delta_pct = round((m12 - m8) / m8 * 100, 1) if m8 else None

    report = {
        "design": "同一批问句、同一库副本、进程内切换 rag.FUSION_TOP_K；每条 warmup 1 次后连测 3 次取中位数",
        "db_source": str(config.DB_PATH),
        "n_queries": len(queries),
        "case_ids": [cid for cid, _, _ in queries],
        "warmup": WARMUP, "repeat": REPEAT,
        "summary": summary,
        "delta_median_ms": delta_ms,
        "delta_median_pct": delta_pct,
        "note": ("扩槽位只让**更多候选进 rerank**，不改变向量/关键词两路召回，"
                 "故成本增量只体现在 rerank 段；rerank 分 <RERANK_MIN_SCORE 的块会被丢弃，"
                 "不进入最终上下文，因此**生成段 token 增量远小于候选增量**。"),
        "detail": detail,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    try:
        os.remove(dst)
    except OSError:
        pass

    print("\n=== retrieve 延迟对照 ===")
    for label, s in summary.items():
        print(f"  {label:<18} 中位数 {s['median_ms']:>7.1f} ms | 均值 {s['mean_ms']:>7.1f} | "
              f"p90 {s['p90_ms']:>7.1f} | 区间 [{s['min_ms']}, {s['max_ms']}]")
    print(f"  Δ 中位数 = {delta_ms:+} ms（{delta_pct:+}%）")
    print("\n[report]", OUT)
    return 0


if __name__ == "__main__":
    import asyncio  # noqa: PLC0415

    sys.exit(asyncio.run(main()))
