#!/usr/bin/env python3
"""P4b-fix ⑤ 探针:真 token 流阶段客户端中止 → 服务端回滚该轮 user 消息(只经 HTTP API)

对照 Review 证据 review_stream_abort.json(旧版:中止后残留 1 条无回复 user 消息)。
判定:中止后会话消息数不变(nothing_persisted=true);完整流对照轮 2 条(user+assistant)。
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:8900"
OUT = Path(__file__).resolve().parent / "evidence" / "after" / "stream_abort_v2.json"
H = {"Content-Type": "application/json"}

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
c = httpx.Client(timeout=180, trust_env=False)
tok = c.post(f"{BASE}/api/login", json={"username": "student", "password": "student123"}).json()["token"]
H["Authorization"] = f"Bearer {tok}"


def conv_count_by_title(title: str) -> tuple[int, int] | None:
    """按标题找最近创建的会话,返回 (conversation_id, message_total)。"""
    convs = c.get(f"{BASE}/api/conversations", headers=H, params={"limit": 20}).json()["conversations"]
    hit = next((x for x in convs if x["title"] == title), None)
    if not hit:
        return None
    msgs = c.get(f"{BASE}/api/conversations/{hit['id']}/messages", headers=H,
                 params={"limit": 200}).json()
    return hit["id"], msgs["total"]


def main() -> int:
    out = {}

    # --- 中止轮:读满 3 个 chunk 后切断(真 token 流阶段) ---
    q_abort = "研究生国家奖学金的评审流程和名额是怎样规定的?请详细展开说明。"
    events_seen = []
    chunks_read = 0
    with c.stream("POST", f"{BASE}/api/chat/stream", headers=H, json={"question": q_abort}) as r:
        for chunk in r.iter_raw():
            chunks_read += 1
            events_seen.append(chunk[:80])
            if chunks_read >= 3:
                break  # 直接断开连接 → 服务端生成器被取消
    time.sleep(4)  # 等服务端取消传播+回滚
    found = conv_count_by_title(q_abort[:20])
    assert found, "中止会话未找到(会话行应已创建)"
    cid_abort, total_after = found
    msgs = c.get(f"{BASE}/api/conversations/{cid_abort}/messages", headers=H,
                 params={"limit": 200}).json()["messages"]
    out["abort_mid_stream"] = {
        "conversation_id": cid_abort, "chunks_read": chunks_read,
        "roles_after": [m["role"] for m in msgs],
        "nothing_persisted": len(msgs) == 0,
    }

    # --- 对照轮:完整流 → user+assistant 各 1 条 ---
    q_full = "研究生申请休学需要提交哪些材料?"
    ev_types = []
    with c.stream("POST", f"{BASE}/api/chat/stream", headers=H, json={"question": q_full}) as r:
        buf = b""
        for chunk in r.iter_raw():
            buf += chunk
            while b"\n\n" in buf:
                raw, buf = buf.split(b"\n\n", 1)
                s = raw.decode("utf-8", "replace").strip()
                if s.startswith("data:"):
                    p = s[5:].strip()
                    if p and p != "[DONE]":
                        try:
                            ev_types.append(json.loads(p).get("type"))
                        except Exception:
                            pass
    time.sleep(1)
    cid_full, total_full = conv_count_by_title(q_full[:20])
    msgs_full = c.get(f"{BASE}/api/conversations/{cid_full}/messages", headers=H,
                      params={"limit": 200}).json()["messages"]
    out["full_stream"] = {
        "conversation_id": cid_full, "event_types": ev_types,
        "roles_after": [m["role"] for m in msgs_full],
        "persisted_two": len(msgs_full) == 2,
    }
    ok = out["abort_mid_stream"]["nothing_persisted"] and out["full_stream"]["persisted_two"]
    out["_verdict"] = "PASS: 中止轮零落库(回滚生效),完整轮正常落 2 条" if ok else "FAIL"
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=1)[:800])
    print(f"[saved] {OUT}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
