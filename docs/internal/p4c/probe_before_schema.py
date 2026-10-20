#!/usr/bin/env python3
"""P4c 第 0 步 BEFORE 取证(1):schema 现状 + 检索函数签名现状

产出(只读,不改库):
  docs/p4c/evidence/before/db_schema.txt       documents 全列 / folders 不存在 / 计数守恒基线
  docs/p4c/evidence/before/search_signatures.txt  rag.search / rag.search_with_quality /
                                                  db.all_chunks_for_search 的当前签名与行号
坑 33: 断言取到非空才落盘(计数 > 0、列数 > 0);坑 5: 不用 emoji,纯文本标记
"""
from __future__ import annotations

import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
EVID = ROOT / "docs" / "p4c" / "evidence" / "before"
DB = ROOT / "novaagent" / "data" / "agent.db"
RAG = ROOT / "novaagent" / "novaagent" / "rag.py"
DBP = ROOT / "novaagent" / "novaagent" / "db.py"

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
EVID.mkdir(parents=True, exist_ok=True)

# ---------- 1) schema ----------
con = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True)
con.row_factory = sqlite3.Row
cols = [dict(r) for r in con.execute("PRAGMA table_info(documents)")]
tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
n_docs = con.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
n_chunks = con.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
by_cat = dict(con.execute("SELECT category, COUNT(*) c FROM documents GROUP BY category ORDER BY c DESC").fetchall())
by_role = dict(con.execute("SELECT role_min, COUNT(*) c FROM documents GROUP BY role_min").fetchall())
con.close()

names = [c["name"] for c in cols]
assert cols, "documents 列为空——不该发生"
assert n_docs > 0 and n_chunks > 0, f"计数为空: documents={n_docs} chunks={n_chunks}"

lines = [
    "P4c BEFORE 基线 (1): schema 现状",
    f"取证时间: 2026-09-30 (P4c 开工前, master={_m if (_m := '0499a89') else ''})",
    f"数据库: {DB}",
    "",
    "== documents 全列 (PRAGMA table_info) ==",
]
for c in cols:
    lines.append(f"  {c['cid']:>2} {c['name']:<14} {c['type']:<8} notnull={c['notnull']} default={c['dflt_value']}")
lines += [
    "",
    f"列清单: {names}",
    f"实测: 'folder_id' in columns = {'folder_id' in names}   <-- 应为 False",
    f"实测: 'audience'  in columns = {'audience' in names}   <-- 应为 False",
    "",
    "== 全部表名 ==",
    f"  {tables}",
    f"实测: 'folders' 表存在 = {'folders' in tables}   <-- 应为 False",
    "",
    "== 计数守恒基线 (本单迁移后必须与此相等) ==",
    f"  documents = {n_docs}",
    f"  chunks    = {n_chunks}",
    "",
    "== 分布(供 scope 用例挑库) ==",
    f"  按 category: {by_cat}",
    f"  按 role_min: {by_role}",
]
(EVID / "db_schema.txt").write_text("\n".join(lines), encoding="utf-8")

# ---------- 2) 检索函数签名 ----------
def sig(path: Path, pattern: str) -> list[str]:
    out = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        m = re.match(pattern, line)
        if m:
            out.append(f"  {path.name}:{i}: {line.strip()}")
    return out

targets = [
    ("rag.py", r"^async def search\(|^def search\(|^async def search_with_quality\("),
    ("db.py", r"^def all_chunks_for_search\("),
]
blocks = []
blocks.append("P4c BEFORE 基线 (2): 检索链路当前签名(本单要给它们加 scope)")
blocks.append("")
blocks.append("== rag.py ==")
blocks += sig(RAG, targets[0][1]) or ["  (未匹配到——需人工核对)"]
blocks.append("")
blocks.append("== db.py ==")
blocks += sig(DBP, targets[1][1]) or ["  (未匹配到——需人工核对)"]
blocks.append("")
blocks.append("注: RBAC 过滤发生在取候选块阶段(db.all_chunks_for_search 的 role_min IN (...)),")
blocks.append("    scope 只能在其之上再加约束取交集(见 P4c 硬约束 1)。")
(EVID / "search_signatures.txt").write_text("\n".join(blocks), encoding="utf-8")

print("[OK] db_schema.txt / search_signatures.txt 已落盘")
print(f"     documents={n_docs} chunks={n_chunks} folder_id={'folder_id' in names} "
      f"audience={'audience' in names} folders={'folders' in tables}")
