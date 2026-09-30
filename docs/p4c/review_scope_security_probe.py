#!/usr/bin/env python3
"""P4c 合并前把关:三个硬约束的对抗探针(不采信回执,全部实测)。

  T1 提权路径:把 role_min=counselor 的文档移进 student 可见的文件夹,
     再以 student 身份 scoped 检索 → 绝不该返回它(文件夹可见性不得放宽文档权限)。
  T2 不泄露存在性:student 请求「越权已存在的 folder」与「根本不存在的 folder」
     两者状态码与响应体必须逐字节一致。
  T3 空库不回落:scoped 到一个空文件夹 → 必须是明确提示,且 sources 为空
     (回落全库等于把未授权范围内容答出去)。
  T4 部分越权静默丢弃:[可见 folder, 越权 folder] 一起请求 → 只按可见的检索,不报错。
  T5 scope 真收窄:指定正确 folder 后返回的每个 source 都必须属于该 folder。

    /d/anaconda3/python.exe docs/p4c/review_scope_security_probe.py
"""
import io
import json
import sys
import time

import httpx

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

BASE = "http://127.0.0.1:8900"
OUT = r"E:\AILearn\NovaCampus\docs\p4c\evidence\after\review_scope_security.json"
Q = "研究生申请休学需要提交哪些材料?"
BODY = ("# 研究生休学与复学管理规定(复核探针文档)\n\n"
        "第一条 为规范研究生学籍管理,保障培养质量,依据普通高等学校学生管理规定并结合本校实际,"
        "制定本办法。第二条 研究生因疾病、创业、入伍或其他正当理由无法继续学习的,应当申请休学。"
        "申请休学须提交本人书面申请、二级甲等以上医院出具的诊断证明(因病休学情形),"
        "并经导师签署意见后,由培养单位审核,报研究生院审批。第三条 休学一般以一年为期,"
        "累计不得超过两年。第四条 休学期满应当在期满前一周内提交复学申请,经培养单位复核、"
        "研究生院批准后办理复学手续。第五条 本办法自发布之日起施行,由研究生院负责解释。")


def tok(u, p):
    r = httpx.post(BASE + "/api/login", json={"username": u, "password": p}, timeout=20)
    r.raise_for_status()
    return {"Authorization": "Bearer " + r.json()["token"]}


def ask(H, q, scope=None):
    body = {"question": q}
    if scope is not None:
        body["scope"] = scope
    r = httpx.post(BASE + "/api/chat", json=body, headers=H, timeout=180)
    return r


def main():
    CO, ST, AD = tok("counselor", "counselor123"), tok("student", "student123"), tok("admin", "admin123")
    res = {}
    made_folders, made_docs = [], []

    # 造材料:admin 上传一篇 counselor 专属文档,建一个 student 可见文件夹
    up = httpx.post(BASE + "/api/kb/upload", headers=AD,
                    files={"file": ("P4C-REVIEW-提权探针.md", BODY.encode("utf-8"), "text/markdown")},
                    data={"role_min": "counselor", "category": "学生事务"}, timeout=60)
    up.raise_for_status()
    doc_id = up.json()["doc_id"]
    made_docs.append(doc_id)
    fid = httpx.post(BASE + "/api/kb/folders", json={"name": "REVIEW-学生可见夹", "visibility": "student"},
                     headers=AD, timeout=30).json()["folder_id"]
    made_folders.append(fid)

    # T1 提权路径
    mv = httpx.post(BASE + "/api/kb/documents/move", json={"doc_ids": [doc_id], "folder_id": fid},
                    headers=AD, timeout=30)
    t1 = {"move_status": mv.status_code}
    r_student = ask(ST, Q, {"folder_ids": [fid]})
    r_counselor = ask(CO, Q, {"folder_ids": [fid]})
    st_titles = [s.get("title") for s in (r_student.json().get("sources") or [])] if r_student.status_code == 200 else []
    t1.update({"student_status": r_student.status_code, "student_sources": st_titles,
               "leaked": any("P4C-REVIEW" in (t or "") for t in st_titles),
               "counselor_sources": [s.get("title") for s in (r_counselor.json().get("sources") or [])]})
    res["T1_privilege_escalation"] = t1
    print("[T1] 提权: 学生 scoped 到含 counselor 文档的可见夹 → 状态 %s, 是否泄露=%s"
          % (r_student.status_code, t1["leaked"]))

    # T2 不泄露存在性:先造一个 student 不可见的 private 夹(admin 拥有、visibility=private)
    priv_fid = httpx.post(BASE + "/api/kb/folders", json={"name": "REVIEW-私有夹", "visibility": "private"},
                          headers=AD, timeout=30).json()["folder_id"]
    made_folders.append(priv_fid)
    allf = httpx.get(BASE + "/api/kb/folders", headers=AD, timeout=30).json()["folders"]
    vis_st = {f["id"] for f in httpx.get(BASE + "/api/kb/folders", headers=ST, timeout=30).json()["folders"]}
    hidden = [f for f in allf if f["id"] not in vis_st]
    if hidden:
        hid = hidden[0]["id"]
        a = ask(ST, Q, {"folder_ids": [hid]})
        b = ask(ST, Q, {"folder_ids": [999999]})
        res["T2_existence_leak"] = {"hidden_folder": hid, "hidden_status": a.status_code,
                                    "nonexistent_status": b.status_code,
                                    "hidden_body": a.text[:160], "nonexistent_body": b.text[:160],
                                    "identical": a.status_code == b.status_code and a.text == b.text}
        print("[T2] 越权夹 %s vs 不存在夹: %s/%s 响应体一致=%s"
              % (hid, a.status_code, b.status_code, res["T2_existence_leak"]["identical"]))
    else:
        res["T2_existence_leak"] = {"skipped": "没有 student 不可见的文件夹可测"}
        print("[T2] 跳过:无越权 folder")

    # T3 空库不回落
    empty_fid = httpx.post(BASE + "/api/kb/folders", json={"name": "REVIEW-空夹", "visibility": "counselor"},
                           headers=CO, timeout=30).json()["folder_id"]
    made_folders.append(empty_fid)
    e = ask(CO, Q, {"folder_ids": [empty_fid]})
    ej = e.json() if e.status_code == 200 else {}
    res["T3_empty_no_fallback"] = {"status": e.status_code, "n_sources": len(ej.get("sources") or []),
                                   "answer_head": (ej.get("answer") or "")[:200],
                                   "fell_back_to_full_kb": len(ej.get("sources") or []) > 0,
                                   "context": ej.get("context")}
    print("[T3] scoped 空夹: 状态 %s, sources=%d (回落全库=%s)"
          % (e.status_code, res["T3_empty_no_fallback"]["n_sources"],
             res["T3_empty_no_fallback"]["fell_back_to_full_kb"]))

    # T4 部分越权静默丢弃
    if hidden:
        p = ask(CO, Q, {"folder_ids": [fid, 999999]})
        res["T4_partial_invisible"] = {"status": p.status_code,
                                       "n_sources": len((p.json().get("sources") or [])) if p.status_code == 200 else None,
                                       "echoed_scope": (p.json().get("context") or {}).get("scope") if p.status_code == 200 else None}
        print("[T4] [可见夹, 不存在夹] 一起请求: 状态 %s, sources=%s" % (p.status_code, res["T4_partial_invisible"]["n_sources"]))

    # T5 scope 真收窄:admin 建夹放 2 篇专属文档,scoped 检索的每个 source 都须属于该夹
    f5 = httpx.post(BASE + "/api/kb/folders", json={"name": "REVIEW-窄夹", "visibility": "counselor"},
                    headers=AD, timeout=30).json()["folder_id"]
    made_folders.append(f5)
    ids = []
    for i in range(2):
        r = httpx.post(BASE + "/api/kb/upload", headers=AD,
                       files={"file": ("P4C-窄夹%d.md" % i,
                                       ("# 窄夹文档%d 研究生休学与复学管理规定\n\n" % i + BODY).encode("utf-8"),
                                       "text/markdown")},
                       data={"role_min": "counselor", "category": "学生事务"}, timeout=60)
        ids.append(r.json()["doc_id"])
        made_docs.append(ids[-1])
    httpx.post(BASE + "/api/kb/documents/move", json={"doc_ids": ids, "folder_id": f5}, headers=AD, timeout=30)
    time.sleep(1.0)
    q5 = ask(CO, "休学需要提交书面申请与导师意见", {"folder_ids": [f5]})
    srcs = q5.json().get("sources") or []
    titles = {s.get("title") for s in srcs}
    res["T5_narrowed"] = {"status": q5.status_code, "n_sources": len(srcs), "titles": sorted(titles),
                          "all_within_scope": all("窄夹" in (t or "") for t in titles) if srcs else None}
    print("[T5] scoped 窄夹: sources=%d 全部属于该夹=%s 标题=%s"
          % (len(srcs), res["T5_narrowed"]["all_within_scope"], sorted(titles)))

    # 清理本次造的材料
    for d in made_docs:
        httpx.delete(BASE + "/api/kb/documents/%d" % d, headers=AD, timeout=30)
    for f in made_folders:
        httpx.delete(BASE + "/api/kb/folders/%d" % f, params={"cascade": "true"},
                     headers=AD, timeout=30)
    kb = httpx.get(BASE + "/api/kb/documents", headers=AD, timeout=30).json()
    res["cleanup"] = {"folders_deleted": len(made_folders), "docs_deleted": len(made_docs),
                      "documents_after": len(kb["documents"])}
    print("\n[CLEAN] 删测试文档 %d 篇、文件夹 %d 个;KB documents=%d"
          % (len(made_docs), len(made_folders), res["cleanup"]["documents_after"]))
    json.dump(res, io.open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    ok = (not t1["leaked"]) and res["T2_existence_leak"].get("identical", True) \
        and not res["T3_empty_no_fallback"]["fell_back_to_full_kb"]
    print("[SUM] %s | 证据 %s" % ("三条硬约束实测全部守住" if ok else "存在未守住的项,见 JSON", OUT))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
