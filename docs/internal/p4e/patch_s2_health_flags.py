#!/usr/bin/env python3
"""P4e S2-②①: `/api/health` 暴露服务端**生效配置**,让每份评测报告自带"当时是什么配置"。

动机(复核方):报告 JSON 顶层只有 version/base/summary/results/total_pass/total/eval_isolation,
**不记录 env 标志** → 后人拿到一份 55/55 无法判断是怎么跑出来的(例如 stream_sse 的
重生通道断言依赖 `NOVA_GROUNDING_STREAM_FORCE_UNGROUNDED=1`,默认关闭时该用例必然红)。

⚠ 为什么读**服务端**而不是客户端 env:客户端与服务可能不在同一进程/同一 env 下
(坑 57 同源 —— "连的是哪个实例"才是决定性的)。客户端 env 仍一并记入,便于对照。

用法: novaagent/.venv/Scripts/python.exe docs/p4e/patch_s2_health_flags.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAIN = ROOT / "novaagent" / "novaagent" / "main.py"
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError, OSError):
    pass

OLD = '''@app.get("/api/health")
async def health():
    return {"status": "ok", "weekly_mcp": agent.weekly.session is not None}
'''

NEW = '''@app.get("/api/health")
async def health():
    # P4e S2-②: 暴露**本进程生效**的关键配置,供评测/排障把"当时是什么配置"写进报告。
    # 只读、无敏感字段(不含 key/口令)。新增字段对既有消费端(冒烟连通性检查)无影响。
    try:
        flags = {
            "grounding_gate_enabled": config.GROUNDING_GATE_ENABLED,
            "grounding_early_window_chars": config.GROUNDING_EARLY_WINDOW_CHARS,
            "grounding_stream_force_ungrounded": config.GROUNDING_STREAM_FORCE_UNGROUNDED,
            "web_search_enabled_default": config.WEB_SEARCH_ENABLED,
            "web_search_timeout_s": config.WEB_SEARCH_TIMEOUT_S,
            "web_search_max_sources": config.WEB_SEARCH_MAX_SOURCES,
            "graph_enabled": config.GRAPH_ENABLED,
            "max_rewrite": config.MAX_REWRITE,
            "llm_model": config.LLM_MODEL,
            "eval_temperature": os.environ.get("NOVAAGENT_EVAL_TEMPERATURE", ""),
        }
    except Exception as e:  # noqa: BLE001  — 自检字段不该让 health 挂掉
        logger.warning("health flags 组装失败: %s", e)
        flags = {}
    return {"status": "ok", "weekly_mcp": agent.weekly.session is not None, "flags": flags}
'''

IMP_OLD = "import json\n"
IMP_NEW = "import json\nimport os\n"


def main() -> int:
    src = MAIN.read_text(encoding="utf-8")
    for name, old, new, cnt in (("IMP", IMP_OLD, IMP_NEW, 1), ("HEALTH", OLD, NEW, 1)):
        n = src.count(old)
        if n != cnt:
            print(f"[FAIL] {name} 命中 {n} 次(期望 {cnt})")
            return 1
        src = src.replace(old, new, 1)
    MAIN.write_text(src, encoding="utf-8")
    print("[OK] /api/health 已暴露 flags")
    return 0


if __name__ == "__main__":
    sys.exit(main())
