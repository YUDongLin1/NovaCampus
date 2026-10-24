"""冒烟测试(P3b C3):验证 Streamable HTTP(/mcp,无状态)下
7 个 AIOps 工具可见可调用(仿 mcp/weekly/tests/smoke_test.py)。

用法:python tests/smoke_test.py http://127.0.0.1:18081
前置:sims 监控栈在跑;宿主机 docker CLI 可用(query_logs);本机代理会拦截
localhost,运行时须 NO_PROXY="127.0.0.1,localhost"。
"""
import asyncio
import json
import sys

from mcp import ClientSession
from mcp.client._probe import negotiate_auto
from mcp.client.streamable_http import streamable_http_client

EXPECTED_TOOLS = {"get_service_status", "list_alerts", "query_metrics", "query_logs",
                  "query_changes", "run_playbook", "gather_diagnosis"}


def call_text(res) -> dict:
    assert not res.is_error, res.content
    return json.loads(res.content[0].text)


async def exercise(session, label: str) -> None:
    tools = {t.name for t in (await session.list_tools()).tools}
    assert EXPECTED_TOOLS <= tools, f"[{label}] 缺工具: {EXPECTED_TOOLS - tools}"
    print(f"[{label}] 工具齐全: {sorted(tools)}")

    st = call_text(await session.call_tool("get_service_status", {}))
    assert st["ok"] and len(st["services"]) >= 1, st
    up_jobs = [s["job"] for s in st["services"] if s["up"] == 1]
    assert up_jobs, f"[{label}] 无 up 服务"
    print(f"[{label}] get_service_status OK: {[(s['job'], s['pool_utilization_pct']) for s in st['services']]}")

    qm = call_text(await session.call_tool("query_metrics", {"promql": "up{job=~\"ykt|jiaowu\"}"}))
    assert qm["ok"] and qm["series_returned"] >= 1, qm
    print(f"[{label}] query_metrics OK: up 序列 {qm['series_returned']} 条")

    la = call_text(await session.call_tool("list_alerts", {"state": "all"}))
    assert la["ok"] and la["rules_count"] >= 5, la
    print(f"[{label}] list_alerts OK: 规则 {la['rules_count']} 条,当前告警 {len(la['alerts'])} 条")

    qc = call_text(await session.call_tool("query_changes", {"minutes": 120}))
    assert qc["ok"] and isinstance(qc["changes"], list), qc
    print(f"[{label}] query_changes OK: 窗口内变更 {len(qc['changes'])} 条(带 source 字段:"
          f"{all('source' in c for c in qc['changes'])})")

    ql = call_text(await session.call_tool("query_logs", {"service": "jiaowu", "minutes": 30, "tail": 100}))
    assert ql["ok"] and ql["total_scanned"] > 0, ql
    print(f"[{label}] query_logs OK: 扫描 {ql['total_scanned']} 行,状态码分布 {ql['status_code_counts']}")

    dp = call_text(await session.call_tool("run_playbook", {"name": "pool_exhaust", "service": "ykt", "dry_run": True}))
    assert dp["ok"] and len(dp["steps"]) >= 3, dp
    print(f"[{label}] run_playbook dry_run OK: 步骤 {len(dp['steps'])} 条")

    pr = call_text(await session.call_tool("run_playbook", {"name": "pool_exhaust", "service": "ykt"}))
    assert pr["ok"] and pr["signals"] and pr["steps"], pr
    assert all(s["result"]["ok"] for s in pr["steps"]), pr
    print(f"[{label}] run_playbook 执行 OK: 信号 {len(pr['signals'])} 条,步骤 {len(pr['steps'])} 步全部只读成功")

    gd = call_text(await session.call_tool("gather_diagnosis", {"service": "ykt", "minutes": 15}))
    assert gd["ok"] and gd["evidence_chain"], gd
    print(f"[{label}] gather_diagnosis OK: 证据链 {len(gd['evidence_chain'])} 条")


async def main(base: str) -> int:
    async with streamable_http_client(f"{base}/mcp") as (r2, w2):
        async with ClientSession(r2, w2) as s:
            await negotiate_auto(s)
            await exercise(s, "StreamableHTTP")
    print("SMOKE TEST PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:18081")))
