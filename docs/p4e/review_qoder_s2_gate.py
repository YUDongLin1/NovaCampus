#!/usr/bin/env python3
"""Qoder 第 3 回合并闸门（P4e S2）——全部自测，不采信回执。

步骤：
 1) 默认实例（不带钩子）：/api/health 是否暴露 flags；三段式长问句的 span 直测 3 次
 2) 全缓冲实例（EARLY_WINDOW_CHARS=0）：同问句 3 次 → 由我亲手确认两档彻底分开
 3) 不带钩子跑整轮 → 复现他们声称的 54/55，并检查 ss-03 的 FAIL 文案是否点名环境变量
 4) 带钩子（canonical）跑整轮 → 复现 55/55，并检查报告新增 env_flags / grounding_gate 字段
 5) 冒烟 --base；6) 端口与库守恒复查
服务全部由本脚本 Popen 起、由本脚本 terminate，并按端口复查（坑 61/63）。
"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time

import httpx

ROOT = r"E:/AILearn/NovaCampus"
PY = os.path.join(ROOT, "novaagent", ".venv", "Scripts", "python.exe")
OUT_DIR = os.path.join(ROOT, "docs", "p4e", "evidence", "review")
os.makedirs(OUT_DIR, exist_ok=True)
REPORT = {}
fails = []


def check(name, cond, detail=u""):
    print(u"  [%s] %s%s" % (u"OK " if cond else u"FAIL", name, (u" — " + detail) if detail else u""))
    if not cond:
        fails.append(u"%s: %s" % (name, detail))


def start(port, env_extra, cwd_sub="novaagent"):
    env = dict(os.environ)
    env["NO_PROXY"] = "127.0.0.1,localhost"
    env["NOVAAGENT_EVAL_TEMPERATURE"] = "0"
    env.update(env_extra)
    log = open(os.path.join(tempfile.gettempdir(), "nova%d.log" % port), "w")
    p = subprocess.Popen([PY, "-m", "uvicorn", "novaagent.main:app", "--port", str(port),
                          "--host", "127.0.0.1"], cwd=os.path.join(ROOT, cwd_sub),
                         stdout=log, stderr=subprocess.STDOUT, env=env)
    for _ in range(40):
        time.sleep(3)
        s = socket.socket(); s.settimeout(1)
        ok = s.connect_ex(("127.0.0.1", port)) == 0
        s.close()
        if ok:
            return p
    p.kill(); raise RuntimeError("port %d not ready" % port)


def stop(p):
    p.terminate()
    try:
        p.wait(timeout=25)
    except Exception:
        p.kill()


def port_open(port):
    s = socket.socket(); s.settimeout(1)
    r = s.connect_ex(("127.0.0.1", port)) == 0
    s.close()
    return r


def span_runs(base, n=3):
    q = None
    for c in json.load(open(os.path.join(ROOT, "evals", "cases.json"), encoding="utf-8"))["cases"]:
        if c["id"] == "ss-01":
            q = c["question"]
    assert q, "cases.json 里取不到 ss-01 问句"
    c = httpx.Client(timeout=240)
    tok = c.post(base + "/api/login", json={"username": "student", "password": "student123"}).json()["token"]
    res = []
    for _ in range(n):
        t0 = time.time(); ttfb = None; nd = 0
        with c.stream("POST", base + "/api/chat/stream", json={"question": q},
                      headers={"Authorization": "Bearer " + tok}) as r:
            for line in r.iter_lines():
                if not line or not line.startswith("data:"):
                    continue
                try:
                    ev = json.loads(line[5:].strip())
                except Exception:
                    continue
                if ev.get("type") == "delta":
                    nd += 1
                    if ttfb is None:
                        ttfb = round((time.time() - t0) * 1000)
        e2e = round((time.time() - t0) * 1000)
        res.append({"ttfb": ttfb, "e2e": e2e, "span": e2e - ttfb if ttfb else None, "deltas": nd})
    return {"question_head": q[:34], "runs": res}


def run_eval(port, hook):
    env = dict(os.environ)
    env["NO_PROXY"] = "127.0.0.1,localhost"
    env["NOVAAGENT_EVAL_TEMPERATURE"] = "0"
    if hook:
        env["NOVA_GROUNDING_STREAM_FORCE_UNGROUNDED"] = "1"
    r = subprocess.run([PY, os.path.join(ROOT, "evals", "run_evals.py"),
                        "--base", "http://127.0.0.1:%d" % port],
                       cwd=os.path.join(ROOT, "novaagent"), capture_output=True,
                       text=True, encoding="utf-8", errors="replace", env=env)
    rep = None
    for f in sorted(os.listdir(os.path.join(ROOT, "reports")), reverse=True):
        if f.startswith("eval_report_2026"):
            rep = json.load(open(os.path.join(ROOT, "reports", f), encoding="utf-8"))
            newest = f
            break
    return r.returncode, (r.stdout or "")[-1400:], rep, locals().get("newest")


print(u"### 1) 默认实例（不带钩子）：health 是否暴露 flags ###")
pA = start(8930, {})
try:
    c = httpx.Client(timeout=60)
    h = c.get("http://127.0.0.1:8930/api/health").json()
    REPORT["health_default"] = h
    print(u"  /api/health =", json.dumps(h, ensure_ascii=False)[:300])
    flags = h.get("flags") or h.get("env_flags") or {}
    check(u"health 暴露了 flags 字段", bool(flags), u"keys=%s" % list(h.keys()))
    check(u"health 里能看到 GROUNDING 相关开关",
          any("grounding" in k.lower() or "GROUNDING" in k for k in (flags or {})),
          u"flags=%s" % json.dumps(flags, ensure_ascii=False)[:200])
    print(u"### 2) 早窗档 span 直测（默认实例）###")
    early = span_runs("http://127.0.0.1:8930", 3)
    REPORT["span_early80_qoder"] = early
    print(u"  问句:", early["question_head"])
    for r in early["runs"]:
        print(u"    ttfb=%s e2e=%s span=%s deltas=%s" % (r["ttfb"], r["e2e"], r["span"], r["deltas"]))
finally:
    stop(pA)

print(u"### 3) 全缓冲档 span 直测（EARLY_WINDOW_CHARS=0）###")
pB = start(8931, {"NOVA_GROUNDING_EARLY_WINDOW_CHARS": "0"})
try:
    full = span_runs("http://127.0.0.1:8931", 3)
    REPORT["span_full_qoder"] = full
    for r in full["runs"]:
        print(u"    ttfb=%s e2e=%s span=%s deltas=%s" % (r["ttfb"], r["e2e"], r["span"], r["deltas"]))
    fmax = max(r["span"] for r in full["runs"] if r["span"] is not None)
    emin = min(r["span"] for r in early["runs"] if r["span"] is not None)
    check(u"两档分离：全缓冲最大 span 远小于早窗最小 span 的一半",
          fmax < emin / 2, u"full_max=%s early_min=%s" % (fmax, emin))
    check(u"阈值 150 落在分布之外（全缓冲全 FAIL、早窗全 PASS）",
          all((r["span"] is not None and r["span"] < 150) for r in full["runs"]) and
          all((r["span"] is not None and r["span"] >= 150) for r in early["runs"]),
          u"full=%s early=%s" % ([r["span"] for r in full["runs"]], [r["span"] for r in early["runs"]]))
finally:
    stop(pB)

print(u"### 4) 不带钩子整轮（复现 54/55）###")
pC = start(8932, {})
try:
    rc, tail, rep, fname = run_eval(8932, hook=False)
    REPORT["round_no_hook"] = {"exit": rc, "report": fname,
                               "total_pass": rep and rep.get("total_pass"),
                               "total": rep and rep.get("total"),
                               "env_flags": rep and rep.get("env_flags"),
                               "grounding": rep and rep.get("grounding_gate"),
                               "fails": [r["id"] for r in (rep or {}).get("results", []) if not r.get("pass")],
                               "ss03_detail": next((r.get("detail") for r in (rep or {}).get("results", [])
                                                    if r["id"] == "ss-03"), None)}
    print(u"  报告", fname, "退出码", rc, REPORT["round_no_hook"]["total_pass"], "/", REPORT["round_no_hook"]["total"])
    print(u"  失败项:", REPORT["round_no_hook"]["fails"])
    print(u"  ss-03 文案:", (REPORT["round_no_hook"]["ss03_detail"] or "")[:200])
    check(u"报告里有 env_flags 字段", bool(rep and rep.get("env_flags")), u"keys=%s" % sorted((rep or {}).keys()))
    check(u"报告里有逐用例 grounding 记账", bool(rep and rep.get("grounding_gate")),
          u"=%s" % json.dumps((rep or {}).get("grounding_gate"), ensure_ascii=False)[:220])
    check(u"ss-03 的 FAIL 文案点名该设哪个环境变量",
          "NOVA_GROUNDING_STREAM_FORCE_UNGROUNDED" in (REPORT["round_no_hook"]["ss03_detail"] or ""),
          (REPORT["round_no_hook"]["ss03_detail"] or "")[:120])
finally:
    stop(pC)

print(u"### 5) canonical（带钩子）整轮 + 冒烟 ###")
pD = start(8933, {"NOVA_GROUNDING_STREAM_FORCE_UNGROUNDED": "1"})
try:
    rc2, tail2, rep2, fname2 = run_eval(8933, hook=True)
    fails2 = [r["id"] for r in (rep2 or {}).get("results", []) if not r.get("pass")]
    REPORT["round_canonical"] = {"exit": rc2, "report": fname2,
                                 "total_pass": rep2 and rep2.get("total_pass"),
                                 "total": rep2 and rep2.get("total"),
                                 "fails": fails2,
                                 "env_flags": rep2 and rep2.get("env_flags"),
                                 "grounding": rep2 and rep2.get("grounding_gate"),
                                 "summary": rep2 and rep2.get("summary")}
    print(u"  报告", fname2, "退出码", rc2, REPORT["round_canonical"]["total_pass"], "/", REPORT["round_canonical"]["total"],
          u"失败", fails2)
    check(u"canonical 整轮 N/N 且退出码 0", rc2 == 0 and (rep2 or {}).get("total_pass") == (rep2 or {}).get("total"),
          u"%s/%s exit=%s fails=%s" % ((rep2 or {}).get("total_pass"), (rep2 or {}).get("total"), rc2, fails2))
    envf = json.dumps((rep2 or {}).get("env_flags") or {}, ensure_ascii=False)
    check(u"canonical 报告的 env_flags 记录了钩子为开",
          "FORCE_UNGROUNDED" in envf.upper() or "force" in envf.lower(), envf[:220])
    sm = subprocess.run([PY, "tests/smoke_test.py", "--base", "http://127.0.0.1:8933"],
                        cwd=os.path.join(ROOT, "novaagent"), capture_output=True,
                        text=True, encoding="utf-8", errors="replace",
                        env={**os.environ, "NO_PROXY": "127.0.0.1,localhost"})
    REPORT["smoke"] = {"exit": sm.returncode, "tail": (sm.stdout or "")[-260:]}
    check(u"冒烟 exit 0", sm.returncode == 0, u"tail=%s" % (sm.stdout or "")[-160:])
finally:
    stop(pD)

time.sleep(2)
for port in (8930, 8931, 8932, 8933):
    check(u"端口 :%d 已关闭" % port, not port_open(port), u"仍监听" if port_open(port) else u"")

kb = subprocess.run([PY, os.path.join(ROOT, "evals", "kb_doctor.py")],
                    cwd=os.path.join(ROOT, "novaagent"), capture_output=True,
                    text=True, encoding="utf-8", errors="replace",
                    env={**os.environ, "NO_PROXY": "127.0.0.1,localhost"})
print(u"### 6) 库守恒 ###", (kb.stdout or "").splitlines()[0] if kb.stdout else kb.stdout)

REPORT["fails"] = fails
json.dump(REPORT, open(os.path.join(OUT_DIR, "qoder_s2_gate.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=2)
print(u"\n[S2 闸门] %s | 报告 %s" % (u"全部通过 ✓" if not fails else u"存在 FAIL ✗",
                                     os.path.join(OUT_DIR, "qoder_s2_gate.json")))
for f in fails:
    print(u"  -", f)
sys.exit(1 if fails else 0)
