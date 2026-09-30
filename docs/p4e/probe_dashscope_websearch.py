#!/usr/bin/env python3
"""P4e 落码前的**协议复验**：DashScope 原生联网协议是否真回 search_info。

规格要求（docs/p4e/workbuddy-order.md §3 第 1 条）：
  "落码前先用一条最小请求复验 DashScope 原生协议
   POST /api/v1/services/aigc/text-generation/generation
   + search_options={forced_search, search_strategy:"turbo", enable_source:true,
                     enable_citation:true, citation_format:"[<number>]"}
   是否真回 output.search_info.search_results[{index,site_name,title,url}]
   —— **若与记录不符 → 硬停上报，不要按猜测实现**。"

本脚本做三件事：
  1. 发**一条**最小原生协议请求（联网开关=on），打印/落盘请求与响应骨架（脱敏 key）；
  2. 同一问句发**一条** OpenAI 兼容模式 + enable_search=true 的请求作对照，
     验证规格里说的"兼容模式不返回 search_info、只回 usage.plugins.search.count"；
  3. 把 search_results 的字段名与规格逐项对账，不符即 `pass=false`（硬停信号）。

⚠ 合规红线（P4 全期适用）：**出网请求只发「当前问题文本」这一个字符串**。
  本脚本的问句是**构造的公开知识问句**（"ISO 4217 三个字母码里 CNY 指的是什么货币"），
  **不是真实学工问句**；不发库内文档、不发会话历史、不发个人信息、不发 contacts.json。
  响应骨架落盘前**只保留 search_results 的字段名与前 3 条**，正文另存便于核对角标。
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

OUT = ROOT / "docs" / "p4e" / "evidence" / "dashscope_websearch_probe.json"
NATIVE_URL = "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation"
# 构造的公开知识问句(非学工/非个人信息)——出网只发这一个字符串
PROBE_Q = "ISO 4217 货币代码里 CNY 指的是哪种货币？"
EXPECT_FIELDS = {"index", "site_name", "title", "url"}


def skeleton(x: object, depth: int = 0) -> object:
    """结构骨架(键名 + 类型 + 列表长度),不落盘正文内容。"""
    if depth > 4:
        return "..."
    if isinstance(x, dict):
        return {k: skeleton(v, depth + 1) for k, v in x.items()}
    if isinstance(x, list):
        return [skeleton(x[0], depth + 1), f"...共{len(x)}条"] if x else []
    return type(x).__name__


def main() -> int:
    key = config.LLM_API_KEY
    if not key:
        print("[硬停] LLM_API_KEY 未配置，无法复验")
        return 2
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    report: dict = {"probe_question": PROBE_Q, "native_url": NATIVE_URL,
                    "note": "出网仅此一个字符串：构造的公开知识问句，不含任何校内/个人信息"}

    # ---- 1) 原生协议(联网) ----
    native_payload = {
        "model": config.LLM_MODEL,
        "input": {"messages": [{"role": "user", "content": PROBE_Q}]},
        "parameters": {
            "search_options": {
                "forced_search": True,
                "search_strategy": "turbo",
                "enable_source": True,
                "enable_citation": True,
                "citation_format": "[<number>]",
            },
            "incremental_output": False,
        },
    }
    with httpx.Client(timeout=120, trust_env=False) as c:
        r = c.post(NATIVE_URL, headers=headers, json=native_payload)
        report["native_status"] = r.status_code
        try:
            native = r.json()
        except Exception:  # noqa: BLE001
            report["native_body_text"] = r.text[:400]
            native = {}
    report["native_skeleton"] = skeleton(native)
    out = native.get("output") or {}
    si = out.get("search_info") or {}
    results = si.get("search_results") or []
    report["native_has_search_info"] = bool(si)
    report["native_n_results"] = len(results)
    report["native_result_fields"] = sorted(results[0].keys()) if results else []
    report["native_results_sample"] = [
        {k: v for k, v in row.items() if k in ("index", "site_name", "title", "url")} for row in results[:3]
    ]
    report["native_text_has_citation"] = any(
        f"[{i}]" in (out.get("text") or "") for i in range(1, (len(results) or 1) + 1))
    report["native_text_head"] = (out.get("text") or "")[:300]
    report["native_usage"] = native.get("usage")
    missing = EXPECT_FIELDS - set(report["native_result_fields"])
    report["native_missing_fields"] = sorted(missing)
    print(f"[原生协议] HTTP {report['native_status']} | search_info={report['native_has_search_info']}"
          f" | results={report['native_n_results']} | 字段={report['native_result_fields']}")
    print(f"[原生协议] 缺失字段 = {report['native_missing_fields'] or '无'}")
    print(f"[原生协议] 答案含 [n] 角标 = {report['native_text_has_citation']}")
    print(f"[原生协议] 答案片段: {report['native_text_head'][:160]}")

    # ---- 2) OpenAI 兼容模式 + enable_search(对照组,验证"拿不到 search_info") ----
    compat_payload = {
        "model": config.LLM_MODEL,
        "messages": [{"role": "user", "content": PROBE_Q}],
        "enable_search": True,
        "search_options": {"forced_search": True, "enable_source": True},
        "stream": False,
    }
    compat_url = f"{config.LLM_BASE_URL.rstrip('/')}/chat/completions"
    with httpx.Client(timeout=120, trust_env=False) as c:
        rc = c.post(compat_url, headers=headers, json=compat_payload)
        report["compat_status"] = rc.status_code
        try:
            compat = rc.json()
        except Exception:  # noqa: BLE001
            compat = {}
    report["compat_skeleton"] = skeleton(compat)
    report["compat_has_search_info"] = "search_info" in json.dumps(compat, ensure_ascii=False)
    report["compat_usage_plugins"] = ((compat.get("usage") or {}).get("plugins"))
    print(f"[兼容模式] HTTP {report['compat_status']} | search_info 出现="
          f"{report['compat_has_search_info']} | usage.plugins={report['compat_usage_plugins']}")

    report["pass"] = bool(report["native_has_search_info"]
                          and report["native_n_results"] > 0
                          and not missing
                          and report["native_status"] == 200)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[结论] pass = {report['pass']}")
    if not report["pass"]:
        print("[硬停] 与规格记录不符 —— 不要按猜测实现，先上报负责人（Qoder）")
    print("[report]", OUT)
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
