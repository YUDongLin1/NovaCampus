#!/usr/bin/env python3
"""调试 sq-01: 移动文档入夹后, 库内实况 + scope 检索现场。只读查库。"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import httpx

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
BASE = "http://127.0.0.1:8900"
ROOT = Path(r"E:\AILearn\NovaCampus")
c = httpx.Client(timeout=240, trust_env=False)


def login(u, p):
    r = c.post(f"{BASE}/api/login", json={"username": u, "password": p})
    r.raise_for_status()
    return {"Authorization": "Bearer " + r.json()["token"]}


co = login("counselor", "counselor123")
st = login("student", "student123")
r = c.post(f"{BASE}/api/kb/folders", headers=co, json={"name": "P4c调试夹", "visibility": "student"})
fid = r.json()["folder_id"]
docs = c.get(f"{BASE}/api/kb/documents", headers=co).json()["documents"]
moved = next(d for d in docs if d["title"].startswith("关于西南交通大学2016年度"))
r = c.patch(f"{BASE}/api/kb/documents/{moved['id']}", headers=co, json={"folder_id": fid})
print("PATCH:", r.status_code, r.text[:120])

db = sqlite3.connect(f"file:{ROOT / 'novaagent' / 'data' / 'agent.db'}?mode=ro", uri=True)
row = db.execute("SELECT id, title, folder_id, audience, role_min FROM documents WHERE id=?",
                 (moved["id"],)).fetchone()
print("库内:", row)
print("该夹文档数:", db.execute("SELECT COUNT(*) FROM documents WHERE folder_id=?", (fid,)).fetchone()[0])
print("该文档块数:", db.execute("SELECT COUNT(*) FROM chunks WHERE doc_id=?", (moved["id"],)).fetchone()[0])
db.close()

r = c.post(f"{BASE}/api/chat", headers=st,
           json={"question": "学平险的参保方式和保费标准是什么？", "scope": {"folder_ids": [fid]}})
d = r.json()
print("chat:", r.status_code, "sources:", [(s["title"], s["score"]) for s in d.get("sources", [])])
print("ctx:", d.get("context"))
print("answer:", (d.get("answer") or "")[:100])

# 对照: counselor 直接问(同 scope)
r = c.post(f"{BASE}/api/chat", headers=co,
           json={"question": "学平险的参保方式和保费标准是什么？", "scope": {"folder_ids": [fid]}})
d = r.json()
print("counselor chat sources:", [(s["title"], s["score"]) for s in d.get("sources", [])])

# 清理
c.patch(f"{BASE}/api/kb/documents/{moved['id']}", headers=co, json={"folder_id": None})
c.delete(f"{BASE}/api/kb/folders/{fid}", headers=co, params={"cascade": "true"})
print("cleaned")
