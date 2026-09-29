"""P3a sims 共用层:Prometheus 指标埋点 + 有界连接池模拟 + 故障注入器

两个模拟校园系统(jiaowu 教务 / ykt 一卡通)共用:
- MetricsMiddleware:按路由模板记录 http_requests_total{method,path,status} 与
  http_request_duration_seconds(path) 直方图;
- SimPool:asyncio 有界连接池模拟——等待超时抛 PoolTimeout(由业务层转 503),
  暴露 app_db_pool_size / app_db_pool_in_use / app_db_pool_waiting /
  app_db_pool_wait_seconds(Histogram,含 _sum/_count);
- FaultManager:pool_exhaust(占满全部连接至到期自动归还)/ cpu_spike
  (进程内多线程 busy-loop,hashlib 大缓冲释放 GIL 可吃满多核),到期自动恢复;
  fault_active{type}=1 期间为注入活跃窗口;
- process_cpu_percent:后台线程每 2s 用 psutil 轮询写入 Gauge。
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import threading
import time
from contextlib import asynccontextmanager
from typing import Any

import psutil
from fastapi import FastAPI, HTTPException, Request, Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger("sims")

SERVICE = os.environ.get("SIM_SERVICE", "sims")

HTTP_REQUESTS = Counter(
    "http_requests_total", "HTTP 请求总数", ["method", "path", "status"]
)
HTTP_DURATION = Histogram(
    "http_request_duration_seconds", "HTTP 请求耗时(秒)", ["path"]
)
PROCESS_CPU = Gauge("process_cpu_percent", "进程 CPU 使用率(psutil 轮询,多核可 >100)")
FAULT_ACTIVE = Gauge("fault_active", "故障注入活跃中(1=注入窗口)", ["type"])


class PoolTimeout(Exception):
    """连接池等待超时(业务层转 503)。"""


class SimPool:
    """有界异步连接池模拟:固定 size,获取超时抛 PoolTimeout,全量指标埋点。"""

    def __init__(self, size: int, wait_timeout: float) -> None:
        self.size = size
        self.wait_timeout = wait_timeout
        self._free: asyncio.Queue[int] = asyncio.Queue()
        self._in_use = 0
        self._waiting = 0
        self.g_size = Gauge("app_db_pool_size", "连接池容量", ["service"]).labels(SERVICE)
        self.g_size.set(size)
        self.g_in_use = Gauge("app_db_pool_in_use", "当前占用连接数", ["service"]).labels(SERVICE)
        self.g_waiting = Gauge("app_db_pool_waiting", "排队等待连接的请求数", ["service"]).labels(SERVICE)
        self.h_wait = Histogram(
            "app_db_pool_wait_seconds",
            "获取连接的等待耗时(秒)",
            ["service"],
            buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0),
        ).labels(SERVICE)
        for i in range(size):
            self._free.put_nowait(i)

    async def acquire(self, timeout: float | None = None) -> int:
        t0 = time.perf_counter()
        self._waiting += 1
        self.g_waiting.set(self._waiting)
        try:
            try:
                conn = await asyncio.wait_for(
                    self._free.get(), timeout=timeout or self.wait_timeout
                )
            except asyncio.TimeoutError as e:
                raise PoolTimeout(
                    f"db pool busy: no free connection within {timeout or self.wait_timeout}s"
                ) from e
        finally:
            self._waiting -= 1
            self.g_waiting.set(self._waiting)
            self.h_wait.observe(time.perf_counter() - t0)
        self._in_use += 1
        self.g_in_use.set(self._in_use)
        return conn

    async def release(self, conn: int) -> None:
        self._in_use -= 1
        self.g_in_use.set(self._in_use)
        self._free.put_nowait(conn)

    def snapshot(self) -> dict[str, Any]:
        return {
            "size": self.size,
            "in_use": self._in_use,
            "waiting": self._waiting,
            "wait_timeout_s": self.wait_timeout,
        }


@asynccontextmanager
async def pool_connection(pool: SimPool, timeout: float | None = None):
    """业务端点取连接的标准姿势:PoolTimeout → HTTP 503(错误率可观测),finally 归还。"""
    try:
        conn = await pool.acquire(timeout=timeout)
    except PoolTimeout as e:
        raise HTTPException(status_code=503, detail="db pool busy (simulated)") from e
    try:
        yield conn
    finally:
        await pool.release(conn)


def _busy_loop(stop_evt: threading.Event) -> None:
    """CPU 忙循环:sha256 大缓冲(>2047B)会释放 GIL,多线程可吃满多核。"""
    buf = b"\x00" * (1024 * 1024)
    while not stop_evt.is_set():
        hashlib.sha256(buf).digest()


class FaultManager:
    """故障注入:pool_exhaust / cpu_spike,到期自动恢复;可提前 duration=0 取消。"""

    def __init__(self, pool: SimPool | None = None) -> None:
        self.pool = pool
        self._tasks: dict[str, asyncio.Task] = {}
        self._stop_events: dict[str, threading.Event] = {}

    def status(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for mode, task in self._tasks.items():
            out[mode] = {
                "active": not task.done(),
                "ends_at": getattr(task, "_sims_ends_at", None),
            }
        for mode in ("pool_exhaust", "cpu_spike"):
            out.setdefault(mode, {"active": False, "ends_at": None})
        return out

    def start(self, mode: str, duration: float) -> dict[str, Any]:
        if mode not in ("pool_exhaust", "cpu_spike"):
            raise ValueError(f"unknown fault mode: {mode}")
        self.cancel(mode)
        task = asyncio.create_task(self._run(mode, duration))
        task._sims_ends_at = time.strftime("%H:%M:%S", time.localtime(time.time() + duration))  # type: ignore[attr-defined]
        self._tasks[mode] = task
        return {"started": True, "mode": mode, "duration_s": duration,
                "note": "到期自动恢复;duration=0 表示取消"}

    def cancel(self, mode: str) -> None:
        old = self._tasks.get(mode)
        if old and not old.done():
            old.cancel()
        if mode == "cpu_spike":
            self._stop_events.get(mode, threading.Event()).set()

    async def _run(self, mode: str, duration: float) -> None:
        logger.warning("[fault] %s START duration=%.1fs", mode, duration)
        FAULT_ACTIVE.labels(mode).set(1)
        try:
            if mode == "pool_exhaust":
                await self._pool_exhaust(duration)
            else:
                await self._cpu_spike(duration)
        except asyncio.CancelledError:
            logger.warning("[fault] %s CANCELLED", mode)
        finally:
            FAULT_ACTIVE.labels(mode).set(0)
            logger.warning("[fault] %s END", mode)

    async def _pool_exhaust(self, duration: float) -> None:
        assert self.pool is not None, "pool_exhaust needs a SimPool"
        held: list[int] = []
        try:
            # 宽限超时拿到全部连接(在途请求短暂占用属正常);拿不满也算注入了现有可拿部分
            while len(held) < self.pool.size:
                try:
                    held.append(await self.pool.acquire(timeout=15.0))
                except PoolTimeout:
                    break
            await asyncio.sleep(duration)
        finally:
            for c in held:
                await self.pool.release(c)

    async def _cpu_spike(self, duration: float) -> None:
        stop = threading.Event()
        self._stop_events["cpu_spike"] = stop
        n = os.cpu_count() or 4
        threads = [threading.Thread(target=_busy_loop, args=(stop,), daemon=True) for _ in range(n)]
        for t in threads:
            t.start()
        try:
            await asyncio.sleep(duration)
        finally:
            stop.set()
            for t in threads:
                t.join(timeout=3)


class MetricsMiddleware(BaseHTTPMiddleware):
    """请求计数/耗时埋点;/metrics 自身不记(避免抓取流量污染)。"""

    @staticmethod
    def _label_path(request: Request) -> str:
        route = request.scope.get("route")
        return getattr(route, "path", request.url.path)

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        if request.url.path == "/metrics":
            return await call_next(request)
        t0 = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            HTTP_REQUESTS.labels(request.method, self._label_path(request), "500").inc()
            raise
        path = self._label_path(request)
        HTTP_REQUESTS.labels(request.method, path, str(response.status_code)).inc()
        HTTP_DURATION.labels(path).observe(time.perf_counter() - t0)
        return response


def start_cpu_poller(interval: float = 2.0) -> threading.Thread:
    """后台线程轮询本进程 CPU 写入 Gauge(psutil 首轮 interval=None 返回 0,后续为增量)。"""
    proc = psutil.Process()

    def _poll() -> None:
        proc.cpu_percent(interval=None)  # 首轮归零基线
        while True:
            time.sleep(interval)
            try:
                PROCESS_CPU.set(proc.cpu_percent(interval=None))
            except Exception:  # psutil 偶发 NoSuchProcess 等,不致命
                pass

    t = threading.Thread(target=_poll, daemon=True, name="cpu-poller")
    t.start()
    return t


def metrics_endpoint() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


async def self_load_loop(app: FastAPI, routes: list[dict[str, Any]], interval: float = 2.0) -> None:
    """内置自压测:周期请求业务端点,让 http_requests_total/耗时/池指标有基线流量。"""
    import httpx

    port = os.environ.get("SIM_PORT", "8000")
    base = f"http://127.0.0.1:{port}"
    async with httpx.AsyncClient(base_url=base, timeout=8.0) as client:
        i = 0
        while True:
            spec = routes[i % len(routes)]
            i += 1
            try:
                await client.request(spec["method"], spec["path"], json=spec.get("json"))
            except Exception as e:  # 自压测失败也计入指标,静默即可
                logger.debug("self-load %s failed: %s", spec["path"], e)
            await asyncio.sleep(interval)
