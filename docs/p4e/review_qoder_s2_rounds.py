#!/usr/bin/env python3
"""Qoder 第 3 回闸门·后半：两档整轮（不带钩子 / canonical 带钩子）+ 冒烟 + 端口与库守恒。
span 分离度已由 review_qoder_s2_gate.py 前段实测完成（全缓冲 35/47/56ms vs 早窗 2687/2904/5713ms）。
"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time

ROOT = r"E:/AILearn/NovaCampus"
PY = os.path.join(ROOT, "novaagent", ".venv", "Scripts", "python.exe")
OUT = os.path.join(ROOT, "docs", "p4e", "evidence", "review", "qoder_s2_rounds.json")
fails = []
REP = {}


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
        if s.connect_ex(("127.0.0.1", port)) == 0:
            return p
    p.kill(); raise RuntimeError("port %d not ready" % port)


def stop(p):
    p.terminate()
    try:
        p.wait(timeout=25)
    except Exception:
        p.kill()


def newest_report():
    d = os.path.join(ROOT, "reports")
    fs = sorted([f for f in os.listdir(d) if f.startswith("eval_report_2026")], reverse=True)
    return fs[0], json.load(open(os.path.join(d, fs[0]), encoding="utf-8"))


def run_round(port, hook, smoke=False):
    env = dict(os.environ)
    env["NO_PROXY"] = "127.0.0.1,localhost"
    env["NOVAAGENT_EVAL_TEMPERATURE"] = "0"
    if hook:
        env["NOVA_GROUNDING_STREAM_FORCE_UNGROUNDED"] = "1"
    r = subprocess.run([PY, os.path.join(ROOT, "evals", "run_evals.py"),
                        "--base", "http://127.0.0.1:%d" % port],
                       cwd=os.path.join(ROOT, "novaagent"), capture_output=True,
                       text=True, encoding="utf-8", errors="replace", env=env)
    fname, rep = newest_report()
    out = {"exit": r.returncode, "report": fname,
           "total_pass": rep.get("total_pass"), "total": rep.get("total"),
           "env_flags": rep.get("env_flags"),
           "grounding_gate": rep.get("grounding_gate"),
           "fails": [x["id"] for x in rep.get("results", []) if not x.get("pass")],
           "ss03_detail": next((x.get("detail") for x in rep["results"] if x["id"] == "ss-03"), ""),
           "summary": {k: v for k, v in rep.get("summary", {}).items() if not isinstance(v, dict)}}
    if smoke:
        sm = subprocess.run([PY, "tests/smoke_test.py", "--base", "http://127.0.0.1:%d" % port],
                            cwd=os.path.join(ROOT, "novaagent"), capture_output=True,
                            text=True, encoding="utf-8", errors="replace",
                            env={**os.environ, "NO_PROXY": "127.0.0.1,localhost"})
        out["smoke_exit"] = sm.returncode
        out["smoke_tail"] = (sm.stdout or "")[-300:]
    return out


print(u"### A) 不带钩子整轮（默认配置，应复现他们声称的 54/55）###")
pA = start(8934, {})
try:
    a = run_round(8934, hook=False)
    REP["no_hook"] = a
    print(u"  报告 %s | 退出码 %s | %s/%s | 失败 %s"
          % (a["report"], a["exit"], a["total_pass"], a["total"], a["fails"]))
    print(u"  env_flags = %s" % json.dumps(a["env_flags"], ensure_ascii=False)[:240])
    print(u"  ss-03 文案 = %s" % (a["ss03_detail"] or "")[:220])
    check(u"默认档报告 JSON 里带 env_flags（且能看出钩子为关）",
          bool(a["env_flags"]) and ("force" in json.dumps(a["env_flags"]).lower()),
          json.dumps(a["env_flags"], ensure_ascii=False)[:180])
    check(u"默认档失败项只有 ss-03（其余全绿）且退出码非 0",
          a["fails"] == ["ss-03"] and a["exit"] == 1, u"fails=%s exit=%s" % (a["fails"], a["exit"]))
    check(u"ss-03 文案点名该设哪个环境变量",
          "NOVA_GROUNDING_STREAM_FORCE_UNGROUNDED" in (a["ss03_detail"] or ""),
          (a["ss03_detail"] or "")[:150])
    check(u"默认档报告逐用例 grounding 记账存在", bool(a["grounding_gate"]),
          json.dumps(a["grounding_gate"], ensure_ascii=False)[:260])
finally:
    stop(pA)

print(u"### B) canonical 整轮（带钩子）+ 冒烟 ###")
pB = start(8935, {"NOVA_GROUNDING_STREAM_FORCE_UNGROUNDED": "1"})
try:
    b = run_round(8935, hook=True, smoke=True)
    REP["canonical"] = b
    print(u"  报告 %s | 退出码 %s | %s/%s | 失败 %s"
          % (b["report"], b["exit"], b["total_pass"], b["total"], b["fails"]))
    print(u"  汇总 %s" % json.dumps(b["summary"], ensure_ascii=False)[:300])
    print(u"  grounding 记账 %s" % json.dumps(b["grounding_gate"], ensure_ascii=False)[:300])
    check(u"canonical 整轮 N/N 且退出码 0",
          b["exit"] == 0 and b["total_pass"] == b["total"],
          "%s/%s exit=%s fails=%s" % (b["total_pass"], b["total"], b["exit"], b["fails"]))
    envs = json.dumps(b["env_flags"], ensure_ascii=False).lower()
    check(u"canonical 报告 env_flags 记录钩子为开",
          ("force" in envs) and ("true" in envs), envs[:200])
    check(u"冒烟 exit 0", b.get("smoke_exit") == 0, str(b.get("smoke_tail"))[-160:])
    gg = json.dumps(b["grounding_gate"], ensure_ascii=False)
    check(u"记账能把 ungrounded 归到具体用例/轮次（不再靠 badcases 反推）",
          "cc-01" in gg or "turn" in gg, gg[:260])
finally:
    stop(pB)

time.sleep(2)
for port in (8934, 8935):
    s = socket.socket(); s.settimeout(1)
    alive = s.connect_ex(("127.0.0.1", port)) == 0
    check(u"端口 :%d 已关闭" % port, not alive, u"仍监听" if alive else u"")

kb = subprocess.run([PY, os.path.join(ROOT, "evals", "kb_doctor.py")],
                    cwd=os.path.join(ROOT, "novaagent"), capture_output=True,
                    text=True, encoding="utf-8", errors="replace",
                    env={**os.environ, "NO_PROXY": "127.0.0.1,localhost"})
line = (kb.stdout or "").splitlines()
print(u"### C) 库守恒 ###", line[0] if line else "(无输出)")
REP["kb_doctor"] = line[0] if line else ""
check(u"kb_doctor 回到 documents=65 / chunks=487",
      "documents=65" in REP["kb_doctor"] and "chunks=487" in REP["kb_doctor"], REP["kb_doctor"])

json.dump({"results": REP, "fails": fails}, open(OUT, "w", encoding="utf-8"),
          ensure_ascii=False, indent=2)
print(u"\n[S2 两档整轮] %s | %s" % (u"全部通过 ✓" if not fails else u"存在 FAIL ✗", OUT))
for f in fails:
    print(u"  -", f)
sys.exit(1 if fails else 0)
