#!/usr/bin/env python3
"""P4d 硬要求 3 的证据:graph 化后 P4c 的 scope 语义**未被旁路**。

三条断言(每条都能失败,且均配非空/对照组):
  A. 对照组非空:student 不带 scope 问同一问题 → 200 且**有来源**(证明问题本身答得出来);
  B. 越权夹 404:student 带 counselor 私夹 scope → HTTP 404,且响应体与"不存在的夹"**逐字节相同**;
  C. 不外泄存在性:两个响应体相等 → 无法据此区分"该夹存在但无权"与"该夹不存在"。
  D. 空夹不回落:specific 空夹 → 零来源 + context.scope_empty=true(绝不回落全库)。

用法:NO_PROXY="127.0.0.1,localhost" python probe_scope_passthrough.py
"""
import json
import sys

import httpx

sys.path.insert(0, ".")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError, OSError):
    pass

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8900"
OUT = sys.argv[2] if len(sys.argv) > 2 else "../docs/p4d/evidence/after/scope_passthrough.json"
QUESTION = "学平险出险后怎么报销？"
results: list[dict] = []
bad: list[str] = []


def step(name: str, ok: bool, detail) -> None:
    results.append({"step": name, "ok": bool(ok), "detail": detail})
    if not ok:
        bad.append(name)
    print(f"[{'PASS' if ok else 'FAIL'}] {name} :: {detail}")


def _login(c: httpx.Client, username: str, password: str) -> dict:
    r = c.post(BASE + "/api/login", json={"username": username, "password": password}, timeout=30)
    r.raise_for_status()
    return {"Authorization": "Bearer " + r.json()["token"]}


def main() -> None:
    c = httpx.Client(timeout=180, trust_env=False)
    co = _login(c, "counselor", "counselor123")
    st = _login(c, "student", "student123")
    priv = empty = None
    try:
        priv = c.post(f"{BASE}/api/kb/folders", headers=co,
                      json={"name": "P4d-scope-私夹", "visibility": "private"}).json()["folder_id"]
        empty = c.post(f"{BASE}/api/kb/folders", headers=co,
                       json={"name": "P4d-scope-空夹", "visibility": "student"}).json()["folder_id"]

        # A 对照组:不带 scope 能答出来(非空前置)
        d = c.post(f"{BASE}/api/chat", headers=st, json={"question": QUESTION}).json()
        n = len(d.get("sources") or [])
        step("A 对照组(无 scope)有来源", n > 0, f"sources={n}")

        # B 越权夹 → 404
        r_priv = c.post(f"{BASE}/api/chat", headers=st,
                        json={"question": QUESTION, "scope": {"folder_ids": [priv]}})
        # 不存在的夹 → 404(对照)
        r_none = c.post(f"{BASE}/api/chat", headers=st,
                        json={"question": QUESTION, "scope": {"folder_ids": [99999999]}})
        step("B 越权夹 → 404", r_priv.status_code == 404,
             f"HTTP {r_priv.status_code} body={r_priv.text[:80]}")
        step("B2 不存在的夹 → 404(对照)", r_none.status_code == 404,
             f"HTTP {r_none.status_code} body={r_none.text[:80]}")
        step("C 两份响应体逐字节相同(不泄露存在性)",
             r_priv.status_code == r_none.status_code and r_priv.text == r_none.text,
             f"priv={r_priv.text!r} none={r_none.text!r}")

        # D 空夹 → 零来源 + scope_empty,绝不回落全库
        r2 = c.post(f"{BASE}/api/chat", headers=st,
                    json={"question": QUESTION, "scope": {"folder_ids": [empty]}})
        # 空夹对 student 可见(visibility=student) → 应当 200 且明确提示"未做全库检索"
        d2 = r2.json() if r2.status_code == 200 else {}
        srcs = d2.get("sources") or []
        ctx = d2.get("context") or {}
        step("D 空夹零来源且 scope_empty=true",
             r2.status_code == 200 and len(srcs) == 0 and ctx.get("scope_empty") is True,
             f"HTTP {r2.status_code} sources={len(srcs)} scope_empty={ctx.get('scope_empty')} "
             f"answer_head={(d2.get('answer') or '')[:60]!r}")
    finally:
        for fid in (priv, empty):
            if fid:
                c.delete(f"{BASE}/api/kb/folders/{fid}", headers=co, params={"cascade": "true"})
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({"base": BASE, "question": QUESTION, "all_pass": not bad,
                   "failed": bad, "steps": results}, f, ensure_ascii=False, indent=2)
    print(f"\n[SUM] {len(results) - len(bad)}/{len(results)} 过 → {OUT}")


main()
