"""query_metrics 只读防护测试(P3b C4)

覆盖:非法 promql(空/多语句/超长)被拒;admin/写类 Prometheus 路径被 _prom_get 拒绝;
区间点数超上限被截断并显式声明;promql 语法错误返回 ok=false;service 名注入被拒。
用法:.venv/Scripts/python.exe tests/test_query_metrics_guard.py
前置:sims 监控栈在跑(Prometheus :9090 可达);NO_PROXY="127.0.0.1,localhost"。
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # import server 模块本体

import server  # noqa: E402


def call(res_json: str) -> dict:
    return json.loads(res_json)


def check(name: str, cond: bool, detail: str = "") -> None:
    mark = "[PASS]" if cond else "[FAIL]"
    print(f"{mark} {name} {detail}")
    if not cond:
        raise SystemExit(1)


async def main() -> int:
    # 1) 空 promql 拒绝
    r = call(server.query_metrics(""))
    check("空 promql 被拒", not r["ok"] and "不能为空" in r["error"], r.get("error", ""))

    # 2) 多语句(分号)拒绝
    r = call(server.query_metrics("up; drop_database()"))
    check("多语句(分号)被拒", not r["ok"] and "分号" in r["error"], r.get("error", ""))

    # 3) 超长 promql 拒绝
    r = call(server.query_metrics("up" + "+1" * 1200))
    check("超长 promql 被拒", not r["ok"] and "过长" in r["error"], r.get("error", ""))

    # 4) admin/写类路径被 _prom_get 只读白名单拒绝
    for bad in ("/api/v1/admin/tsdb/delete_series", "/api/v1/status/config", "/-/reload"):
        try:
            server._prom_get(bad, {"query": "up"})
            check(f"写类/admin 路径 {bad} 被拒", False, "未被拒绝!")
        except server.AiopsGuardError as e:
            check(f"写类/admin 路径 {bad} 被拒", "只允许" in str(e))

    # 5) service 名 promql 注入(job 过滤参数)被拒
    r = call(server.get_service_status('ykt"} or up{job="jiaowu'))
    check("service 名非法字符被拒", not r["ok"], r.get("error", ""))

    # 6) 区间点数超上限被截断并显式声明(step=1s × 400s 窗口 → 401 点 > 200 上限)
    r = call(server.query_metrics("up{job=\"ykt\"}", start="not-a-time", end="now"))
    check("非法时间格式返回 ok=false", not r["ok"], r.get("error", ""))
    r = call(server.query_metrics("up{job=\"ykt\"}", window_s=400.0, step_s=1.0))
    check("区间点数超上限被截断并声明",
          r["ok"] and r["mode"] == "range" and r.get("truncated") is True
          and "截断" in (r.get("truncated_note") or ""),
          f"points={r.get('points_per_series')} note={r.get('truncated_note')}")

    # 7) promql 语法错误 → Prometheus error → ok=false
    r = call(server.query_metrics("up{"))
    check("promql 语法错误返回 ok=false", not r["ok"], (r.get("error") or "")[:80])

    # 8) 正常即时查询:时间 +0800 可读、数值 4 位有效
    r = call(server.query_metrics("up{job=\"ykt\"}"))
    check("正常即时查询", r["ok"] and r["mode"] == "instant" and r["results"], )
    v = r["results"][0]["values"][0]
    check("时间输出 +0800 可读", v["time"].endswith("+0800"), v["time"])
    check("数值 4 位有效", len(v["value"].replace(".", "").replace("-", "").lstrip("0")) <= 4, v["value"])

    # 9) mini-yaml 解析器与 pyyaml(若可用)对 playbooks.yml 结果一致
    text = open(server._PLAYBOOKS_PATH, encoding="utf-8").read()
    mini = server._mini_yaml(text)
    pb_mini = mini.get("playbooks", {})
    check("mini-yaml 解析出 3 条预案",
          set(pb_mini) >= {"pool_exhaust", "cpu_spike", "service_down"}
          and all(len(pb_mini[k].get("steps", [])) >= 3 for k in pb_mini),
          sorted(pb_mini))
    try:
        import yaml
        full = yaml.safe_load(text)["playbooks"]
        same_steps = all(len(full[k].get("steps", [])) == len(pb_mini[k].get("steps", []))
                         for k in full)
        check("mini-yaml 与 pyyaml 解析一致", same_steps, "")
    except ImportError:
        print("[SKIP] pyyaml 未安装,跳过一致性比对(回退路径即生产路径)")

    print("GUARD TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
