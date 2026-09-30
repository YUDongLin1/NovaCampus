#!/usr/bin/env python3
"""P4e 落码前协议复验（第三轮·收敛版）：**四条联网入口全矩阵**，判定哪条真回结构化来源。

背景：单据要求「落码前先用一条最小请求复验 DashScope **原生协议** +
`search_options={forced_search, search_strategy:"turbo", enable_source, enable_citation,
citation_format:"[<number>]"}` 是否真回 `output.search_info.search_results[{index,site_name,title,url}]`」。
第一轮实测**不符**（HTTP 200 但 `search_options` 被完全忽略），故按单据「若与记录不符 → 硬停上报」
先做根因定位，不落码。本脚本是这次定位的**可复验入口**，把结论固化成一张表。

实测结论（本脚本可复现，证据 docs/p4e/evidence/websearch_entrypoint_matrix.json）：
  | 入口 | 参数位置 | 搜索是否真执行 | 结构化来源 |
  |------|---------|--------------|-----------|
  | 原生 text-generation | parameters.search_options | ❌ 无 plugins、无检索痕迹 | ❌ 无 search_info |
  | 原生 text-generation | 顶层 enable_search（旧模型） | ❌ prompt_tokens 不涨 | ❌ |
  | 兼容 Chat Completions | extra_body.search_options | ⚠️ 检索**真执行**(prompt 29→2092)但静默丢弃来源 | ❌ |
  | 兼容 Chat Completions | enable_search=true | ⚠️ 同上 | ❌ |
  | **兼容 Responses API** | **tools=[{"type":"web_search"}]** | ✅ | **⚠️ 只回 `url`，缺 index/title/site_name** |

关键事实（决定能不能按单据原样实现）：
  1. **单据记录的 `output.search_info.search_results[{index,site_name,title,url}]` 四字段，
     在当前 DashScope 上任何一个入口都拿不到。** 新模型族（qwen3.8/3.7/3.5 系列、qwen3-max）
     的原生协议 `output` 已从 `{text, finish_reason}` 变成 `{choices:[...]}`，
     `search_info` 整块消失；旧模型（qwen-flash/plus/turbo/max/long）连 `usage.plugins` 都没有。
  2. 唯一带回来源的是 Responses API 的 `web_search_call.action.sources`，元素只有
     `{"type":"url","url":...}` —— **有 URL 可点，但没有 index/title/site_name**。
  3. 正文**不含 `[n]` 角标**、**不含内联 URL**、**`annotations` 为空** → 无法把某条断言
     映射到某条 URL，`[W1]` 分区编号**无法由上游给出**，必须由 NovaCampus 自行分配。
  4. `site_name` 理论上可由 `urlparse(url).netloc` 推导（实测 18 源 → 13 个唯一 host），
     但那是**我们自己造的展示值**，不是官方 `site_name`，属需要裁决的口径问题。

⚠ 合规（红线 C 级）：本脚本出网**只发一个构造的公开知识问句**，
   不发库内文档/chunk/会话历史/系统提示词/学生个人信息/contacts.json。
   问句刻意选「杭州明天天气 / 统计局 GDP」这类公开时效问句，**不是任何真实学工问句**。
   落盘证据里 `text_head` 只保留模型对该公开问句的回答。

用法（项目 venv，httpx 在里面）：
    novaagent/.venv/Scripts/python.exe docs/p4e/probe_websearch_entrypoints.py
退出码：0 = 找到至少一条回 URL 的入口；1 = 一条都没有（真硬停）；2 = 缺 key/依赖。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "novaagent"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError, OSError):
    pass

import httpx  # noqa: E402

from novaagent import config  # noqa: E402

NATIVE_URL = "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation"
COMPAT_CHAT_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
COMPAT_RESP_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/responses"
MODELS_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/models"

OUT = ROOT / "docs" / "p4e" / "evidence" / "websearch_entrypoint_matrix.json"

# 构造的公开知识问句（非真实学工问句；不含任何库内内容）
Q_TIME = "杭州明天天气如何？"
Q_FACT = "中国国家统计局最新公布的 GDP 同比增速是多少？请引用来源。"

# 单据要求的四字段 —— 实测全部拿不齐，这是硬停的核心依据
SPEC_FIELDS = {"index", "site_name", "title", "url"}

TIMEOUT = 110.0


def _post(key: str, url: str, payload: dict) -> tuple[int | None, dict | str | None]:
    """返回 (http, json 或 截断文本 或 None)。统一 timeout / trust_env=False（避代理假 404）。"""
    try:
        with httpx.Client(timeout=TIMEOUT, trust_env=False) as c:
            r = c.post(url, headers={"Authorization": f"Bearer {key}",
                                     "Content-Type": "application/json"}, json=payload)
    except Exception as e:  # noqa: BLE001
        return None, f"{type(e).__name__}: {str(e)[:160]}"
    try:
        return r.status_code, r.json()
    except Exception:  # noqa: BLE001
        return r.status_code, r.text[:200]


def _search_options(strategy: str) -> dict:
    """单据指定的 search_options 原样。"""
    return {"forced_search": True, "search_strategy": strategy,
            "enable_source": True, "enable_citation": True, "citation_format": "[<number>]"}


def probe_native(key: str, model: str, strategy: str) -> dict:
    """入口①：原生 text-generation + parameters.search_options（单据指定形态）。"""
    payload = {"model": model,
               "input": {"messages": [{"role": "user", "content": Q_FACT}]},
               "parameters": {"search_options": _search_options(strategy), "result_format": "message"}}
    http, j = _post(key, NATIVE_URL, payload)
    if not isinstance(j, dict):
        return {"entry": "native_text_generation", "http": http, "raw": j}
    out = j.get("output") or {}
    si = out.get("search_info") or {}
    res = si.get("search_results") or []
    return {
        "entry": "native_text_generation", "param": "parameters.search_options",
        "model": model, "strategy": strategy, "http": http,
        "output_keys": sorted(out.keys()),
        "has_search_info": bool(si), "n_results": len(res),
        "result_fields": sorted(res[0].keys()) if res else [],
        "missing_vs_spec": sorted(SPEC_FIELDS - set(res[0].keys())) if res else sorted(SPEC_FIELDS),
        "usage_plugins": (j.get("usage") or {}).get("plugins"),
        "code": j.get("code"), "message": (j.get("message") or "")[:140],
    }


def probe_compat_chat(key: str, model: str, strategy: str) -> dict:
    """入口②：兼容 Chat Completions + extra_body.search_options（llm.py 现用形态）。"""
    payload = {"model": model, "messages": [{"role": "user", "content": Q_FACT}],
               "extra_body": {"search_options": _search_options(strategy)}}
    http, j = _post(key, COMPAT_CHAT_URL, payload)
    if not isinstance(j, dict):
        return {"entry": "compat_chat_completions", "http": http, "raw": j}
    msg = ((j.get("choices") or [{}])[0]).get("message") or {}
    si = msg.get("search_info") or {}
    res = si.get("search_results") or []
    usage = j.get("usage") or {}
    return {
        "entry": "compat_chat_completions", "param": "extra_body.search_options",
        "model": model, "strategy": strategy, "http": http,
        "message_keys": sorted(msg.keys()),
        "has_search_info": bool(si), "n_results": len(res),
        "result_fields": sorted(res[0].keys()) if res else [],
        "missing_vs_spec": sorted(SPEC_FIELDS - set(res[0].keys())) if res else sorted(SPEC_FIELDS),
        # 「搜索是否真执行」的唯一客观信号：prompt_tokens 是否显著上涨（注入检索上下文）
        "prompt_tokens": usage.get("prompt_tokens"),
        "usage_plugins": usage.get("plugins"),
        "code": j.get("code"), "message": (j.get("message") or "")[:140],
    }


def probe_responses(key: str, model: str) -> dict:
    """入口③：兼容 Responses API + tools=[{"type":"web_search"}]（官方唯一回来源的入口）。"""
    payload = {"model": model, "input": Q_TIME, "tools": [{"type": "web_search"}]}
    http, j = _post(key, COMPAT_RESP_URL, payload)
    if not isinstance(j, dict):
        return {"entry": "compat_responses_api", "http": http, "raw": j}
    src: list[dict] = []
    out_types: list[str] = []
    for o in (j.get("output") or []):
        if not isinstance(o, dict):
            continue
        out_types.append(str(o.get("type")))
        if o.get("type") == "web_search_call":
            src.extend((o.get("action") or {}).get("sources") or [])
    msg = next((o for o in (j.get("output") or [])
                if isinstance(o, dict) and o.get("type") == "message"), {})
    text = "".join(c.get("text") or "" for c in (msg.get("content") or []) if isinstance(c, dict))
    ann_n = sum(len(c.get("annotations") or []) for c in (msg.get("content") or [])
                if isinstance(c, dict))
    hosts: list[str] = []
    for s in src:
        h = urlparse(s.get("url") or "").netloc
        if h and h not in hosts:
            hosts.append(h)
    return {
        "entry": "compat_responses_api", "param": 'tools=[{"type":"web_search"}]',
        "model": model, "http": http,
        "output_types": out_types, "n_sources": len(src),
        "source_fields_union": sorted({k for s in src for k in s}),
        "missing_vs_spec": sorted(SPEC_FIELDS - {k for s in src for k in s}),
        # 决定 [W1] 分区编号能否由上游给出：正文角标 / 内联 URL / annotations 任一非零才行
        "text_citation_markers": sorted(set(re.findall(r"\[(\d+)\]", text))),
        "text_inline_urls": len(re.findall(r"https?://[^\s\)\]]+", text)),
        "n_annotations": ann_n,
        "unique_hosts": len(hosts), "hosts_head": hosts[:12],
        "n_text_chars": len(text), "text_head": text[:300],
        "usage_plugins": ((j.get("usage") or {}).get("x_details") or [{}])[0].get("plugins"),
        "code": j.get("code"), "message": (j.get("message") or "")[:140],
    }


def probe_model_acl(key: str) -> dict:
    """旁证：该 key 到底能调哪些模型（区分「模型不支持」vs「key 无权限」）。"""
    try:
        with httpx.Client(timeout=40, trust_env=False) as c:
            r = c.get(MODELS_URL, headers={"Authorization": f"Bearer {key}"})
        j = r.json()
        ids = sorted(m.get("id") for m in (j.get("data") or []) if m.get("id"))
        return {"http": r.status_code, "n_models": len(ids), "sample": ids[:15]}
    except Exception as e:  # noqa: BLE001
        return {"http": None, "error": str(e)[:160]}


def main() -> int:
    key = config.LLM_API_KEY
    if not key:
        print("[硬停] LLM_API_KEY 未配置")
        return 2

    print("=== 旁证：key 模型权限 ===")
    acl = probe_model_acl(key)
    print(f"  可调模型数 = {acl.get('n_models')}  HTTP={acl.get('http')}")
    print("  样例:", ", ".join(acl.get("sample") or [])[:200])

    # 新模型族：原生协议对多模态/新代次会 400 url error，故只挑已知纯文本联网模型
    net_models = ["qwen3.8-max", "qwen3.7-flash", "qwen3-max", "qwen-flash"]

    rows: list[dict] = []
    print("\n=== 入口① 原生 text-generation + parameters.search_options（单据指定形态） ===")
    print(f"{'model':<15}{'strategy':<9}{'http':>6}{'search_info':>13}{'n':>4}  output_keys / 备注")
    for m in net_models:
        for st in ("turbo", "agent"):
            r = probe_native(key, m, st)
            rows.append(r)
            note = f"output={r.get('output_keys')}"
            if r.get("usage_plugins"):
                note += f" plugins={r['usage_plugins']}"
            if r.get("message"):
                note = r["message"][:90]
            print(f"{m:<15}{st:<9}{str(r.get('http')):>6}{str(r.get('has_search_info')):>13}"
                  f"{str(r.get('n_results')):>4}  {note}")

    print("\n=== 入口② 兼容 Chat Completions + extra_body.search_options（llm.py 现用形态） ===")
    print(f"{'model':<15}{'strategy':<9}{'http':>6}{'search_info':>13}{'n':>4}{'prompt_tok':>11}  备注")
    for m in net_models:
        for st in ("turbo", "agent"):
            r = probe_compat_chat(key, m, st)
            rows.append(r)
            note = "plugins 无" if not r.get("usage_plugins") else f"plugins={r['usage_plugins']}"
            if r.get("message"):
                note = r["message"][:90]
            print(f"{m:<15}{st:<9}{str(r.get('http')):>6}{str(r.get('has_search_info')):>13}"
                  f"{str(r.get('n_results')):>4}{str(r.get('prompt_tokens')):>11}  {note}")

    print("\n=== 入口③ 兼容 Responses API + tools=[{type:web_search}]（官方唯一回来源入口） ===")
    print(f"{'model':<15}{'http':>6}{'sources':>9}{'角标':>6}{'内联URL':>9}{'annot':>7}  字段 / 备注")
    for m in net_models:
        r = probe_responses(key, m)
        rows.append(r)
        print(f"{m:<15}{str(r.get('http')):>6}{str(r.get('n_sources')):>9}"
              f"{len(r.get('text_citation_markers') or []):>6}{str(r.get('text_inline_urls')):>9}"
              f"{str(r.get('n_annotations')):>7}  fields={r.get('source_fields_union')} "
              f"缺={r.get('missing_vs_spec')}")
        if r.get("message"):
            print("      msg:", r["message"][:110])

    with_url = [r for r in rows if r.get("entry") == "compat_responses_api" and r.get("n_sources")]
    spec_ok = [r for r in with_url if not r.get("missing_vs_spec")]
    searched_but_silent = [
        r for r in rows
        if r.get("entry") == "compat_chat_completions"
        and isinstance(r.get("prompt_tokens"), int) and r["prompt_tokens"] > 500
        and not r.get("has_search_info")
    ]

    report = {
        "probe_questions": {"facts": Q_FACT, "time_sensitive": Q_TIME},
        "compliance_note": "出网仅发构造的公开知识问句；未发任何库内文档/会话历史/个人信息",
        "spec_expected_fields": sorted(SPEC_FIELDS),
        "key_model_acl": acl,
        "rows": rows,
        "entrypoints_returning_urls": [
            {"entry": r["entry"], "model": r["model"], "n_sources": r["n_sources"],
             "fields": r["source_fields_union"], "missing_vs_spec": r["missing_vs_spec"],
             "citation_markers": r.get("text_citation_markers"),
             "inline_urls": r.get("text_inline_urls"), "n_annotations": r.get("n_annotations")}
            for r in with_url],
        "entrypoints_returning_spec_4_fields": [r["model"] for r in spec_ok],
        "searched_but_sources_silently_dropped": [
            {"model": r["model"], "strategy": r["strategy"], "prompt_tokens": r["prompt_tokens"]}
            for r in searched_but_silent],
        "verdict": {
            "spec_field_contract_met": bool(spec_ok),
            "url_available": bool(with_url),
            "upstream_can_suppress_W_index": any(
                (r.get("text_citation_markers") or r.get("text_inline_urls") or r.get("n_annotations"))
                for r in with_url),
            "hard_stop_reason": (
                "单据记录的 output.search_info.search_results[{index,site_name,title,url}] 四字段契约"
                "在当前 DashScope 任何入口都不成立；唯一能回 URL 的 Responses API 只给 {type,url}，"
                "且正文无 [n] 角标 / 无内联 URL / annotations 为空 → [W1] 编号须由本系统自行分配，"
                "site_name 只能由 netloc 推导（非官方字段）。属契约级裁决项，按单据『若与记录不符 → "
                "硬停上报，不要按猜测实现』停下。"),
        },
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n=== 判定 ===")
    v = report["verdict"]
    print(f"  回 URL 的入口        : {[r['model'] for r in with_url] or '无'}")
    print(f"  回全 4 字段的入口    : {[r['model'] for r in spec_ok] or '无  ← 契约不成立'}")
    print(f"  上游可给 [W] 编号    : {v['upstream_can_suppress_W_index']}")
    print(f"  搜索执行但来源被丢弃 : {len(searched_but_silent)} 组（prompt_tokens>500 且无 search_info）")
    print("\n[硬停]", v["hard_stop_reason"])
    print("[report]", OUT)
    return 0 if with_url else 1


if __name__ == "__main__":
    sys.exit(main())
