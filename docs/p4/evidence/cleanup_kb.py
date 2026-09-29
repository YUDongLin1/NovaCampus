#!/usr/bin/env python3
"""P4a 前置(用户已授权 2026-09-29):清理 KB 脏数据 17 篇 + 备份 + 重建 FTS

删除对象(逐条列举,断言数量=17,不符即退出非零):
  A. 网页导入脏数据 2 篇:id=109(https://cwc.swjtu.edu.cn/ 登录页,role_min=student)、
     id=22(http://127.0.0.1:8900/ 自家前端首页,正文含演示口令)
  B. smoke_test.py 每次运行重复上传且从不清理的测试残留 15 篇:
     学籍管理规定-测试 ×6、学籍管理规定-学生版 ×6、分类测试-运维手册 ×3
保留:EVAL-* 评测种子(id 8~11)、政策文件 32、学生事务 20、运维手册 2(真手册)。
"""
import io
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError, OSError):
    pass

DB = Path(r"E:\AILearn\NovaCampus\novaagent\data\agent.db")
REPORT = Path(r"E:\AILearn\NovaCampus\.p4_work\cleanup_report.txt")

DIRTY_URLS = ["https://cwc.swjtu.edu.cn/", "http://127.0.0.1:8900/"]
TEST_TITLES = ["学籍管理规定-测试", "学籍管理规定-学生版", "分类测试-运维手册"]
KEEP_PREFIX = "EVAL-"

if not DB.exists():
    print("[FAIL] 数据库不存在:", DB)
    sys.exit(1)

bak = DB.with_name(DB.name + ".bak-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
shutil.copy2(DB, bak)
print("[OK] 已备份 ->", bak.name, "(%d bytes)" % bak.stat().st_size)

conn = sqlite3.connect(str(DB))
conn.row_factory = sqlite3.Row
out = io.open(str(REPORT), "w", encoding="utf-8")


def cnt(sql, args=()):
    return conn.execute(sql, args).fetchone()[0]


before_docs = cnt("SELECT COUNT(*) FROM documents")
before_chunks = cnt("SELECT COUNT(*) FROM chunks")
out.write("清理前: documents=%d chunks=%d messages=%d\n\n" %
          (before_docs, before_chunks, cnt("SELECT COUNT(*) FROM messages")))

ph = ",".join("?" * len(DIRTY_URLS))
rows_a = conn.execute(
    f"SELECT id,title,filename,category,role_min FROM documents WHERE filename IN ({ph})", DIRTY_URLS
).fetchall()
ph2 = ",".join("?" * len(TEST_TITLES))
rows_b = conn.execute(
    f"SELECT id,title,filename,category,role_min FROM documents WHERE title IN ({ph2})", TEST_TITLES
).fetchall()

targets = {r["id"]: dict(r) for r in rows_a}
for r in rows_b:
    targets[r["id"]] = dict(r)

# 安全断言:EVAL-* 种子绝不能进删除集
bad = [d for d in targets.values() if d["title"].startswith(KEEP_PREFIX)]
if bad:
    print("[FAIL] 删除集里出现 EVAL-* 种子,硬停:", bad)
    sys.exit(1)
if len(targets) != 17:
    print("[FAIL] 待删文档数=%d,期望 17 —— 硬停,不执行删除" % len(targets))
    for i, d in sorted(targets.items()):
        print("   ", i, d["title"], d["filename"])
    sys.exit(1)

out.write("[待删 17 篇]\n")
for i in sorted(targets):
    d = targets[i]
    n = cnt("SELECT COUNT(*) FROM chunks WHERE doc_id=?", (i,))
    out.write("  id=%-4s chunks=%-3d role=%-9s cat=%-6s title=%s | filename=%s\n"
              % (i, n, d["role_min"], d["category"], d["title"][:50], d["filename"][:60]))

ids = sorted(targets)
q = ",".join("?" * len(ids))
conn.execute(f"DELETE FROM chunks WHERE doc_id IN ({q})", ids)      # 触发器同步 chunks_fts
conn.execute(f"DELETE FROM documents WHERE id IN ({q})", ids)
conn.commit()
conn.execute("INSERT INTO chunks_fts(chunks_fts) VALUES('rebuild')")  # 幂等重建全文索引
conn.commit()

after_docs = cnt("SELECT COUNT(*) FROM documents")
after_chunks = cnt("SELECT COUNT(*) FROM chunks")
fts_n = cnt("SELECT COUNT(*) FROM chunks_fts")
orphan = cnt("SELECT COUNT(*) FROM chunks c LEFT JOIN documents d ON d.id=c.doc_id WHERE d.id IS NULL")

out.write("\n清理后: documents=%d chunks=%d chunks_fts=%d 孤儿分块=%d\n"
          % (after_docs, after_chunks, fts_n, orphan))
out.write("\n[清理后 category 分布]\n")
for r in conn.execute("SELECT category,COUNT(*) n FROM documents GROUP BY category ORDER BY n DESC"):
    out.write("  %s = %d\n" % (r["category"], r["n"]))
out.write("\n[清理后 role_min 分布]\n")
for r in conn.execute("SELECT role_min,COUNT(*) n FROM documents GROUP BY role_min"):
    out.write("  %s = %d\n" % (r["role_min"], r["n"]))
out.write("\n[清理后关键词覆盖]\n")
for kw in ["医保", "学平险", "校医院", "计财处", "财务处", "保险", "缴费", "荣誉称号", "浏览器", "演示账号"]:
    out.write("  %-8s chunks=%d\n" % (kw, cnt("SELECT COUNT(*) FROM chunks WHERE content LIKE ?", ("%" + kw + "%",))))
out.write("\n[剩余重复标题]\n")
dup = conn.execute("SELECT title,COUNT(*) n FROM documents GROUP BY title HAVING n>1").fetchall()
out.write("  %s\n" % (["%s x%d" % (r["title"], r["n"]) for r in dup] or "无"))
out.close()

ok = (after_docs == before_docs - 17 and orphan == 0 and fts_n == after_chunks)
print("[%s] documents %d -> %d, chunks %d -> %d, chunks_fts=%d, 孤儿=%d"
      % ("PASS" if ok else "FAIL", before_docs, after_docs, before_chunks, after_chunks, fts_n, orphan))
print("[OK] 明细报告 ->", REPORT)
sys.exit(0 if ok else 2)
