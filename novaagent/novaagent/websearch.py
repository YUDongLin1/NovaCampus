"""P4e M7:联网检索客户端(DashScope **Responses API** + `tools=[{"type":"web_search"}]`)。

## 为什么不是单据原本写的原生协议

单据(M7 / 原开单指令)假设用 DashScope 原生 `text-generation` + `search_options`
能拿回 `output.search_info.search_results[{index, site_name, title, url}]`。
**该契约在当前 DashScope 上不成立**,四入口全矩阵实测见
`docs/p4e/evidence/WEBSEARCH_PROTOCOL_HARDSTOP.md` 与 `websearch_entrypoint_matrix.json`:

| 入口 | 结果 |
|------|------|
| 原生 text-generation + `search_options` | 参数被忽略,无 `search_info` |
| 兼容 chat/completions + `enable_search` | 检索**真执行**(prompt_tokens 29→2092)但来源被**静默丢弃** |
| **兼容 Responses API + `tools=[web_search]`** | ✅ 回来源,但每条**只有 `{type, url}`** |

唯一可用入口的**硬约束**(决定了本模块能承诺什么):
  * 无 `index`、无 `title`、无 `site_name`;
  * 正文**零 `[n]` 角标、零内联 URL、`annotations` 为空** → **不存在「哪句出自哪条 URL」的映射**。

因此:
  * `site_name` 由 `urlparse(url).netloc` **推导**,并显式打 `site_name_derived=True`
    让 UI/评测能标注「站点名由 URL 推导」;
  * `index` 由本系统按 `action.sources` **原序**分配,**仅作列表编号**;
  * **不得**把 `[W1..Wk]` 绑定到具体句子(那是用假精确换好看,面试/审计都说不清),
    改为**整段级标注**(见 `agent.WEB_DECLARE`)。

## 合规红线(C 级)

出网请求体**只有三个字段**:`model` / `input`(= 当前问题文本) / `tools`。
**不发**库内 chunk、会话历史、系统提示词、改写串里的语料片段、学生个人信息、
`contacts.json`。日志只记耗时/条数/错误类型,**不记问题文本以外的任何内容**。
"""
from __future__ import annotations

import logging
import time
from typing import Any
from urllib.parse import urlparse

import httpx

from . import config

logger = logging.getLogger("novaagent.websearch")


def responses_url(base_url: str = "") -> str:
    """兼容模式 base(形如 `.../compatible-mode/v1`)→ Responses 端点。

    非 DashScope 形态的自定义 base_url 也能拼出来,但大概率 404 → 走 `search()` 的
    异常分支降级(坑 46:降级必须可见,不静默)。
    """
    return (base_url or config.LLM_BASE_URL).rstrip("/") + "/responses"


def derive_site_name(url: str) -> str:
    """站点名由 URL 推导(上游不提供 `site_name`)——UI 必须标注「由 URL 推导」。"""
    return urlparse(url or "").netloc


def build_web_sources(urls: list[str]) -> list[dict]:
    """把上游 URL 列表整理成前端/评测消费的「联网来源分区」条目。

    `ref` 用 `W1..Wk` 与本地 `[1..n]` **分区不混编号**;`index` 仅作列表编号。
    """
    out: list[dict] = []
    seen: set[str] = set()
    for u in urls or []:
        u = (u or "").strip()
        if not u or u in seen:
            continue
        seen.add(u)
        out.append({
            "index": len(out) + 1,
            "ref": f"W{len(out) + 1}",
            "url": u,
            "site_name": derive_site_name(u),
            # 明确标注:这不是上游给的官方 site_name,是本地由 URL 推出来的展示值
            "site_name_derived": True,
            "note": "站点名由 URL 推导（上游只返回 {type,url}）",
        })
    return out


async def search(question: str, model: str = "", base_url: str = "", api_key: str = "",
                 timeout_s: float | None = None) -> dict[str, Any]:
    """一次联网检索。返回 {called, ms, n_sources, error, urls, text}。

    ⚠ 任何失败都**不抛**给调用方,而是把 `error` 写进返回(调用方据此降级并提示用户)——
       但**必须**记录日志(坑 46:静默兜底等于把 bug 藏起来)。
    ⚠ 合规:payload 只有 model / input / tools 三个键,`input` 恒为**当前问题文本**。
    """
    t0 = time.time()
    out: dict[str, Any] = {"called": True, "ms": 0, "n_sources": 0, "error": "",
                           "urls": [], "text": ""}
    payload = {
        "model": model or config.LLM_MODEL,
        "input": question or "",          # ← 出网唯一的内容字段:当前问题文本
        "tools": [{"type": "web_search"}],
        # ⚠ **必须**显式强制,否则模型常常"不检索直接作答"(实测,qwen-flas):
        #   「ISO 4217 人民币代码」baseline → `web_search_call` 不出现、src=0;
        #   加 tool_choice 后 → src=10。而时间/时效类问句(杭州天气)不加也会检索(src=9)。
        #   即:静态知识题要靠 tool_choice 才能保证"用户开了联网就真的检索了"。
        #   单据与 WEBSEARCH_PROTOCOL_HARDSTOP 都**没记录这一条**,是本轮实测新增的协议事实。
        #   另测无效(同为 src=0):forced_search 顶层/写在 tool 里/search_options —— 只有 tool_choice 有效。
        "tool_choice": {"type": "web_search"},
    }
    try:
        async with httpx.AsyncClient(timeout=timeout_s or config.WEB_SEARCH_TIMEOUT_S) as c:
            resp = await c.post(
                responses_url(base_url),
                headers={"Authorization": f"Bearer {api_key or config.LLM_API_KEY}",
                         "Content-Type": "application/json"},
                json=payload,
            )
        out["http"] = resp.status_code
        resp.raise_for_status()
        j = resp.json()
    except Exception as e:  # noqa: BLE001
        # httpx.ReadTimeout 的 str(e) 是空串 → 只记类型名会让人看不出是超时还是别的
        out["error"] = f"{type(e).__name__}" + ((": " + str(e)[:120]) if str(e).strip() else "")
        out["ms"] = round((time.time() - t0) * 1000)
        logger.warning("联网检索失败(降级为仅本地): %s", out["error"])
        return out

    urls: list[str] = []
    text = ""
    for item in (j.get("output") or []):
        if not isinstance(item, dict):
            continue
        if item.get("type") == "web_search_call":
            for s in ((item.get("action") or {}).get("sources") or []):
                if isinstance(s, dict) and s.get("url"):
                    urls.append(str(s["url"]))
        elif item.get("type") == "message":
            for blk in (item.get("content") or []):
                if isinstance(blk, dict) and blk.get("text"):
                    text += str(blk["text"])
    # 顺序去重 + 截断(上游重复率实测 0~5.6%)
    dedup: list[str] = []
    seen: set[str] = set()
    for u in urls:
        if u not in seen:
            seen.add(u)
            dedup.append(u)
    out["urls"] = dedup[: max(1, config.WEB_SEARCH_MAX_SOURCES)]
    out["text"] = text
    out["n_sources"] = len(out["urls"])
    out["ms"] = round((time.time() - t0) * 1000)
    if not out["urls"]:
        out["error"] = "no_sources"
        logger.warning("联网检索返回 0 条来源(降级为仅本地)")
    return out
