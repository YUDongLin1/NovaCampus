"""SIM-JIAOWU 教务系统(模拟)——P3a 对照服务

有界连接池(size 默认 8,POOL_SIZE 可调),业务端点占池 0.05~0.3s。
指标与故障注入端点与 ykt 同款(common 共用),用于总览盘双服务对照。

端点:
  GET  /health                        健康检查(含池快照)
  GET  /metrics                       Prometheus 文本
  GET  /api/courses                   课程列表
  GET  /api/grades/{student_id}       成绩查询
  POST /api/enroll                    选课
  POST /debug/fault/{mode}            故障注入 {"duration": N}(0=取消)
  GET  /debug/fault/status            注入状态
"""
from __future__ import annotations

import asyncio
import contextlib
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

SERVICE = "jiaowu"
POOL_SIZE = int(environ.get("POOL_SIZE", "8"))
POOL_WAIT = float(environ.get("POOL_WAIT_SECONDS", "2.0"))

pool = SimPool(size=POOL_SIZE, wait_timeout=POOL_WAIT)
faults = FaultManager(pool)

COURSES = [
    {"course_id": "C001", "name": "高等数学(下)", "credit": 5},
    {"course_id": "C002", "name": "数据结构", "credit": 4},
    {"course_id": "C003", "name": "操作系统", "credit": 4},
    {"course_id": "C004", "name": "计算机网络", "credit": 3},
    {"course_id": "C005", "name": "数据库原理", "credit": 3},
]

SELF_LOAD_ROUTES = [
    {"method": "GET", "path": "/api/courses"},
    {"method": "GET", "path": "/api/grades/S2025001"},
    {"method": "POST", "path": "/api/enroll",
     "json": {"student_id": "S2025001", "course_id": "C003"}},
]


async def _db_work(seconds: float) -> None:
    await asyncio.sleep(seconds)


@asynccontextmanager
async def lifespan(app: FastAPI):
    start_cpu_poller()
    load_task = asyncio.create_task(self_load_loop(app, SELF_LOAD_ROUTES, interval=2.0))
    yield
    load_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await load_task


app = FastAPI(title="SIM-JIAOWU 教务系统(模拟)", version="1.0.0", lifespan=lifespan)
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


@app.get("/api/courses")
async def courses() -> dict[str, Any]:
    async with pool_connection(pool) as conn:
        await _db_work(random.uniform(0.05, 0.15))
        return {"courses": COURSES, "conn": conn}


@app.get("/api/grades/{student_id}")
async def grades(student_id: str) -> dict[str, Any]:
    async with pool_connection(pool) as conn:
        await _db_work(random.uniform(0.1, 0.3))
        rows = [{"course_id": c["course_id"], "score": 60 + random.randint(0, 40)}
                for c in COURSES[:3]]
        return {"student_id": student_id, "grades": rows, "conn": conn}


@app.post("/api/enroll")
async def enroll(request: Request) -> dict[str, Any]:
    body = await request.json()
    async with pool_connection(pool) as conn:
        await _db_work(random.uniform(0.1, 0.25))
        return {"ok": True, "student_id": body.get("student_id"),
                "course_id": body.get("course_id"), "conn": conn}


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
