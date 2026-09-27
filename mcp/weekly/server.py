#!/usr/bin/env python3
"""周报 MCP Server(NovaCampus P1)— 辅导员碎片记录 → 结构化周报 → 归档

架构约定:分类智能交给 WeKnora 里的 Agent(LLM)完成,本 Server 只做
确定性的存取与渲染 —— 工具职责单一,便于评测与复用。

工具(5 个):
  add_fragment         记录一条工作碎片(未指定分类时由 Agent 判断后传入)
  list_fragments       按日期范围列出碎片
  delete_fragment      删除记录错误的碎片
  render_weekly_report 按日期范围聚合碎片,渲染结构化周报 Markdown 草稿
  archive_report       归档定稿周报(SQLite + Markdown 文件),供后续回灌知识库

运行:python server.py(环境变量 WEEKLY_DATA_DIR / WEEKLY_PORT)
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import date, datetime, timedelta
from pathlib import Path

from mcp.server.mcpserver import MCPServer

DATA_DIR = Path(os.environ.get("WEEKLY_DATA_DIR", "./data-weekly"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "weekly.db"
REPORTS_DIR = DATA_DIR / "reports"
REPORTS_DIR.mkdir(exist_ok=True)

CATEGORIES = ["谈心谈话", "事务办理", "活动组织", "异常突发", "其他"]

_lock = threading.Lock()
_conn = sqlite3.connect(DB_PATH, check_same_thread=False)
_conn.row_factory = sqlite3.Row
_conn.executescript(
    """
    CREATE TABLE IF NOT EXISTS fragments (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        content     TEXT NOT NULL,
        category    TEXT NOT NULL DEFAULT '其他',
        occurred_at TEXT NOT NULL,
        created_at  TEXT NOT NULL,
        deleted     INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS reports (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        title      TEXT NOT NULL,
        start_date TEXT NOT NULL,
        end_date   TEXT NOT NULL,
        content_md TEXT NOT NULL,
        file_path  TEXT NOT NULL,
        archived_at TEXT NOT NULL
    );
    """
)

mcp = MCPServer(
    "weekly-report",
    instructions=(
        "辅导员周报助手。标准流程:"
        "1) 用户随口说工作碎片时,调用 add_fragment 记录——若用户未明确分类,"
        f"由你根据内容从 {CATEGORIES} 中选择最贴切的一类传入 category;"
        "2) 用户要写周报时,先用 render_weekly_report 生成草稿,基于草稿润色输出给用户;"
        "3) 用户确认后调用 archive_report 归档定稿。"
    ),
)


def _today() -> str:
    return date.today().isoformat()


def _valid_date(s: str) -> str:
    date.fromisoformat(s)  # 值校验,不合法会抛 ValueError
    return s


def _ok(**kw) -> str:
    return json.dumps({"ok": True, **kw}, ensure_ascii=False)


def _err(msg: str) -> str:
    return json.dumps({"ok": False, "error": msg}, ensure_ascii=False)


@mcp.tool()
def add_fragment(content: str, category: str = "其他", occurred_at: str = "") -> str:
    """记录一条辅导员工作碎片。

    content: 碎片内容,一句话即可,尽量包含时间/对象/事项/结果;
    category: 必须是 谈心谈话/事务办理/活动组织/异常突发/其他 之一,由调用方(你)判断;
    occurred_at: 事件发生日期 YYYY-MM-DD,缺省为今天(注意区分"发生时间"与"记录时间")。
    """
    content = content.strip()
    if not content:
        return _err("content 不能为空")
    if category not in CATEGORIES:
        category = "其他"
    occurred = _valid_date(occurred_at) if occurred_at else _today()
    with _lock:
        cur = _conn.execute(
            "INSERT INTO fragments (content, category, occurred_at, created_at) VALUES (?,?,?,?)",
            (content, category, occurred, datetime.now().isoformat(timespec="seconds")),
        )
        _conn.commit()
        return _ok(fragment_id=cur.lastrowid, category=category, occurred_at=occurred)


@mcp.tool()
def list_fragments(start_date: str = "", end_date: str = "") -> str:
    """按发生日期范围(闭区间)列出碎片,缺省返回全部未删除记录。日期格式 YYYY-MM-DD。"""
    q, args = "SELECT id, content, category, occurred_at FROM fragments WHERE deleted=0", []
    if start_date:
        q += " AND occurred_at >= ?"
        args.append(_valid_date(start_date))
    if end_date:
        q += " AND occurred_at <= ?"
        args.append(_valid_date(end_date))
    q += " ORDER BY occurred_at, id"
    with _lock:
        rows = [dict(r) for r in _conn.execute(q, args)]
    return _ok(count=len(rows), fragments=rows)


@mcp.tool()
def delete_fragment(fragment_id: int) -> str:
    """删除一条记错的碎片(软删除)。"""
    with _lock:
        cur = _conn.execute("UPDATE fragments SET deleted=1 WHERE id=? AND deleted=0", (fragment_id,))
        _conn.commit()
    return _ok(deleted=cur.rowcount) if cur.rowcount else _err(f"未找到 id={fragment_id} 的有效碎片")


@mcp.tool()
def render_weekly_report(start_date: str, end_date: str = "") -> str:
    """聚合 [start_date, end_date] 内的碎片,渲染结构化周报 Markdown 草稿。

    end_date 缺省为 start_date 同周的周日。草稿返回后,你应润色措辞与总结,
    再让用户确认,确认后调用 archive_report 归档。
    """
    start = _valid_date(start_date)
    end = _valid_date(end_date) if end_date else str(
        date.fromisoformat(start) + timedelta(days=6 - date.fromisoformat(start).weekday())
    )
    with _lock:
        rows = [dict(r) for r in _conn.execute(
            "SELECT id, content, category, occurred_at FROM fragments "
            "WHERE deleted=0 AND occurred_at>=? AND occurred_at<=? ORDER BY occurred_at, id",
            (start, end),
        )]
    if not rows:
        return _err(f"{start} ~ {end} 没有已记录的碎片,请先用 add_fragment 记录")

    by_cat: dict[str, list[dict]] = {}
    for r in rows:
        by_cat.setdefault(r["category"], []).append(r)

    lines = [
        f"# 辅导员工作周报({start} ~ {end})",
        "",
        "## 本周概览",
        f"- 共记录 {len(rows)} 条工作事项:"
        + "、".join(f"{c} {len(v)} 条" for c, v in by_cat.items()),
        "",
    ]
    for cat in CATEGORIES:
        if cat not in by_cat:
            continue
        lines.append(f"## {cat}")
        for r in by_cat[cat]:
            d = r["occurred_at"][5:]  # MM-DD
            lines.append(f"- [{d}] {r['content']}")
        lines.append("")
    lines += ["## 下周计划", "- (待补充)", "", "> 本草稿由智枢 Agent 基于碎片记录自动整理,归档前请核对内容。"]
    return _ok(start_date=start, end_date=end, count=len(rows), report_markdown="\n".join(lines))


@mcp.tool()
def archive_report(title: str, start_date: str, end_date: str, content_md: str) -> str:
    """归档定稿周报:写入 SQLite 并保存 Markdown 文件,返回文件路径。

    title: 周报标题;content_md: 润色定稿后的完整 Markdown 内容(通常来自 render_weekly_report 的草稿)。
    """
    start, end = _valid_date(start_date), _valid_date(end_date)
    fname = f"{start}_{end}_周报.md"
    fpath = REPORTS_DIR / fname
    fpath.write_text(f"# {title}\n\n{content_md}", encoding="utf-8")
    with _lock:
        cur = _conn.execute(
            "INSERT INTO reports (title, start_date, end_date, content_md, file_path, archived_at) "
            "VALUES (?,?,?,?,?,?)",
            (title, start, end, content_md, str(fpath), datetime.now().isoformat(timespec="seconds")),
        )
        _conn.commit()
        return _ok(report_id=cur.lastrowid, file=str(fpath))


@mcp.tool()
def list_reports(start_date: str = "", end_date: str = "") -> str:
    """列出已归档周报(按归档时间倒序)。start_date/end_date 为可选过滤:
    只返回与 [start_date, end_date] 区间有重叠的周报。"""
    q = ("SELECT id, title, start_date, end_date, file_path, archived_at FROM reports WHERE 1=1")
    args: list[str] = []
    if start_date:
        q += " AND end_date >= ?"
        args.append(_valid_date(start_date))
    if end_date:
        q += " AND start_date <= ?"
        args.append(_valid_date(end_date))
    q += " ORDER BY id DESC"
    with _lock:
        rows = [dict(r) for r in _conn.execute(q, args)]
    return _ok(count=len(rows), reports=rows)


@mcp.tool()
def read_report(report_id: int) -> str:
    """读取一篇已归档周报的完整 Markdown 内容。"""
    with _lock:
        row = _conn.execute(
            "SELECT id, title, start_date, end_date, content_md, file_path, archived_at "
            "FROM reports WHERE id=?",
            (report_id,),
        ).fetchone()
    if row is None:
        return _err(f"未找到 id={report_id} 的归档周报")
    return _ok(**dict(row))


if __name__ == "__main__":
    # 双传输并存:SSE(/sse,WeKnora MCP 客户端使用)+ Streamable HTTP(/mcp,通用客户端)
    from contextlib import asynccontextmanager

    import uvicorn
    from starlette.applications import Starlette

    host = os.environ.get("WEEKLY_HOST", "0.0.0.0")
    port = int(os.environ.get("WEEKLY_PORT", "8000"))

    sse_asgi = mcp.sse_app(sse_path="/sse", message_path="/messages/", host=host)
    http_asgi = mcp.streamable_http_app(streamable_http_path="/mcp", host=host)

    @asynccontextmanager
    async def lifespan(_app):
        # streamable_http_app 的 lifespan 负责 StreamableHTTPSessionManager 启动,
        # 必须带着跑,否则 /mcp 请求会报 task group 未初始化
        async with http_asgi.router.lifespan_context(http_asgi):
            async with sse_asgi.router.lifespan_context(sse_asgi):
                yield

    app = Starlette(routes=[*http_asgi.routes, *sse_asgi.routes], lifespan=lifespan)
    uvicorn.run(app, host=host, port=port)
