"""端到端现场演示(P3b C5):注入 → 告警 → 指标 → 日志 → 变更 → 预案 → 根因候选+证据链

用法:.venv/Scripts/python.exe tests/aiops_demo.py
前置:sims 监控栈在跑(ykt :9102、Prometheus :9090)、aiops MCP server 在 :18081、
NO_PROXY="127.0.0.1,localhost"。全流程约 60s(注入 45s 自动恢复)。
输出:stdout 逐步打印;重定向落盘 docs/p3b/evidence/demo_pool_exhaust.txt。
"""
import asyncio
import json
import sys
import time
import urllib.request

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

YKT = "http://127.0.0.1:9102"


def call_text(res) -> dict:
    assert not res.is_error, res.content
    return json.loads(res.content[0].text)


def trigger_pool_exhaust(duration: int = 45) -> None:
    req = urllib.request.Request(f"{YKT}/debug/fault/pool_exhaust",
                                 data=json.dumps({"duration": duration}).encode(),
                                 method="POST", headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        print(f"[demo 1] 触发注入: {resp.read().decode('utf-8')}")


async def main() -> int:
    print("=" * 72)
    print("AIOPS 端到端现场演示:ykt 连接池耗尽 → AIOps 工具链取证 → 根因候选")
    print("=" * 72)
    trigger_pool_exhaust(45)

    async with streamable_http_client("http://127.0.0.1:18081/mcp") as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()

            # 2) 轮询 list_alerts 直到 firing(注入场景 → SimsDbPoolSaturated)
            firing = []
            for _ in range(10):
                await asyncio.sleep(4)
                la = call_text(await s.call_tool("list_alerts", {"state": "firing"}))
                firing = [a["alertname"] for a in la.get("alerts", [])]
                print(f"[demo 2] list_alerts(firing): {firing}")
                if "SimsDbPoolSaturated" in firing:
                    break
            assert "SimsDbPoolSaturated" in firing, "未观测到池饱和告警"

            # 3) query_metrics:池利用率 + 5xx 速率
            qm = call_text(await s.call_tool("query_metrics", {
                "promql": "app_db_pool_in_use{job=\"ykt\"} / app_db_pool_size{job=\"ykt\"}"}))
            util = qm["results"][0]["values"][0]
            print(f"[demo 3a] 池利用率 = {float(util['value']) * 100:.1f}%  @ {util['time']}")
            qm2 = call_text(await s.call_tool("query_metrics", {
                "promql": "sum(rate(http_requests_total{job=\"ykt\",status=~\"5..\"}[30s]))"}))
            err = qm2["results"][0]["values"][0]
            print(f"[demo 3b] 5xx 速率 = {err['value']}/s  @ {err['time']}")
            assert float(qm["results"][0]["values"][0]["value"]) >= 0.999, "池未饱和"
            assert float(qm2["results"][0]["values"][0]["value"]) > 0, "5xx 速率未抬升"

            # 4) query_logs:捞 503 行
            ql = call_text(await s.call_tool("query_logs",
                                             {"service": "ykt", "keyword": "503",
                                              "minutes": 10, "tail": 300}))
            print(f"[demo 4] query_logs: 503 计数 {ql['status_code_counts'].get('503', 0)},"
                  f"样例 {ql['matched_lines'][:1]}")
            assert ql["status_code_counts"].get("503", 0) > 0, "日志中无 503"

            # 5) query_changes:认到注入事件
            qc = call_text(await s.call_tool("query_changes", {"service": "ykt", "minutes": 10}))
            kinds = {c["kind"] for c in qc["changes"]}
            print(f"[demo 5] query_changes: {[(c['kind'], c['job'], c.get('type')) for c in qc['changes']]}")
            assert "fault_injection_window" in kinds or "fault_injection_trigger" in kinds, \
                "变更记录中未认到注入事件"

            # 6) run_playbook:完整取证 + 根因候选 + 证据链
            pb = call_text(await s.call_tool("run_playbook",
                                             {"name": "pool_exhaust", "service": "ykt"}))
            print(f"[demo 6] run_playbook pool_exhaust:")
            for sg in pb["signals"]:
                fired = "命中" if sg["fired"] else "未命中"
                sample = sg["samples"][0]["value"] if sg["samples"] else "-"
                print(f"    signal[{fired}] {sg['desc']}: {sample}")
            print(f"    root_cause_hints: {pb['root_cause_hints']}")
            print(f"    mitigation: {pb['mitigation']['text'][:60]}...({pb['mitigation']['note']})")

            # 7) gather_diagnosis:一键取证 + 证据链(P3c 落点)
            gd = call_text(await s.call_tool("gather_diagnosis", {"service": "ykt", "minutes": 15}))
            print(f"[demo 7] gather_diagnosis 证据链 {len(gd['evidence_chain'])} 条:")
            for e in gd["evidence_chain"]:
                print(f"    {e['tool']}.{e['field']} = {e['value']}")

    print("AIOPS DEMO PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
