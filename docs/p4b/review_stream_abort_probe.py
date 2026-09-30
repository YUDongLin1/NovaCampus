#!/usr/bin/env python3
"""P4b 复核:C5 服务端中止语义——在**真正的 token 流阶段**切断,而不是压缩阶段。

Zcode 的实测(c5_switch_abort.json)中止发生在压缩阶段,连 user 消息都未落库;
那只覆盖了"构建/压缩先于落库"这一半。本脚本读若干 SSE chunk 后立刻关连接,
断言:① 该会话消息数不变(该轮未发生);② 完整读完一轮则 +2 条(user+assistant)。

    /d/anaconda3/python.exe docs/p4b/review_stream_abort_probe.py
"""
import io
import json
import os
import sys
import time

import httpx

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

BASE = "http://127.0.0.1:8900"
OUT = r"E:\AILearn\NovaCampus\docs\p4b\evidence\after\review_stream_abort.json"
Q = "研究生申请休学需要提交哪些材料?"


def login():
    r = httpx.post(BASE + "/api/login", json={"username": "counselor", "password": "counselor123"}, timeout=20)
    r.raise_for_status()
    return {"Authorization": "Bearer " + r.json()["token"]}


def count(H, cid):
    d = httpx.get(BASE + "/api/conversations/%d/messages" % cid, headers=H,
                  params={"limit": 500}, timeout=20).json()
    return d["total"], d["messages"]


def main():
    H = login()
    res = {}
    cid = httpx.post(BASE + "/api/conversations", json={"title": "REVIEW-ABORT"}, headers=H, timeout=20).json()["id"]
    t0, _ = count(H, cid)

    # ① 流式读到第 3 个 chunk 就断开
    chunks = 0
    with httpx.Client(timeout=120) as c:
        with c.stream("POST", BASE + "/api/chat/stream", json={"question": Q, "conversation_id": cid},
                      headers=H) as r:
            for _ in r.iter_lines():
                chunks += 1
                if chunks >= 3:
                    break
    time.sleep(3.0)
    t1, msgs1 = count(H, cid)
    res["abort_mid_stream"] = {"chunks_read": chunks, "total_before": t0, "total_after": t1,
                               "roles_after": [m["role"] for m in msgs1],
                               "nothing_persisted": t1 == t0}
    print("[abort] 读到 %d 个 chunk 后断开: 消息 %d -> %d,该轮未落库=%s"
          % (chunks, t0, t1, t1 == t0))

    # ② 完整读完一轮
    got = []
    with httpx.Client(timeout=180) as c:
        with c.stream("POST", BASE + "/api/chat/stream", json={"question": Q, "conversation_id": cid},
                      headers=H) as r:
            for line in r.iter_lines():
                if line.startswith("data:"):
                    got.append(line[5:].strip())
    time.sleep(1.5)
    t2, msgs2 = count(H, cid)
    types = []
    for p in got:
        try:
            types.append(json.loads(p).get("type"))
        except Exception:
            pass
    res["full_stream"] = {"events": len(got), "event_types": sorted(set(types)),
                          "has_context_event": "context" in types,
                          "total_before": t1, "total_after": t2,
                          "persisted_two": t2 == t1 + 2,
                          "roles_after": [m["role"] for m in msgs2]}
    print("[full] 完整一轮: 事件 %d 种=%s,含 context 事件=%s;消息 %d -> %d(应 +2=%s)"
          % (len(got), sorted(set(types)), "context" in types, t1, t2, t2 == t1 + 2))

    httpx.delete(BASE + "/api/conversations/%d" % cid, headers=H, timeout=20)
    res["cleaned"] = True
    json.dump(res, io.open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    ok = res["abort_mid_stream"]["nothing_persisted"] and res["full_stream"]["persisted_two"] \
        and res["full_stream"]["has_context_event"]
    print("\n[SUM] %s | 证据写入 %s" % ("C5 服务端中止语义与 context 事件均成立" if ok else "C5 有不符合预期项,见 JSON", OUT))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
