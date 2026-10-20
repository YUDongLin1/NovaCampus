#!/usr/bin/env python3
"""P4e 协议复验第二轮：定位「原生协议回 200 但无 search_info」的**真实原因**。

第一轮结果（evidence/dashscope_websearch_probe.json）：
  原生协议 HTTP 200，`output` 只有 `{finish_reason, text}`，**连 `usage.plugins` 都没有**
  → `search_options` 被**完全忽略**，不是"回不回 search_info"的问题。
两种可能，必须实测区分（不许猜）：
  H1 模型不支持联网（`qwen-flash` 是轻量本地推理型号，DashScope 联网搜索只对
     qwen-plus / qwen-turbo / qwen-max / qwen3-* 等联网版开放）→ 换模型即可；
  H2 参数位置/结构不对（`search_options` 应在 `parameters` 内——本轮已放对）
     → 换模型也白搭。

做法：固定问句、只换模型名，扫一遍候选；同时对照"兼容模式 + enable_search"。
每个模型记录 {http, has_search_info, n_results, fields, usage.plugins, text_has_citation}。

⚠ 合规：出网仅发一个**构造的公开知识问句**，不发库内文档/会话历史/个人信息。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "novaagent"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError, OSError):
    pass

import httpx  # noqa: E402

from novaagent import config  # noqa: E402

OUT = ROOT / "docs" / "p4e" / "evidence" / "websearch_model_matrix.json"
NATIVE_URL = "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation"
PROBE_Q = "ISO 4217 货币代码里 CNY 指的是哪种货币？"   # 构造的公开知识问句
EXPECT_FIELDS = {"index", "site_name", "title", "url"}
MODELS = ["qwen-flash", "qwen-plus", "qwen-turbo", "qwen-max", "qwen3-plus", "qwen-long"]


def call_native(key: str, model: str) -> dict:
    payload = {
        "model": model,
        "input": {"messages": [{"role": "user", "content": PROBE_Q}]},
        "parameters": {"search_options": {
            "forced_search": True, "search_strategy": "turbo",
            "enable_source": True, "enable_citation": True, "citation_format": "[<number>]",
        }},
    }
    try:
        with httpx.Client(timeout=120, trust_env=False) as c:
            r = c.post(NATIVE_URL, headers={"Authorization": f"Bearer {key}",
                                            "Content-Type": "application/json"}, json=payload)
        try:
            j = r.json()
        except Exception:  # noqa: BLE001
            return {"model": model, "http": r.status_code, "error": r.text[:200]}
    except Exception as e:  # noqa: BLE001
        return {"model": model, "http": None, "error": str(e)[:200]}
    out = (j.get("output") or {})
    si = (out.get("search_info") or {})
    res = si.get("search_results") or []
    txt = out.get("text") or ""
    return {
        "model": model, "http": r.status_code,
        "has_search_info": bool(si), "n_results": len(res),
        "fields": sorted(res[0].keys()) if res else [],
        "missing_fields": sorted(EXPECT_FIELDS - set(res[0].keys())) if res else sorted(EXPECT_FIELDS),
        "usage_plugins": ((j.get("usage") or {}).get("plugins")),
        "text_has_citation": any(f"[{i}]" in txt for i in range(1, (len(res) or 1) + 1)),
        "text_head": txt[:200],
        "code": j.get("code"), "message": j.get("message"),
    }


def main() -> int:
    key = config.LLM_API_KEY
    if not key:
        print("[硬停] LLM_API_KEY 未配置")
        return 2
    rows = []
    print(f"{'model':<14}{'http':>6}{'search_info':>13}{'n':>4}{'角标':>6}  fields / 备注")
    for m in MODELS:
        row = call_native(key, m)
        rows.append(row)
        print(f"{m:<14}{str(row.get('http')):>6}{str(row.get('has_search_info')):>13}"
              f"{str(row.get('n_results')):>4}{str(row.get('text_has_citation')):>6}"
              f"  {row.get('fields') or row.get('error') or row.get('message') or ''}"
              f"{'  usage.plugins=' + str(row.get('usage_plugins')) if row.get('usage_plugins') else ''}")
    ok = [r for r in rows if r.get("has_search_info") and r.get("n_results")]
    rep = {"probe_question": PROBE_Q, "models_tried": MODELS, "rows": rows,
           "working_models": [r["model"] for r in ok],
           "conclusion": ("H1 模型不支持（换模型即可）" if ok else
                          "H1/H2 均未排除：所有候选模型都无 search_info") +
                         f"；可用模型={[r['model'] for r in ok]}"}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n[结论]", rep["conclusion"])
    print("[report]", OUT)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
