"""LLM 调用层(OpenAI 兼容协议,默认 DashScope qwen-flash)"""
from __future__ import annotations

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
