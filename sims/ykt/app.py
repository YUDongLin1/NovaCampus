"""SIM-YKT 校园一卡通系统(模拟)——P3a 故障叙事主角

有界连接池(size 默认 10,POOL_SIZE 可调),/api/card/pay 持连接 0.3~0.6s 模拟对账写库。
池被占满时后续请求排队,等待超过 POOL_WAIT_SECONDS(默认 2s)→ 503(错误率↑)。

端点:
  GET  /health                        健康检查(含池快照)
  GET  /metrics                       Prometheus 文本
  GET  /api/card/{card_id}/balance    查余额(占池 ~0.1s)
  POST /api/card/pay                  消费扣款(占池 0.3~0.6s,故障主角)
  GET  /api/card/{card_id}/transactions  交易流水(占池 ~0.2s)
  POST /debug/fault/{mode}            故障注入 {"duration": N}(0=取消)
  GET  /debug/fault/status            注入状态
"""
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import random
from contextlib import asynccontextmanager
from os import environ
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException, Request, Response

from common import (
    FaultManager,
    MetricsMiddleware,
    SimPool,
    metrics_endpoint,
    pool_connection,
    self_load_loop,
    start_cpu_poller,
)

SERVICE = "ykt"
POOL_SIZE = int(environ.get("POOL_SIZE", "10"))
POOL_WAIT = float(environ.get("POOL_WAIT_SECONDS", "2.0"))

pool = SimPool(size=POOL_SIZE, wait_timeout=POOL_WAIT)
faults = FaultManager(pool)

SELF_LOAD_ROUTES = [
    {"method": "GET", "path": "/api/card/C2025001/balance"},
    {"method": "POST", "path": "/api/card/pay", "json": {"card_id": "C2025001", "amount": 12.5}},
    {"method": "GET", "path": "/api/card/C2025001/transactions"},
]


async def _db_work(seconds: float) -> None:
    """模拟一次 DB 往返延迟。"""
    await asyncio.sleep(seconds)


@asynccontextmanager
async def lifespan(app: FastAPI):
    start_cpu_poller()
    load_task = asyncio.create_task(self_load_loop(app, SELF_LOAD_ROUTES, interval=2.0))
    yield
    load_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await load_task


app = FastAPI(title="SIM-YKT 校园一卡通(模拟)", version="1.0.0", lifespan=lifespan)
app.add_middleware(MetricsMiddleware)


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": SERVICE,
        "pool": pool.snapshot(),
        "faults": faults.status(),
    }


@app.get("/metrics")
async def metrics() -> Response:
    return metrics_endpoint()


def _stable_number(seed: str, mod: int) -> int:
    return int(hashlib.sha256(seed.encode()).hexdigest(), 16) % mod


@app.get("/api/card/{card_id}/balance")
async def balance(card_id: str) -> dict[str, Any]:
    async with pool_connection(pool) as conn:
        await _db_work(random.uniform(0.05, 0.15))
        return {"card_id": card_id, "balance_yuan": round(_stable_number(card_id, 50000) / 100, 2),
                "conn": conn}


@app.post("/api/card/pay")
async def pay(request: Request) -> dict[str, Any]:
    body = await request.json()
    card_id, amount = str(body.get("card_id", "unknown")), float(body.get("amount", 0))
    async with pool_connection(pool) as conn:
        await _db_work(random.uniform(0.3, 0.6))  # 对账写库,持连接较久——池耗尽的放大器
        return {"ok": True, "card_id": card_id, "amount": amount, "balance_yuan": round(
            max(0.0, _stable_number(card_id, 50000) / 100 - amount), 2), "conn": conn}


@app.get("/api/card/{card_id}/transactions")
async def transactions(card_id: str) -> dict[str, Any]:
    async with pool_connection(pool) as conn:
        await _db_work(random.uniform(0.1, 0.3))
        items = [{"id": i, "amount": -round(_stable_number(f"{card_id}-{i}", 5000) / 100, 2)}
                 for i in range(5)]
        return {"card_id": card_id, "transactions": items, "conn": conn}


@app.post("/debug/fault/{mode}")
async def inject(mode: str, request: Request) -> dict[str, Any]:
    body = await request.json()
    duration = float(body.get("duration", 0))
    try:
        return faults.start(mode, duration)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/debug/fault/status")
async def fault_status() -> dict[str, Any]:
    return {"service": SERVICE, "faults": faults.status(), "pool": pool.snapshot()}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
