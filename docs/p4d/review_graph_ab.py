#!/usr/bin/env python3
"""P4d 合并前把关:忠实度回归的根因 A/B(graph 编排开 / 关)。

现象:qa-12、qa-13 在此前 7 轮忠实度恒为 1.0,恰好在本单这轮同时变 0.0;
     而 qa-12 的答案是"有 3 条来源却答『研究生…未在知识库覆盖』"的非答案,却因关键词判 PASS。
做法:用 config 里的 NOVA_GRAPH_ENABLED 开关起两个实例做 A/B(同一 DB、同一问句、同一角色),
     对比 sources 集合与答案是否作答。只读查询,不改库、不动实现方的 :8900。

用法(需先起 graph-off 实例,见 docs/p4d/review_graph_ab.sh 或本脚本自动起的命令):
    NO_PROXY="127.0.0.1,localhost" novaagent/.venv/Scripts/python.exe -X utf8 docs/p4d/review_graph_ab.py
"""
import io
import json
import os
import subprocess
import sys
import time

import httpx


# ---- 演示口令:一律从环境变量读,源码内不落明文(开源前脱敏要求) ----
def _demo_pw(role: str) -> str:
    r = role.upper()
    pwd = os.environ.get(f"NOVA_SEED_{r}_PASSWORD") or os.environ.get("NOVA_DEMO_PASSWORD", "")
    if not pwd:
        raise RuntimeError(
            f"未设置演示口令:请在 novaagent/.env 中写入 NOVA_DEMO_PASSWORD"
            f"(或 NOVA_SEED_{r}_PASSWORD)。")
    return pwd


ADMIN_PW = _demo_pw("admin")
COUNSELOR_PW = _demo_pw("counselor")
STUDENT_PW = _demo_pw("student")


try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = r"E:\AILearn\NovaCampus"
ON = "http://127.0.0.1:8900"          # 实现方实例(graph 默认开启)
OFF = "http://127.0.0.1:8903"         # 本脚本起的 graph-off 实例
OUT = ROOT + r"\docs\p4d\evidence\after\review_graph_ab.json"
PW = {"admin": ADMIN_PW, "counselor": COUNSELOR_PW, "student": STUDENT_PW}
IDS = ["qa-12", "qa-13", "rind-02"]
PORT_PAT = "8903"


def tok(base, role):
    r = httpx.post(base + "/api/login", json={"username": role, "password": PW[role]}, timeout=20)
    r.raise_for_status()
    return {"Authorization": "Bearer " + r.json()["token"]}


def ask(base, H, q):
    d = httpx.post(base + "/api/chat", json={"question": q}, headers=H, timeout=180).json()
    srcs = d.get("sources") or []
    return {"answer": d.get("answer") or "", "titles": [s.get("title") for s in srcs],
            "n_sources": len(srcs), "ctx": {k: (d.get("context") or {}).get(k)
                                            for k in ("intent", "attempts", "rewritten", "scope",
                                                      "retrieval_skipped")}}


NON_ANSWER = ("未在知识库覆盖", "未检索到", "暂无相关", "无法给出", "没有相关", "未覆盖", "请以")


def is_non_answer(a):
    return len(a) < 160 and any(m in a for m in NON_ANSWER)


def main():
    spec = json.load(io.open(ROOT + r"\evals\cases.json", encoding="utf-8"))
    cases = {c["id"]: c for c in spec["cases"]}
    print("[准备] 起 graph-off 实例 :%s" % PORT_PAT)
    env = dict(os.environ, NOVA_GRAPH_ENABLED="0", NO_PROXY="127.0.0.1,localhost",
               NOVAAGENT_EVAL_TEMPERATURE="0")
    logf = io.open(os.path.join(os.environ.get("TEMP", "."), "nova_p4d_graphoff.log"), "wb")
    proc = subprocess.Popen([ROOT + r"\novaagent\.venv\Scripts\python.exe", "-m", "uvicorn",
                             "novaagent.main:app", "--port", PORT_PAT],
                            cwd=ROOT + r"\novaagent", env=env, stdout=logf, stderr=subprocess.STDOUT)
    try:
        ok = False
        for _ in range(40):
            try:
                if httpx.get(OFF + "/api/health", timeout=3).status_code == 200:
                    ok = True
                    break
            except Exception:
                pass
            time.sleep(2)
        if not ok:
            print("[FAIL] graph-off 实例没起来,看日志 nova_p4d_graphoff.log")
            sys.exit(2)
        print("[OK] graph-off 实例就绪")

        res = {}
        for cid in IDS:
            c = cases[cid]
            role = c.get("role", "student")
            row = {}
            for label, base in (("graph_on", ON), ("graph_off", OFF)):
                H = tok(base, role)
                a = ask(base, H, c["question"])
                row[label] = {"n_sources": a["n_sources"], "titles": a["titles"],
                              "non_answer": is_non_answer(a["answer"]),
                              "answer_head": a["answer"][:220], "ctx": a["ctx"]}
            same_titles = sorted(row["graph_on"]["titles"]) == sorted(row["graph_off"]["titles"])
            row["same_source_set"] = same_titles
            res[cid] = row
            print("\n[%s] 角色=%s 来源集合相同=%s" % (cid, role, same_titles))
            for label in ("graph_on", "graph_off"):
                r = row[label]
                print("   %-10s sources=%d 非答案=%s 改写=%s intent=%s | %s"
                      % (label, r["n_sources"], r["non_answer"], (r["ctx"] or {}).get("rewritten"),
                         (r["ctx"] or {}).get("intent"), r["answer_head"][:90].replace("\n", " / ")))
        json.dump(res, io.open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print("\n[OK] 证据写入 %s" % OUT)
    finally:
        # 只回收本脚本自己起的进程(argv 逐项比对,绝不做子串匹配 —— 坑 37)
        try:
            import psutil
            p = psutil.Process(proc.pid)
            for ch in p.children(recursive=True):
                ch.terminate()
            p.terminate()
            p.wait(timeout=15)
            print("[CLEAN] 已回收自己起的 graph-off 实例 pid=%d" % proc.pid)
        except Exception as e:
            proc.kill()
            print("[CLEAN] terminate 异常,已 kill(%s)" % e)
    r = httpx.get(ON + "/api/health", timeout=5)
    print("[确认] 实现方 :8900 仍在,health=%s" % r.status_code)


if __name__ == "__main__":
    main()
