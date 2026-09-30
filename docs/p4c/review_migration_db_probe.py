#!/usr/bin/env python3
"""P4c 合并前把关:把回执里"探针在 .tmp 跑完就没了"的两组数字补成**可入库、可复跑**的产物。

  M1 迁移(C1 声称"副本库 8/8"):在 agent.db 的**副本**上启动 db.py 迁移两次,断言
     documents/chunks 守恒、folder_id 全 NULL、audience 全 common、两次 schema 一致、
     folders 表存在、迁移幂等(不 UPDATE 既有行)。
  M2 db 层 scope(C3 声称"db 层 9/9"):直接调 db.all_chunks_for_search 与 db.fts_search,
     断言 scope 只收窄不放宽、folder_ids==[] 直接空、audience 对全 common 库无操作、
     FTS 层同步收窄、越权文档不因入夹而对低角色可见。

只读生产库(拷到 TEMP 再迁移),绝不改 novaagent/data/agent.db。

用法:NO_PROXY="127.0.0.1,localhost" novaagent/.venv/Scripts/python.exe -X utf8 docs/p4c/review_migration_db_probe.py
"""
import io
import json
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(r"E:\AILearn\NovaCampus")
OUT = ROOT / "docs" / "p4c" / "evidence" / "after" / "review_migration_db_probe.json"
SRC_DB = ROOT / "novaagent" / "data" / "agent.db"

results = []


def check(name, ok, detail=""):
    results.append({"check": name, "pass": bool(ok), "detail": str(detail)[:200]})
    print("%-4s %s | %s" % ("[OK]" if ok else "[FAIL]", name, str(detail)[:110]))


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    tmp = Path(tempfile.mkdtemp(prefix="p4c_review_"))
    dbcopy = tmp / "agent.db"
    shutil.copy2(SRC_DB, dbcopy)
    # 连 WAL  side-car 一起拷,避免副本处于未合并日志状态
    for suf in ("-wal", "-shm"):
        p = Path(str(SRC_DB) + suf)
        if p.exists():
            shutil.copy2(p, Path(str(dbcopy) + suf))

    with sqlite3.connect(dbcopy) as c:
        before = dict(docs=c.execute("select count(*) from documents").fetchone()[0],
                      chunks=c.execute("select count(*) from chunks").fetchone()[0])
    print("[副本库] 迁移前:", before)

    # ---- M1:迁移跑三次(db.connect 首次即迁移,再手动 _migrate 两次坐实幂等) ----
    os.environ["NOVA_DATA_DIR"] = str(tmp)
    sys.path.insert(0, str(ROOT / "novaagent"))
    from novaagent import db  # noqa: E402

    def snap():
        with sqlite3.connect(dbcopy) as c:
            cols = [r[1] for r in c.execute("PRAGMA table_info(documents)")]
            tables = [r[0] for r in c.execute("select name from sqlite_master where type='table'")]
            return dict(
                docs=c.execute("select count(*) from documents").fetchone()[0],
                chunks=c.execute("select count(*) from chunks").fetchone()[0],
                folders_exist="folders" in tables,
                folder_id_col="folder_id" in cols,
                audience_col="audience" in cols,
                null_folder=c.execute("select count(*) from documents where folder_id is null").fetchone()[0],
                audience_common=c.execute("select count(*) from documents where audience='common'").fetchone()[0],
                cols=tuple(cols))

    db.connect()              # 首次连接即跑 P4c 幂等迁移
    s1 = snap()
    db._migrate()             # 第二次启动
    s2 = snap()
    db._migrate()             # 第三次,坐实幂等
    s3 = snap()

    check("M1-1 documents 守恒", s1["docs"] == before["docs"] == s3["docs"], "%s→%s" % (before["docs"], s3["docs"]))
    check("M1-2 chunks 守恒", s1["chunks"] == before["chunks"] == s3["chunks"], "%s→%s" % (before["chunks"], s3["chunks"]))
    check("M1-3 folders 表已建", s1["folders_exist"], s1["folders_exist"])
    check("M1-4 folder_id 列已加", s1["folder_id_col"], s1["folder_id_col"])
    check("M1-5 audience 列已加", s1["audience_col"], s1["audience_col"])
    check("M1-6 存量文档 folder_id 全 NULL(不 UPDATE 既有行)",
          s1["null_folder"] == s1["docs"], "%d/%d" % (s1["null_folder"], s1["docs"]))
    check("M1-7 存量 audience 全 common", s1["audience_common"] == s1["docs"], "%d/%d" % (s1["audience_common"], s1["docs"]))
    check("M1-8 三次启动 schema 与计数完全一致(幂等)", s1 == s2 == s3, "s1==s2==s3: %s" % (s1 == s2 == s3))

    # ---- M2:db 层 scope 语义(用副本库现造数据) ----
    conn = db._conn
    fid_a = db.create_folder("REVIEW-夹A", None, 2, "counselor")
    fid_b = db.create_folder("REVIEW-夹B", None, 2, "counselor")
    # 把两类文档分别挂进夹
    docs_a = [r[0] for r in conn.execute("select id from documents where role_min='student' limit 2")]
    docs_b = [r[0] for r in conn.execute("select id from documents where role_min='counselor' limit 2")]
    db.move_documents(docs_a, fid_a)
    db.move_documents(docs_b, fid_b)
    conn.execute("UPDATE documents SET audience='postgrad' WHERE id=?", (docs_a[0],))
    conn.commit()

    all_stu = db.all_chunks_for_search(1)                       # rank=student
    in_a = db.all_chunks_for_search(1, folder_ids=[fid_a])
    empty = db.all_chunks_for_search(1, folder_ids=[])
    # 并集要用 counselor 角色(rank=2):docs_b 是 counselor 文档,用 rank=1 会被 RBAC 先排除,
    # 那样根本测不到"并集"(第一版断言用 rank=1 得到 [5,8],被我误判成 FAIL)
    both = db.all_chunks_for_search(2, folder_ids=[fid_a, fid_b])
    both_stu = db.all_chunks_for_search(1, folder_ids=[fid_a, fid_b])
    aud_pg = db.all_chunks_for_search(1, audience="postgrad")
    cat = db.all_chunks_for_search(1, categories=["学生事务"])
    doc_ids_a = {r["doc_id"] for r in in_a}
    doc_ids_both = {r["doc_id"] for r in both}
    check("M2-1 无 scope 时候选=全库可见块(形状不变)", len(in_a) < len(all_stu) and len(all_stu) > 0,
          "全库 %d 块 / 夹A %d 块" % (len(all_stu), len(in_a)))
    check("M2-2 指定夹后候选只含该夹文档", doc_ids_a == set(docs_a), "%s ⊆ %s" % (sorted(doc_ids_a), sorted(docs_a)))
    check("M2-3 folder_ids==[] 直接返回空(绝不回落全库)", empty == [], "len=%d" % len(empty))
    check("M2-4 多夹取并集(counselor 视角两夹都可见)", doc_ids_both == set(docs_a) | set(docs_b),
          "%s vs 期望 %s" % (sorted(doc_ids_both), sorted(set(docs_a) | set(docs_b))))
    check("M2-4b 并集在 student 视角仍被 RBAC 收窄(只剩学生可见夹A)",
          {r["doc_id"] for r in both_stu} == set(docs_a), sorted({r["doc_id"] for r in both_stu}))
    check("M2-5 audience 只收窄不放宽", len(aud_pg) <= len(all_stu) and len(aud_pg) > 0,
          "postgrad %d / 全库 %d" % (len(aud_pg), len(all_stu)))
    check("M2-6 audience 恒放行 common(未标注不误杀)",
          len(db.all_chunks_for_search(1, audience="undergrad")) > 0,
          "undergrad 仍可见 common 块 %d" % len(db.all_chunks_for_search(1, audience="undergrad")))
    # categories 收窄:用夹A 文档的**真实分类**来筛,否则命中 0 块会"空集子集"假通过
    cat_a = conn.execute("select category from documents where id=?", (docs_a[0],)).fetchone()[0] or "其他"
    cat = db.all_chunks_for_search(1, categories=[cat_a])
    cat_docs = {r[0] for r in conn.execute("select id from documents where category=?", (cat_a,)).fetchall()}
    check("M2-7 categories 收窄生效且非空",
          len(cat) > 0 and {r["doc_id"] for r in cat} <= cat_docs,
          "分类「%s」→ %d 块,文档集合 ⊆ 该分类 %d 篇" % (cat_a, len(cat), len(cat_docs)))
    # 越权提权检查:student 角色看 counselor-only 文档(即使在 student 可见夹里)
    db.update_folder(fid_b, visibility="student")           # 把含 counselor 文档的夹设为 student 可见
    stu_view = db.all_chunks_for_search(1, folder_ids=[fid_b])
    check("M2-8 文件夹可见性不得放宽文档 role_min(不提权)", stu_view == [],
          "student 看含 counselor 文档的 student 夹 → %d 块" % len(stu_view))
    # FTS 下推验证:fts_search 把整个查询当**引号短语**匹配,trigram 分词下不足 3 字直接返回
    # None(文档写明)。第一版我用"学生"(2 字)和夹A里根本不存在的"休学",两次都是我的词不对。
    a_content = conn.execute("select content from chunks where doc_id=?", (docs_a[0],)).fetchone()[0]
    term = next((w for w in ("学平险", "保险费", "大学生", "研究生", "通知") if w in a_content), None)
    if term is None:                      # 兜底:取正文里连续的 3 字片段
        clean = "".join(ch for ch in a_content if "\u4e00" <= ch <= "\u9fff")
        term = clean[:3] if len(clean) >= 3 else None
    a_chunk_ids = {r["id"] for r in in_a}
    fts_a = db.fts_search(term, ["student", "counselor"], 20, folder_ids=[fid_a]) or []
    fts_b = db.fts_search(term, ["student", "counselor"], 20, folder_ids=[fid_b]) or []
    fts_all = db.fts_search(term, ["student", "counselor"], 20) or []
    ok_fts = (len(fts_all) > 0 and all(cid in a_chunk_ids for cid, _ in fts_a)
              and all(cid not in a_chunk_ids for cid, _ in fts_b))
    check("M2-9 FTS 层同步下推 scope(命中集真被过滤,不是忽略 scope)", ok_fts,
          "词「%s」: 全库=%d scoped夹A=%d(全在夹A内=%s) scoped夹B=%d(含夹A块=0)"
          % (term, len(fts_all), len(fts_a),
             all(cid in a_chunk_ids for cid, _ in fts_a), len(fts_b)))

    n_m1 = sum(1 for r in results if r["check"].startswith("M1"))
    n_m1_ok = sum(1 for r in results if r["check"].startswith("M1") and r["pass"])
    n_m2 = sum(1 for r in results if r["check"].startswith("M2"))
    n_m2_ok = sum(1 for r in results if r["check"].startswith("M2") and r["pass"])
    json.dump({"before": before, "snapshots": [{k: v for k, v in s.items() if k != "cols"} for s in (s1, s2, s3)],
               "checks": results, "pass": all(r["pass"] for r in results),
               "counts": {"m1": "%d/%d" % (n_m1_ok, n_m1), "m2": "%d/%d" % (n_m2_ok, n_m2)}},
              io.open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    n_ok = sum(1 for r in results if r["pass"])
    print("\n[SUM] %d/%d 通过 | 证据 %s" % (n_ok, len(results), OUT))
    shutil.rmtree(tmp, ignore_errors=True)
    sys.exit(0 if n_ok == len(results) else 1)


if __name__ == "__main__":
    main()
