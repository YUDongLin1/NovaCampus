"""周报 MCP 客户端:长连接封装(连接我们部署的 weekly-mcp 服务)"""
from __future__ import annotations

import json
import logging

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

logger = logging.getLogger(__name__)


class WeeklyMCP:
    def __init__(self, url: str) -> None:
        self._url = url
        self._http_cm = None
        self._session_cm = None
        self.session: ClientSession | None = None

    async def start(self) -> None:
        # 本机系统代理会拦截 localhost 并返回 502,显式绕过
        import os

        no_proxy = os.environ.setdefault("NO_PROXY", "127.0.0.1,localhost")
        os.environ.setdefault("no_proxy", no_proxy)
        self._http_cm = streamable_http_client(self._url)
        read, write = await self._http_cm.__aenter__()
        self._session_cm = ClientSession(read, write)
        self.session = await self._session_cm.__aenter__()
        await self.session.initialize()
        tools = {t.name for t in (await self.session.list_tools()).tools}
        logger.info("weekly MCP connected at %s, tools=%s", self._url, sorted(tools))

    async def stop(self) -> None:
        for cm in (self._session_cm, self._http_cm):
            if cm:
                await cm.__aexit__(None, None, None)
        self.session = None

    async def call(self, name: str, args: dict) -> dict:
        if not self.session:
            return {"ok": False, "error": "weekly MCP 未连接"}
        try:
            res = await self.session.call_tool(name, args)
            if res.is_error:
                return {"ok": False, "error": res.content[0].text}
            return json.loads(res.content[0].text)
        except Exception as e:  # 工具失败不阻断对话
            logger.exception("weekly tool %s failed", name)
            return {"ok": False, "error": str(e)}
