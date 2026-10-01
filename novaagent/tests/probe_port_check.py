#!/usr/bin/env python3
"""C0-⑤ 端口复查验证用的**零额度**探针(只打 /api/health)。

## 为什么需要它

`docs/p4d/run_with_server.sh` 改完后会打印 `[port-check] :<port> closed=True/False`。
要验证这一行,得真起一次服务 —— 但**不能**用 `run_evals.py` / `smoke_test.py` 验:
那两个都会发真实 LLM 请求,落在 `novaagent/.env` 的用户额度上(硬约束第 7 条)。

本探针只做一次 `GET /api/health`:
  · 不带任何 question → 不进 agent.chat_for → **不调 LLM、不调 embedding**;
  · 顺便把 C0-⑥ 的 `llm_key_source` / `embedding_key_source` 读数打出来 ——
    这两行既验证 health flags 真的带了 key_source,又验证**这次没注入会话环境变量**
    (读数应为 repo_dotenv,也就是"整轮结果一律不认"的那一档)。

跑法(由 run_with_server.sh 拉起,或手工):
    bash docs/p4d/run_with_server.sh 8941 tests/probe_port_check.py --base http://127.0.0.1:8941
退出码:0 = health 可读;非 0 = 连不上或 flags 缺字段。
"""
from __future__ import annotations

import argparse
import json
import sys

BASE = "http://127.0.0.1:8900"
REQUIRED_FLAGS = ("llm_key_source", "embedding_key_source",
                  "grounding_gate_scope_mode", "web_search_idle_timeout_s",
                  "web_search_total_timeout_s")


def main() -> int:
    global BASE
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=BASE)
    BASE = ap.parse_args().base.rstrip("/")

    import httpx

    failed: list[str] = []
    with httpx.Client(timeout=15) as c:
        r = c.get(f"{BASE}/api/health")
        if r.status_code != 200:
            print(f"[FAIL] /api/health → {r.status_code}", file=sys.stderr)
            return 1
        payload = r.json() or {}
        flags = payload.get("flags") or {}

        print(f"[probe] base={BASE}")
        print(f"[probe] status={payload.get('status')} weekly_mcp={payload.get('weekly_mcp')}")

        missing = [k for k in REQUIRED_FLAGS if k not in flags]
        if missing:
            failed.append(f"health flags 缺字段: {missing}")
        else:
            print("[PASS] /api/health 可读,且 flags 含 C0-③/④/⑥ 的全部字段")
            for k in REQUIRED_FLAGS:
                print(f"[probe]   {k} = {flags.get(k)!r}")

        # 本次**未注入**会话环境变量 → 读数应为 repo_dotenv。
        # 打印它不是为了"证明额度可用",而是为了留下"这次没碰用户额度"的痕迹:
        # 若这里显示 session_env,说明调用方的环境里带着 key,证据链要重走。
        src = flags.get("llm_key_source")
        print(f"[probe] llm_key_source={src!r} (repo_dotenv = 本次用的是仓库 .env,"
              f"按 C0-⑥ 规则该轮结果不认)")
        if src == "session_env":
            failed.append("本次进程带着会话环境变量 key(C0-⑥:该轮结果不认),证据链须重走")

        # 硬断言:本探针绝不能留下 key 值 —— 只允许来源标签与模型名。
        blob = json.dumps(payload, ensure_ascii=False)
        for bad in ("sk-", "Bearer ", "api_key\":\""):
            if bad in blob:
                failed.append(f"health 响应含疑似 key 形态串 {bad!r}")

    for f in failed:
        print(f"[FAIL] {f}", file=sys.stderr)
    print(f"[RESULT] {5 - len(failed)}/5 passed" if failed else "[RESULT] 5/5 passed")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())