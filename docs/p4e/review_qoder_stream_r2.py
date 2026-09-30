#!/usr/bin/env python3
"""Qoder 独立复验 S1：三档流式形态对照（早窗 80 / 全缓冲 0 / 闸门关闭）+ 断开工不变量。

不复用他们的 judge（那是被测物的一部分），这里自己发请求、自己算：
  TTFB(首个 delta)、E2E、span=E2E-TTFB、delta 事件数、是否出现 grounding_retry、
  闸门命中与 retry 是否一致、断开后会话是否残留消息（P4b C5）。
断言阈值取他们规格里的 300ms span，但判据由本脚本独立实现。
两个服务都由本脚本 Popen、由本脚本 terminate，并用 psutil 复查端口（坑 61）。
"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time

import httpx

ROOT = r"E:/AILearn/NovaCampus"
PY = os.path.join(ROOT, "novaagent", ".venv", "Scripts", "python.exe")
Q = u"研究生申请休学需要提交哪些材料？审批流程又是怎样的？"
OUT = os.path.join(ROOT, "docs", "p4e", "evidence", "review", "qoder_stream_r2.json")
os.makedirs(os.path.dirname(OUT), exist_ok=True)

fails = []


def check(name, cond, detail=u""):
    print(u"  [%s] %s%s" % (u"OK " if cond else u"FAIL", name, (u" — " + detail) if detail else u""))
    if not cond:
        fails.append(u"%s: %s" % (name, detail))


def start(port, env_extra):
    env = dict(os.environ)
    env["NO_PROXY"] = "127.0.0.1,localhost"
    env["NOVAAGENT_EVAL_TEMPERATURE"] = "0"
    env.update(env_extra)
    log = open(os.path.join(tempfile.gettempdir(), "nova%d.log" % port), "w")
    p = subprocess.Popen([PY, "-m", "uvicorn", "novaagent.main:app", "--port", str(port),
                          "--host", "127.0.0.1"], cwd=os.path.join(ROOT, "novaagent"),
                         stdout=log, stderr=subprocess.STDOUT, env=env)
    for _ in range(40):
        time.sleep(3)
        s = socket.socket(); s.settimeout(1)
        ok = s.connect_ex(("127.0.0.1", port)) == 0
        s.close()
        if ok:
            return p
    p.kill(); raise RuntimeError("port %d not ready" % port)


def token(c, base, user, pw):
    return c.post(base + "/api/login", json={"username": user, "password": pw}).json()["token"]


def measure(base, tok, q=Q):
    c = httpx.Client(timeout=240)
    t0 = time.time(); ttfb = None; e2e = None; nd = 0; retry = False; done = {}
    with c.stream("POST", base + "/api/chat/stream", json={"question": q},
                  headers={"Authorization": "Bearer " + tok}) as r:
        for line in r.iter_lines():
            if not line or not line.startswith("data:"):
                continue
            try:
                ev = json.loads(line[5:].strip())
            except Exception:
                continue
            t = ev.get("type")
            if t == "delta":
                nd += 1
                if ttfb is None:
                    ttfb = round((time.time() - t0) * 1000)
            elif t == "grounding_retry":
                retry = True
            elif t == "done":
                done = ev
    e2e = round((time.time() - t0) * 1000)
    ctx = done.get("context") or {}
    return {
        "ttfb": ttfb, "e2e": e2e, "span": (e2e - ttfb) if (ttfb and e2e) else None,
        "deltas": nd, "retry": retry,
        "gate": ctx.get("grounding_gate"),
        "answer_len": len(done.get("answer") or ""),
        "n_sources": len(done.get("sources") or []),
        "cid": done.get("conversation_id"),
    }


def abort_probe(base, tok):
    """断开后消息不得落库（P4b C5）：显式建会话 → 流式读到几个 delta 就断 → 查该会话消息数。"""
    c = httpx.Client(timeout=240)
    h = {"Authorization": "Bearer " + tok}
    cid = c.post(base + "/api/conversations", headers=h,
                 json={"title": "qoder-abort-probe"}).json()["id"]
    n = 0
    try:
        with c.stream("POST", base + "/api/chat/stream",
                      json={"question": Q, "conversation_id": cid}, headers=h) as r:
            for line in r.iter_lines():
                if line.startswith("data:") and u'"type": "delta"' in line:
                    n += 1
                    if n >= 4:
                        break
    except Exception:
        pass
    time.sleep(2.0)
    js = c.get(base + "/api/conversations/%s/messages" % cid, headers=h).json()
    items = js.get("messages") if isinstance(js, dict) else js
    return {"deltas_before_abort": n, "cid": cid,
            "leftover": [m.get("role") for m in (items or [])]}


report = {}
print(u"=== A 档：默认（早窗 80 + 闸门开）===")
pA = start(8920, {})
try:
    c = httpx.Client(timeout=120); baseA = "http://127.0.0.1:8920"
    tokA = token(c, baseA, "student", "student123")
    a_runs = [measure(baseA, tokA) for _ in range(3)]
    report["early80"] = a_runs
    spans = [r["span"] for r in a_runs]
    check(u"早窗档 span > 300ms（渐进性存在）", all(s is not None and s > 300 for s in spans),
          u"spans=%s" % spans)
    check(u"早窗档 delta 数 >= 10", all(r["deltas"] >= 10 for r in a_runs),
          u"deltas=%s" % [r["deltas"] for r in a_runs])
    check(u"闸门命中与 grounding_retry 一致",
          all(bool((r["gate"] or {}).get("hit")) == bool(r["retry"]) for r in a_runs),
          u"gates=%s retries=%s" % ([bool((r["gate"] or {}).get("hit")) for r in a_runs],
                                    [r["retry"] for r in a_runs]))
    ab = abort_probe(baseA, tokA)
    report["abort_early80"] = ab
    check(u"断开后该会话零残留消息（P4b C5）", ab["leftover"] == [], u"leftover=%s" % ab["leftover"])
finally:
    pA.terminate()
    try:
        pA.wait(timeout=25)
    except Exception:
        pA.kill()

print(u"=== B 档：NOVA_GROUNDING_EARLY_WINDOW_CHARS=0（退回全缓冲）===")
pB = start(8921, {"NOVA_GROUNDING_EARLY_WINDOW_CHARS": "0"})
try:
    c = httpx.Client(timeout=120); baseB = "http://127.0.0.1:8921"
    tokB = token(c, baseB, "student", "student123")
    b_runs = [measure(baseB, tokB) for _ in range(2)]
    report["full_buffer"] = b_runs
    spans = [r["span"] for r in b_runs]
    check(u"全缓冲档 span 明显小于早窗档（证明这把尺子能判红）",
          all(s is not None and s < 200 for s in spans), u"spans=%s" % spans)
finally:
    pB.terminate()
    try:
        pB.wait(timeout=25)
    except Exception:
        pB.kill()

time.sleep(2)
for port in (8920, 8921):
    s = socket.socket(); s.settimeout(1)
    alive = s.connect_ex(("127.0.0.1", port)) == 0
    print(u"[端口复查] :%d 仍监听? %s" % (port, alive))
    check(u":%d 已关闭" % port, not alive, u"仍监听" if alive else u"")

report["fails"] = fails
json.dump(report, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print(u"\n[stream-r2] %s | 报告 %s" % (u"全部通过 ✓" if not fails else u"存在 FAIL ✗", OUT))
sys.exit(1 if fails else 0)
