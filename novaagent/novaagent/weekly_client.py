"""周报 MCP 客户端:连接我们部署的 weekly-mcp 服务(Streamable HTTP 无状态端点)

连接失败不抛错:主服务照常启动,周报功能降级为返回「未连接」,
且每次调用前会再试一次懒重连 —— 周报服务后启动也能自愈,不必重启主服务。
无状态端点下每次调用都是独立请求,此处持有的 session 只是 SDK 的请求上下文,
不代表一条长连接;降级与懒重连语义与之前完全一致。
"""
from __future__ import annotations

import asyncio
import json
import logging

from mcp import ClientSession
from mcp.client._probe import negotiate_auto
from mcp.client.streamable_http import streamable_http_client

logger = logging.getLogger(__name__)


class WeeklyMCP:
    def __init__(self, url: str) -> None:
        self._url = url
        self._http_cm = None
        self._session_cm = None
        self.session: ClientSession | None = None
        self._start_lock = asyncio.Lock()

    async def start(self) -> bool:
        """尝试连接;成功返回 True。失败只记警告并清理半开连接,不向上抛 —
        周报是增强功能,不该因为它没起就把整个主服务拖垮。"""
        if self.session is not None:
            return True
        async with self._start_lock:
            if self.session is not None:
                return True
            # 本机系统代理会拦截 localhost 并返回 502,显式绕过
            import os

            no_proxy = os.environ.setdefault("NO_PROXY", "127.0.0.1,localhost")
            os.environ.setdefault("no_proxy", no_proxy)
            try:
                self._http_cm = streamable_http_client(self._url)
                read, write = await self._http_cm.__aenter__()
                self._session_cm = ClientSession(read, write)
                self.session = await self._session_cm.__aenter__()
                # 2026-07-28 协议已取消 initialize 握手:SDK 的时代协商先探
                # server/discover,现代服务器走无状态流程;遇旧服务器自动回落
                # initialize,不会把旧服务端也一刀切断。
                # 注:mcp 2.2.0 未从 mcp.client 公开该函数,此处直接引用 SDK
                # 内部协商实现;升级 SDK 大版本时需复核该导入路径。
                await negotiate_auto(self.session)
                tools = {t.name for t in (await self.session.list_tools()).tools}
            except (asyncio.CancelledError, Exception):
                # 注意:SDK 传输失败时可能以 CancelledError 形式抛到调用方
                # (传输内部任务组取消了等待响应的协程),并非当前任务真的被取消;
                # 周报是增强功能,连接失败一律按降级处理,不向上抛,否则一次
                # 周报服务宕机就会拖垮主服务启动。
                logger.warning(
                    "weekly MCP 连接失败(%s):周报功能暂不可用,其余功能不受影响;"
                    "启动周报服务后会自动重连,无需重启主服务",
                    self._url, exc_info=True)
                await self.stop()
                return False
            logger.info("weekly MCP connected at %s, tools=%s", self._url, sorted(tools))
            return True

    async def stop(self) -> None:
        for cm in (self._session_cm, self._http_cm):
            if cm:
                try:
                    await cm.__aexit__(None, None, None)
                except (asyncio.CancelledError, Exception):
                    # 半开/已断的连接关不干净也无妨;SDK 清理抖动同 start 一样处理
                    pass
        self._session_cm = None
        self._http_cm = None
        self.session = None

    async def call(self, name: str, args: dict) -> dict:
        if not self.session:
            await self.start()  # 懒重连:周报服务后启动时自愈
        if not self.session:
            return {"ok": False, "error": "weekly MCP 未连接"}
        try:
            res = await self.session.call_tool(name, args)
            if res.is_error:
                return {"ok": False, "error": res.content[0].text}
            return json.loads(res.content[0].text)
        except (asyncio.CancelledError, Exception) as e:
            # 工具失败不阻断对话;传输失败同样可能以 CancelledError 形式出现,同 start 一样处理。
            # 另外:连接层一旦抛错,当前 session 已不可再用(服务端重启后旧会话
            # 也不会恢复),这里直接 reset,下一次调用走懒重连重新协商;
            # 否则一次断线会让后续所有调用都跟着失败。
            logger.exception("weekly tool %s failed", name)
            await self.stop()
            return {"ok": False, "error": str(e)}
