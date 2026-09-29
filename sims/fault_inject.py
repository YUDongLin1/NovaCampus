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

    # 2) 轮询至恢复(服务到期自动恢复)
    t0 = time.time()
    deadline = t0 + args.duration + 30
    while time.time() < deadline:
        time.sleep(min(5.0, max(2.0, args.duration / 10)))
        try:
            st = http_json("GET", f"{base}/debug/fault/status")
            faults = st.get("faults", {})
            active = faults.get(args.mode, {}).get("active")
            pool = st.get("pool", {})
            print(f"[poll] t+{time.time() - t0:.0f}s active={active} "
                  f"pool_in_use={pool.get('in_use')} waiting={pool.get('waiting')}")
            if not active:
                print(f"[OK] {args.mode} 已到期自动恢复")
                return 0
        except Exception as e:
            print(f"[WARN] 轮询失败: {e}")
    print("[FAIL] 等待超时,注入未如期恢复——请人工检查")
    return 1


if __name__ == "__main__":
    sys.exit(main())
