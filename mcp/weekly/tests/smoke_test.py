"""冒烟测试:同时验证 SSE(/sse,WeKnora 用)与 Streamable HTTP(/mcp)两种传输

用法:python tests/smoke_test.py http://127.0.0.1:18080
本机代理会拦截 localhost,运行时须 NO_PROXY="127.0.0.1,localhost"。
"""
import asyncio
import json
import sys

from mcp import ClientSession
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamable_http_client

EXPECTED_TOOLS = {"add_fragment", "list_fragments", "delete_fragment", "render_weekly_report",
                  "archive_report", "list_reports", "read_report"}


def call_text(res) -> dict:
    assert not res.is_error, res.content
    return json.loads(res.content[0].text)


async def exercise(session, label: str, cleanup_ids: list[int]) -> None:
    tools = {t.name for t in (await session.list_tools()).tools}
    assert EXPECTED_TOOLS <= tools, f"[{label}] 缺工具: {EXPECTED_TOOLS - tools}"
    print(f"[{label}] 工具齐全: {sorted(tools)}")

    a = call_text(await session.call_tool("add_fragment", {
        "content": "与姓名1同学谈话,反馈补考压力,已转介心理中心",
        "category": "谈心谈话", "occurred_at": "2026-09-24"}))
    b = call_text(await session.call_tool("add_fragment", {
        "content": "处理学生宿舍网络报修一间",
        "occurred_at": "2026-09-25"}))  # 不传 category → 应回落"其他"
    assert a["ok"] and b["ok"] and b["category"] == "其他", (a, b)
    print(f"[{label}] 记录碎片 OK: id={a['fragment_id']},{b['fragment_id']}(分类回落正确)")

    r = call_text(await session.call_tool("render_weekly_report", {
        "start_date": "2026-09-21", "end_date": "2026-09-27"}))
    assert r["ok"] and r["count"] >= 2 and "谈心谈话" in r["report_markdown"]
    print(f"[{label}] 周报草稿 OK(共 {r['count']} 条,含分类聚合)")

    arc = call_text(await session.call_tool("archive_report", {
        "title": f"P1 冒烟测试({label})", "start_date": "2026-09-21",
        "end_date": "2026-09-27", "content_md": r["report_markdown"]}))
    assert arc["ok"] and arc["file"].endswith(".md")
    print(f"[{label}] 归档 OK: {arc['file']}")

    lr = call_text(await session.call_tool("list_reports", {}))
    assert lr["ok"] and lr["count"] >= 1
    rid = lr["reports"][0]["id"]
    rr = call_text(await session.call_tool("read_report", {"report_id": rid}))
    assert rr["ok"] and "# " in rr["content_md"]
    print(f"[{label}] 归档列表/读取 OK({lr['count']} 篇)")

    for fid in (a["fragment_id"], b["fragment_id"]):
        d = call_text(await session.call_tool("delete_fragment", {"fragment_id": fid}))
        assert d["ok"]
    cleanup_ids.extend([a["fragment_id"], b["fragment_id"]])
    print(f"[{label}] 清理测试数据 OK")


async def main(base: str) -> int:
    async with sse_client(f"{base}/sse") as (r1, w1):
        async with ClientSession(r1, w1) as s:
            await s.initialize()
            await exercise(s, "SSE", [])
    async with streamable_http_client(f"{base}/mcp") as (r2, w2):
        async with ClientSession(r2, w2) as s:
            await s.initialize()
            await exercise(s, "StreamableHTTP", [])
    print("SMOKE TEST PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:18080")))
