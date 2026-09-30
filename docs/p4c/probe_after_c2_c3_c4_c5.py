#!/usr/bin/env python3
"""P4c C2/C3/C4/C5 集中 API 验证探针(自清理, 证据落盘即判红)。

覆盖:
  C2 文件夹 CRUD/重命名/重名 409/批量移动/非空删除 409/级联移回根
  C3 scope 三输入对照(全库/指定夹/越权夹) + 来源全属该库
  C4 question 与 scope 分离(请求体内无 @ 残留;服务端拒 @ 开头问题)
  C5 audience 标注/筛选 + F3 学段追问(需成对标注材料才触发;清理后不触发)
坑 33: 每步断言取到非空才继续;坑 39: 任何断言失败 → exit 1。
产出: docs/p4c/evidence/after/c2_c3_c4_c5_api_checks.json
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:8900"
ROOT = Path(__file__).resolve().parent.parent.parent
OUT = ROOT / "docs" / "p4c" / "evidence" / "after" / "c2_c3_c4_c5_api_checks.json"

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
steps: list[dict] = []
ok_all = True


def step(name: str, cond: bool, detail=""):
    global ok_all
    steps.append({"step": name, "pass": bool(cond), "detail": str(detail)[:400]})
    print(("[PASS] " if cond else "[FAIL] ") + name + (f" | {str(detail)[:120]}" if detail else ""))
    ok_all = ok_all and bool(cond)
    return cond


def login(c, u, p):
    r = c.post(f"{BASE}/api/login", json={"username": u, "password": p})
    r.raise_for_status()
    return {"Authorization": "Bearer " + r.json()["token"]}


def main() -> int:
    c = httpx.Client(timeout=240, trust_env=False)
    co = login(c, "counselor", "counselor123")
    ad = login(c, "admin", "admin123")
    st = login(c, "student", "student123")
    base_docs = c.get(f"{BASE}/api/kb/documents", headers=co).json()["documents"]
    n_base = len(base_docs)
    t0 = time.time()

    # ---------- C2 文件夹 CRUD ----------
    r = c.post(f"{BASE}/api/kb/folders", headers=co, json={"name": "P4c夹A", "visibility": "counselor"})
    step("C2 建夹 A", r.status_code == 200 and r.json().get("folder_id"), r.text[:120])
    fa = r.json()["folder_id"]
    fb = c.post(f"{BASE}/api/kb/folders", headers=co, json={"name": "P4c夹B", "visibility": "counselor"}).json()["folder_id"]
    r = c.post(f"{BASE}/api/kb/folders", headers=co, json={"name": "P4c夹A"})
    step("C2 同层重名 → 409", r.status_code == 409, r.status_code)
    r = c.patch(f"{BASE}/api/kb/folders/{fa}", headers=co, json={"name": "P4c夹A2"})
    step("C2 重命名", r.status_code == 200 and r.json()["name"] == "P4c夹A2", r.text[:120])
    r = c.patch(f"{BASE}/api/kb/folders/{fa}", headers=co, json={"name": "P4c夹B"})
    step("C2 改成同级已有名 → 409", r.status_code == 409, r.status_code)
    r = c.get(f"{BASE}/api/kb/folders", headers=co)
    names = [f["name"] for f in r.json()["folders"]]
    step("C2 列表含两个新夹", "P4c夹A2" in names and "P4c夹B" in names, names)

    # RBAC: 学生看不见 counselor 可见夹、不能建夹、管理不可见夹 404
    r = c.get(f"{BASE}/api/kb/folders", headers=st)
    s_names = [f["name"] for f in r.json()["folders"]]
    step("C2 学生列表不含 counselor 可见夹", "P4c夹A2" not in s_names and "P4c夹B" not in s_names, s_names)
    r = c.post(f"{BASE}/api/kb/folders", headers=st, json={"name": "学生夹"})
    step("C2 学生建夹 → 403", r.status_code == 403, r.status_code)
    r = c.patch(f"{BASE}/api/kb/folders/{fa}", headers=st, json={"name": "x"})
    # 管理端点先撞角色闸(403, 与 P4a permission_api 惯例一致);读路径才是「不可见=不存在」404
    step("C2 学生改夹 → 403(角色闸优先)", r.status_code == 403, r.status_code)

    # ---------- 移动与 audience 标注(C2/C5) ----------
    target = next(d for d in base_docs if d["title"].startswith("关于西南交通大学2016年度"))
    did = target["id"]
    r = c.patch(f"{BASE}/api/kb/documents/{did}", headers=co, json={"folder_id": fa})
    step("C2 单条移动进夹", r.status_code == 200, r.text[:120])
    in_folder = c.get(f"{BASE}/api/kb/documents?folder_id={fa}", headers=co).json()["documents"]
    step("C2 夹内列表含该文档", any(x["id"] == did for x in in_folder) and len(in_folder) == 1,
         [x["title"] for x in in_folder])
    r = c.patch(f"{BASE}/api/kb/documents/{did}", headers=co, json={"audience": "postgrad"})
    step("C5 标注学段 postgrad", r.status_code == 200, r.text[:120])
    pg = c.get(f"{BASE}/api/kb/documents?audience=postgrad", headers=co).json()["documents"]
    ug = c.get(f"{BASE}/api/kb/documents?audience=undergrad", headers=co).json()["documents"]
    step("C5 audience 筛选生效", any(x["id"] == did for x in pg) and not any(x["id"] == did for x in ug),
         f"pg={len(pg)} ug={len(ug)}")
    c.patch(f"{BASE}/api/kb/documents/{did}", headers=co, json={"audience": "common"})
    r = c.post(f"{BASE}/api/kb/documents/move", headers=co,
               json={"doc_ids": [did, base_docs[1]["id"]], "folder_id": fa})
    step("C2 批量移动", r.status_code == 200 and r.json()["moved"] == 2, r.text[:120])
    r = c.delete(f"{BASE}/api/kb/folders/{fa}", headers=co)
    step("C2 非空删除 → 409+hint", r.status_code == 409 and "cascade" in json.dumps(r.json(), ensure_ascii=False),
         r.text[:200])
    r = c.delete(f"{BASE}/api/kb/folders/{fa}", headers=co, params={"cascade": "true"})
    step("C2 级联删除(文档移回根,不删文档)", r.status_code == 200 and
         r.json()["docs_moved_to_root"] >= 2, r.text[:160])
    still = c.get(f"{BASE}/api/kb/documents/{did}/chunks", headers=co)
    step("C2 级联后文档仍在(移回根)", still.status_code == 200 and
         still.json()["document"]["folder_id"] is None, still.json().get("document", {}).get("folder_id"))

    # ---------- C3/C4 检索 scope(上传专用文档,结束自清理) ----------
    unique = ("蟹黄堡秘制配方编号97531号，仅限本验证文档使用，不含任何真实校规内容。"
          "本段为检索范围验证填充：知识点必须落在被指定的文件夹内，指定该夹后来源应全部来自本夹，"
          "未指定时属于全库对照列。补充说明：配方编号、保管责任、查阅流程均为合成描述，"
          "与学校任何真实规定无关，验证完成后整篇删除。") * 5
    doc_text = ("# P4c 检索范围验证文档\n\n" + unique +
                "\n本文档用于验证 @ 指定检索范围：指定本夹后，来源必须全部来自本夹；"
                "未指定时不保证。内容与学校真实政策无关，验证完成后即删除。")
    r = c.post(f"{BASE}/api/kb/folders", headers=co, json={"name": "P4c检索夹", "visibility": "student"})
    fscope = r.json()["folder_id"]
    r = c.post(f"{BASE}/api/kb/upload", headers=co,
               files={"file": ("p4c-scope-验证文档.md", doc_text.encode(), "text/markdown")},
               data={"role_min": "student", "category": "其他", "folder_id": str(fscope),
                     "audience": "common"})
    step("C3 上传文档入指定夹", r.status_code == 200, r.text[:160])
    up_doc = r.json()["doc_id"]
    q = "蟹黄堡秘制配方编号97531号是什么内容？"

    # C4: 请求体 question 与 scope 分离(证据=实际发送体;服务端 200 即接受了无 @ 问句)
    body_sent = {"question": q, "scope": {"folder_ids": [fscope]}}
    t0 = time.time()
    r = c.post(f"{BASE}/api/chat", headers=co, json=body_sent)
    step("C4 分离传参请求被接受(200)", r.status_code == 200, r.text[:160])
    d = r.json()
    step("C4 响应 context.scope 原样回传", (d.get("context") or {}).get("scope", {}).get("folder_ids") == [fscope],
         d.get("context"))
    step("C3 来源全属该夹", bool(d.get("sources")) and
         all(s["title"] == "p4c-scope-验证文档" for s in d["sources"]),
         [s["title"] for s in d.get("sources", [])])
    r_noscope = c.post(f"{BASE}/api/chat", headers=co, json={"question": q})
    step("C3 全库对照有来源(基线对照列)", bool(r_noscope.json().get("sources")),
         len(r_noscope.json().get("sources", [])))
    r = c.post(f"{BASE}/api/chat", headers=co, json={"question": "@" + q,
                                                     "scope": {"folder_ids": [fscope]}})
    step("C4 服务端拒绝 @ 开头问句 → 400", r.status_code == 400, r.status_code)

    # C3 越权与不存在同表现: counselor 建私夹, student 指定它 → 404; 999999 → 404 同文案
    fpriv = c.post(f"{BASE}/api/kb/folders", headers=co, json={"name": "P4c私夹", "visibility": "private"}).json()["folder_id"]
    r1 = c.post(f"{BASE}/api/chat", headers=st, json={"question": q, "scope": {"folder_ids": [fpriv]}})
    r2 = c.post(f"{BASE}/api/chat", headers=st, json={"question": q, "scope": {"folder_ids": [999999]}})
    step("C3 越权夹与不存在夹同表现 404", r1.status_code == 404 and r2.status_code == 404
         and r1.json() == r2.json(), f"{r1.status_code}/{r2.status_code} {r1.text[:80]!r} vs {r2.text[:80]!r}")

    # 硬约束 3: 空库 → 明确提示, 绝不回落全库
    fempty = c.post(f"{BASE}/api/kb/folders", headers=st if False else co,
                    json={"name": "P4c空夹", "visibility": "student"}).json()["folder_id"]
    r = c.post(f"{BASE}/api/chat", headers=co,
               json={"question": "国家奖学金的评定条件是什么？", "scope": {"folder_ids": [fempty]}})
    d = r.json()
    step("硬约束3 空库 → 明确提示且零来源(不回落全库)",
         r.status_code == 200 and d.get("sources") == [] and "未做全库检索" in d.get("answer", "")
         and (d.get("context") or {}).get("scope_empty") is True, r.text[:200])

    # ---------- C5 F3 学段追问(需成对标注) ----------
    pair_text = ("# 荣誉称号评定办法(P4c 学段验证)\n\n本科生荣誉称号评定：竢实扬华奖章面向本科生评选，"
                 "按学年综合成绩排序产生，本段为验证用合成内容，与真实文件无关。" * 3)
    r = c.post(f"{BASE}/api/kb/upload", headers=co,
               files={"file": ("P4c-荣誉称号-本科生办法.md", pair_text.encode(), "text/markdown")},
               data={"role_min": "student", "category": "其他", "audience": "undergrad",
                     "folder_id": str(fscope)})
    ug_doc = r.json().get("doc_id")
    grad_text = ("# 荣誉称号评定办法(研究生)(P4c 学段验证)\n\n研究生荣誉称号评定：优秀研究生标兵面向"
                 "研究生评选，按学业与科研综合评定，本段为验证用合成内容，与真实文件无关。" * 3)
    r = c.post(f"{BASE}/api/kb/upload", headers=co,
               files={"file": ("P4c-荣誉称号-研究生办法.md", grad_text.encode(), "text/markdown")},
               data={"role_min": "student", "category": "其他", "audience": "postgrad",
                     "folder_id": str(fscope)})
    pg_doc = r.json().get("doc_id")
    step("C5 上传本/研成对标注材料", bool(ug_doc) and bool(pg_doc), f"{ug_doc}/{pg_doc}")
    r = c.post(f"{BASE}/api/chat", headers=co, json={"question": "荣誉称号可以同时拿两个吗？"})
    d = r.json()
    step("C5 学段敏感+无学段词 → 追问(不猜)",
         (d.get("clarify") or {}).get("type") == "audience" and "本科生" in d.get("answer", "")
         and d.get("sources") == [], r.text[:200])
    r = c.post(f"{BASE}/api/chat", headers=co,
               json={"question": "荣誉称号可以同时拿两个吗？", "audience_hint": "postgrad"})
    d = r.json()
    step("C5 带 audience_hint → 抑制追问并正常作答(不再追问学段)",
         not d.get("clarify") and bool(d.get("sources")), [s["title"] for s in d.get("sources", [])])

    # ---------- 清理(恢复 65 篇与空夹状态) ----------
    for didx in (up_doc, ug_doc, pg_doc):
        if didx:
            c.delete(f"{BASE}/api/kb/documents/{didx}", headers=co)
    for f in c.get(f"{BASE}/api/kb/folders", headers=co).json()["folders"]:
        if f["name"].startswith("P4c"):
            c.delete(f"{BASE}/api/kb/folders/{f['id']}", headers=co, params={"cascade": "true"})
    n_after = len(c.get(f"{BASE}/api/kb/documents", headers=co).json()["documents"])
    folders_after = c.get(f"{BASE}/api/kb/folders", headers=co).json()["folders"]
    step("清理: documents 守恒", n_after == n_base, f"{n_base}→{n_after}")
    step("清理: 文件夹全部移除", all(not f["name"].startswith("P4c") for f in folders_after),
         [f["name"] for f in folders_after])

    (OUT).write_text(json.dumps({
        "base": BASE, "elapsed_s": round(time.time() - t0, 1),
        "documents_before": n_base, "documents_after": n_after,
        "c4_request_body_sent": body_sent,
        "steps": steps, "all_pass": ok_all,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n{'ALL PASS' if ok_all else 'HAS FAILURES'} → {OUT}")
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
