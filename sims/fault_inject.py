#!/usr/bin/env python3
"""P3a 故障注入 CLI(纯标准库,宿主机直跑)

用法:
  python sims/fault_inject.py --target ykt --mode pool_exhaust --duration 60
  python sims/fault_inject.py --target jiaowu --mode cpu_spike --duration 30
  python sims/fault_inject.py --target ykt --mode pool_exhaust --duration 0   # 提前取消

原理:调用目标服务的 POST /debug/fault/{mode} {"duration": N}——
  pool_exhaust:服务进程内并发占满全部连接(有界池),持到期满自动归还;
  cpu_spike:服务进程内多线程 busy-loop(sha256 大缓冲释放 GIL)抬 CPU。
到点自动恢复;CLI 默认轮询 /debug/fault/status 打印进度,--no-wait 仅触发不等待。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError, OSError):
    pass

DEFAULT_BASES = {
    "ykt": "http://127.0.0.1:9102",
    "jiaowu": "http://127.0.0.1:9101",
}


def http_json(method: str, url: str, body: dict | None = None, timeout: float = 15.0) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def read_cpu_percent(base: str, timeout: float = 5.0) -> float | None:
    """C2 取证:从 {base}/metrics(Prometheus 文本)解析无 label 的 process_cpu_percent。

    解析失败返回 None(轮询行打印 cpu=NA),不影响注入流程与退出码。
    """
    try:
        with urllib.request.urlopen(f"{base}/metrics", timeout=timeout) as resp:
            for line in resp.read().decode("utf-8", "replace").splitlines():
                # 精确匹配指标名(避开 process_cpu_seconds_total 等);该指标无 label
                if line.startswith("process_cpu_percent ") or line.startswith("process_cpu_percent{"):
                    tail = line.rsplit(None, 1)[-1] if " " in line else ""
                    return round(float(tail), 1)
    except Exception:
        return None
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description="P3a 故障注入 CLI")
    ap.add_argument("--target", required=True, choices=sorted(DEFAULT_BASES))
    ap.add_argument("--mode", required=True, choices=["pool_exhaust", "cpu_spike"])
    ap.add_argument("--duration", type=float, required=True,
                    help="注入秒数;0=取消进行中的注入")
    ap.add_argument("--base", default="", help="覆盖服务地址(默认按 target 取本机映射端口)")
    ap.add_argument("--no-wait", action="store_true", help="只触发,不轮询等待恢复")
    args = ap.parse_args()

    base = (args.base or DEFAULT_BASES[args.target]).rstrip("/")
    print(f"[inject] target={args.target} mode={args.mode} duration={args.duration}s base={base}")

    # 0) 注入前基线快照
    try:
        before = http_json("GET", f"{base}/debug/fault/status")
        print(f"[before] {json.dumps(before, ensure_ascii=False)}")
    except Exception as e:
        print(f"[FAIL] 无法连接 {base}: {e}")
        return 2

    # 1) 触发注入
    try:
        r = http_json("POST", f"{base}/debug/fault/{args.mode}", {"duration": args.duration})
        print(f"[OK] {json.dumps(r, ensure_ascii=False)}")
    except urllib.error.HTTPError as e:
        print(f"[FAIL] HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:200]}")
        return 1

    if args.duration <= 0 or args.no_wait:
        return 0

    # 2) 轮询至恢复(服务到期自动恢复);同窗抓 process_cpu_percent 留 CPU 文本证据(C2)
    t0 = time.time()
    cpu_peak: float | None = None
    deadline = t0 + args.duration + 30
    while time.time() < deadline:
        time.sleep(min(5.0, max(2.0, args.duration / 10)))
        cpu = read_cpu_percent(base)
        if cpu is not None and (cpu_peak is None or cpu > cpu_peak):
            cpu_peak = cpu
        try:
            st = http_json("GET", f"{base}/debug/fault/status")
            faults = st.get("faults", {})
            active = faults.get(args.mode, {}).get("active")
            pool = st.get("pool", {})
            print(f"[poll] t+{time.time() - t0:.0f}s active={active} "
                  f"pool_in_use={pool.get('in_use')} waiting={pool.get('waiting')} "
                  f"cpu={'NA' if cpu is None else f'{cpu:.1f}%'}")
            if not active:
                print(f"[OK] {args.mode} 已到期自动恢复")
                break
        except Exception as e:
            print(f"[WARN] 轮询失败: {e}")
    else:
        print("[FAIL] 等待超时,注入未如期恢复——请人工检查")
        return 1
    print(f"[cpu] cpu_peak={'NA' if cpu_peak is None else f'{cpu_peak:.1f}%'} "
          f"(来源: {base}/metrics 的 process_cpu_percent,轮询期采样取最大)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
