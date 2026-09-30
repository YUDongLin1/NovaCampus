#!/usr/bin/env python3
"""P4d C1 证据:意图直答快路径 vs 检索生成路径的延迟对照。

同时给出两个口径:
  - **TTFD(首字延迟)**:/api/chat/stream 收到第一个 `delta` 事件的毫秒数——用户实际体感;
  - **E2E(端到端)**:/api/chat 非流式总耗时。

参与对照的问句:
  时间类(intent=time,不调 LLM)、闲聊(intent=chitchat,一次 LLM)、
  普通 qa(单遍检索即达标)、改写路径(需要 2 轮检索)。
"""
import json
import sys
import time

import httpx

sys.path.insert(0, ".")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError, OSError):
    pass

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8900"
OUT = sys.argv[2] if len(sys.argv) > 2 else "../docs/p4d/evidence/after/latency_compare.txt"
REPEAT = 3

CASES = [
    ("时间类(正则直答)", "retrieval_skipped", "现在几点了？"),
    ("闲聊(chitchat)", "retrieval_skipped", "你好，你是谁呀？"),
    ("普通qa(单遍达标)", "retrieval", "研究生申请休学需要哪些材料？"),
    ("改写路径(2轮检索)", "rewrite", "学平险在哪里买"),
]


def ttfd(client: httpx.Client, headers: dict, q: str) -> int | None:
    t0 = time.time()
    with client.stream("POST", f"{BASE}/api/chat/stream", headers=headers,
                       json={"question": q}, timeout=120) as r:
        r.raise_for_status()
        for line in r.iter_lines():
            if not line.startswith("data: "):
                continue
            payload = line[6:]
            if payload.strip() == "[DONE]":
                break
            try:
                ev = json.loads(payload)
            except json.JSONDecodeError:
                continue
            if ev.get("type") == "delta" and ev.get("content"):
                return round((time.time() - t0) * 1000)
    return None


def main() -> None:
    tok = httpx.post(f"{BASE}/api/login", json={"username": "student", "password": "student123"},
                     timeout=30).json()["token"]
    headers = {"Authorization": f"Bearer {tok}"}
    rows = []
    with httpx.Client() as c:
        for label, kind, q in CASES:
            ttfds, e2es, ctxs = [], [], None
            for _ in range(REPEAT):
                t0 = time.time()
                d = c.post(f"{BASE}/api/chat", headers=headers, json={"question": q}, timeout=120).json()
                e2es.append(round((time.time() - t0) * 1000))
                ctxs = d.get("context") or {}
                v = ttfd(c, headers, q)
                if v is not None:
                    ttfds.append(v)
            rows.append({
                "label": label, "kind": kind, "q": q,
                "ttfd_ms": sorted(ttfds)[len(ttfds) // 2] if ttfds else None,
                "e2e_ms": sorted(e2es)[len(e2es) // 2],
                "retrieval_skipped": ctxs.get("retrieval_skipped"),
                "attempts": ctxs.get("attempts"),
                "intent": ctxs.get("intent"),
            })
            r = rows[-1]
            print(f"{r['label']:18s} TTFD={str(r['ttfd_ms']):>6s}ms  E2E={r['e2e_ms']:>6d}ms  "
                  f"skipped={r['retrieval_skipped']} attempts={r['attempts']} intent={r['intent']}")

    direct = [r for r in rows if r["kind"] == "retrieval_skipped"]
    retr = [r for r in rows if r["kind"] in ("retrieval", "rewrite")]
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("P4d C1 延迟对照(中位数,每例 3 次;TTFD=SSE 首个 delta 到达毫秒数)\n")
        f.write(f"{'场景':20s} {'类型':18s} {'TTFD(ms)':>10s} {'E2E(ms)':>10s} "
                f"{'检索跳过':>9s} {'检索轮数':>9s} {'intent':>12s}\n")
        for r in rows:
            f.write(f"{r['label']:20s} {r['kind']:18s} {str(r['ttfd_ms']):>10s} {r['e2e_ms']:>10d} "
                    f"{str(r['retrieval_skipped']):>9s} {str(r['attempts']):>9s} {str(r['intent']):>12s}\n")
        if direct and retr:
            dt = max(r["ttfd_ms"] or 0 for r in direct)
            rt = min(r["ttfd_ms"] or 0 for r in retr)
            f.write(f"\n直答路径 TTFD 上界={dt}ms;检索路径 TTFD 下界={rt}ms;"
                    f"{'快路径显著更快' if dt < rt else '⚠ 快路径未更快,需排查'}\n")
    print(f"\n已写入 {OUT}")


main()
