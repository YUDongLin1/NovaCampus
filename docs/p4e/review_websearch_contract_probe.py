#!/usr/bin/env python3
"""Qoder 独立复验 P4e 合同前提（只发 2 条请求，构造的公开问句，红线安全）。

要裁决的是实现方交的硬停报告：它说单据里写的 DashScope 原生协议契约**不成立**、
唯一能带回来源的是 responses + tools=[{type:web_search}]，且只给 `{type,url}`。
这是 P4e 主体设计的地基，不能凭回执裁决 → 我自己发请求看响应结构。

红线自查：问句是构造的公开知识题，不含库内内容、会话历史、学生信息。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(r"E:/AILearn/NovaCampus/novaagent")))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError, OSError):
    pass

import httpx  # noqa: E402

from novaagent import config  # noqa: E402

Q = "ISO 4217 货币代码里 CNY 指的是哪种货币？请给出来源。"
KEY = config.LLM_API_KEY
BASE = config.LLM_BASE_URL.rstrip("/")          # .../compatible-mode/v1
MODEL = config.LLM_MODEL
NATIVE = "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation"
print("model =", MODEL, "| base =", BASE, "| key len =", len(KEY or ""), "(不打印 key)")

HDR = {"Authorization": "Bearer " + KEY, "Content-Type": "application/json"}
out = {"question": Q, "model": MODEL}

# ---------- A. 单据里写的原生协议 + search_options ----------
payload_a = {
    "model": MODEL,
    "input": {"messages": [{"role": "user", "content": Q}]},
    "parameters": {
        "result_format": "message",
        "enable_source": True,
        "enable_citation": True,
        "citation_format": "[<number>]",
        "search_options": {"forced_search": True, "search_strategy": "turbo",
                           "enable_source": True, "enable_citation": True,
                           "citation_format": "[<number>]"},
    },
}
try:
    r = httpx.post(NATIVE, headers=HDR, json=payload_a, timeout=60)
    j = r.json() if r.status_code == 200 else {"error": r.text[:300]}
    output = (j or {}).get("output") or {}
    usage = (j or {}).get("usage") or {}
    info = output.get("search_info") if isinstance(output, dict) else None
    srcs = (info or {}).get("search_results") if info else None
    out["A_native"] = {
        "http": r.status_code,
        "output_keys": sorted(output.keys()) if isinstance(output, dict) else None,
        "has_search_info": bool(info),
        "n_search_results": (len(srcs) if srcs else 0),
        "search_result_fields": sorted(srcs[0].keys()) if srcs else [],
        "usage_keys": sorted(usage.keys()),
        "usage_plugins": usage.get("plugins"),
        "input_tokens": usage.get("input_tokens") or usage.get("prompt_tokens"),
    }
except Exception as e:
    out["A_native"] = {"exception": "%s: %s" % (type(e).__name__, str(e)[:200])}

# ---------- B. responses + tools=[web_search] ----------
for url in (BASE + "/responses", "https://dashscope.aliyuncs.com/compatible-mode/v1/responses"):
    payload_b = {"model": MODEL, "input": Q, "tools": [{"type": "web_search"}]}
    try:
        r = httpx.post(url, headers=HDR, json=payload_b, timeout=90)
        if r.status_code != 200:
            out["B_responses"] = {"url": url, "http": r.status_code, "body": r.text[:200]}
            continue
        j = r.json()
        items = j.get("output") or []
        calls = [it for it in items if isinstance(it, dict) and it.get("type") == "web_search_call"]
        sfields, nsources, hosts = [], 0, []
        for c in calls:
            s = ((c.get("action") or {}).get("sources") or [])
            nsources += len(s)
            if s:
                sfields = sorted(s[0].keys())
                hosts = [(__import__("urllib.parse", fromlist=["x"]).urlparse(
                    (d.get("url") or "")).netloc) for d in s][:6]
        texts = "".join([(it.get("content") or "") if isinstance(it.get("content"), str)
                         else json.dumps(it.get("content"), ensure_ascii=False)
                         for it in items if isinstance(it, dict) and it.get("type") == "message"])
        out["B_responses"] = {
            "url": url, "http": r.status_code,
            "item_types": [it.get("type") for it in items if isinstance(it, dict)],
            "n_web_search_call": len(calls),
            "n_sources": nsources,
            "source_fields": sfields,
            "sample_hosts": hosts,
            "text_len": len(texts),
            "text_brackets_n": __import__("re").findall(r"\[\d+\]", texts)[:8],
            "annotations": sum(len(it.get("content") or []) for it in items
                               if isinstance(it, dict) and isinstance(it.get("content"), list)),
            "usage": j.get("usage"),
        }
        break
    except Exception as e:
        out["B_responses"] = {"exception": "%s: %s" % (type(e).__name__, str(e)[:200])}

print(json.dumps(out, ensure_ascii=False, indent=2)[:2600])
