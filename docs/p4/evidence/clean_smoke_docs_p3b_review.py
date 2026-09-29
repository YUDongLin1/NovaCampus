#!/usr/bin/env python3
"""Review P3b 期间的运行时清理:删除 Zcode 跑 novaagent smoke 造成的 4 篇污染文档,回到 65 基线。
只删本轮新增的 smoke 产物(id>115 且标题/文件名命中已知测试模式),不动任何真实语料。"""
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
TEST_TITLES = {"学籍管理规定-测试", "学籍管理规定-学生版", "分类测试-运维手册", "智枢 Agent · NovaCampus"}

conn = sqlite3.connect(str(DB))
conn.row_factory = sqlite3.Row
rows = conn.execute("SELECT id,title,filename,role_min FROM documents WHERE id>115 ORDER BY id").fetchall()
targets = [r for r in rows if r["title"] in TEST_TITLES]

print("id>115 的文档:", [(r["id"], r["title"]) for r in rows])
print("命中清理集:", [(r["id"], r["title"]) for r in targets])

if len(targets) != 4:
    print("[FAIL] 命中 %d 篇,期望 4 —— 硬停,不删" % len(targets))
    sys.exit(1)
if any(r["id"] <= 115 for r in targets):
    print("[FAIL] 清理集越界到既有语料 —— 硬停")
    sys.exit(1)

bak = DB.with_name(DB.name + ".bak-reviewP3b-" + datetime.now().strftime("%H%M%S"))
shutil.copy2(DB, bak)
print("[OK] 备份 ->", bak.name)

ids = [r["id"] for r in targets]
q = ",".join("?" * len(ids))
conn.execute("DELETE FROM chunks WHERE doc_id IN (%s)" % q, ids)
conn.execute("DELETE FROM documents WHERE id IN (%s)" % q, ids)
conn.commit()
conn.execute("INSERT INTO chunks_fts(chunks_fts) VALUES('rebuild')")
conn.commit()

docs = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
chks = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
fts = conn.execute("SELECT COUNT(*) FROM chunks_fts").fetchone()[0]
orphan = conn.execute("SELECT COUNT(*) FROM chunks c LEFT JOIN documents d ON d.id=c.doc_id WHERE d.id IS NULL").fetchone()[0]
cred = conn.execute("SELECT COUNT(*) FROM chunks WHERE content LIKE '%admin/admin123%' OR content LIKE '%密码均为%'").fetchone()[0]
dup = conn.execute("SELECT COUNT(*) FROM (SELECT title FROM documents GROUP BY title HAVING COUNT(*)>1)").fetchone()[0]

print("[%s] documents=%d chunks=%d chunks_fts=%d 孤儿=%d 重复标题=%d 含口令分块=%d"
      % ("PASS" if (docs == 65 and orphan == 0 and fts == chks and cred == 0 and dup == 0) else "FAIL",
         docs, chks, fts, orphan, dup, cred))
sys.exit(0 if (docs == 65 and orphan == 0 and fts == chks and cred == 0) else 2)
