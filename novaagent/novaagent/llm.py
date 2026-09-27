"""LLM 调用层(OpenAI 兼容协议,默认 DashScope qwen-flash)"""
from __future__ import annotations

import json
from typing import Any

import httpx

from . import config


async def chat(
    messages: list[dict],
    tools: list[dict] | None = None,
    max_tokens: int = 2048,
    temperature: float = 0.3,
    model: str = "",
    base_url: str = "",
    api_key: str = "",
) -> dict:
    """单轮调用,返回 message dict(含 content 或 tool_calls)。model/base_url/api_key 可覆盖全局配置。"""
    payload: dict[str, Any] = {
        "model": model or config.LLM_MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if tools:
        payload["tools"] = tools
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            f"{(base_url or config.LLM_BASE_URL).rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {api_key or config.LLM_API_KEY}"},
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]


async def chat_stream(
    messages: list[dict],
    tools: list[dict] | None = None,
    model: str = "",
    base_url: str = "",
    api_key: str = "",
    max_tokens: int = 2048,
    temperature: float = 0.3,
):
    """T8: 流式调用(OpenAI 兼容 stream=true)。异步生成器逐段 yield 事件:
      {"type": "delta", "content": str}                正文增量
      {"type": "tool_delta", "index": int, "id": str|None,
       "name": str|None, "args": str}                  工具调用碎片(调用方按 index 聚合)
      {"type": "finish", "reason": str}                结束原因
    """
    payload: dict[str, Any] = {
        "model": model or config.LLM_MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": True,
    }
    if tools:
        payload["tools"] = tools
    async with httpx.AsyncClient(timeout=180) as client:
        async with client.stream(
            "POST",
            f"{(base_url or config.LLM_BASE_URL).rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {api_key or config.LLM_API_KEY}"},
            json=payload,
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if not data:
                    continue
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue
                choices = chunk.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}
                if delta.get("content"):
                    yield {"type": "delta", "content": delta["content"]}
                for tc in delta.get("tool_calls") or []:
                    fn = tc.get("function") or {}
                    yield {
                        "type": "tool_delta",
                        "index": tc.get("index", 0),
                        "id": tc.get("id"),
                        "name": fn.get("name"),
                        "args": fn.get("arguments") or "",
                    }
                if choices[0].get("finish_reason"):
                    yield {"type": "finish", "reason": choices[0]["finish_reason"]}
