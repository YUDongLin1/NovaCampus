#!/usr/bin/env python3
"""P4e M-B:迁移幂等性探针——`web_search_enabled` 列在**库副本**上跑两遍结果一致。

纪律(HANDOFF):agent.db 不得被脚本改动;迁移只写进 `db.py` 启动期 `_migrate()`(幂等),
并在**库副本**上验证跑两遍结果一致。

断言:
  D1 副本上首次连接后 user_settings 含 web_search_enabled 列
  D2 **再连一次**(第二次 _migrate)后 schema 与数据逐字段不变 → 幂等
  D3 老用户默认 ''(= 未设置 → 回落全局默认「关」),不误开
  D4 set/get 往返:True→"1"、False→"0"、None/''→""
  D5 只改 web_search_enabled 时,model/custom/llm_* 等既有字段**不被冲掉**
退出码:0 = 全过;1 = 有 FAIL。
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError, OSError):
    pass

_TMP = Path(tempfile.mkdtemp(prefix="nova_migrate_")) / "novaagent" / "data"
_TMP.mkdir(parents=True, exist_ok=True)
_SRC = ROOT / "novaagent" / "data" / "agent.db"
if _SRC.exists():
    shutil.copy2(_SRC, _TMP / "agent.db")
os.environ["NOVA_DATA_DIR"] = str(_TMP)
sys.path.insert(0, str(ROOT / "novaagent"))

import sqlite3  # noqa: E402

from novaagent import db  # noqa: E402

FAILS: list = []


def ck(cond: bool, name: str, detail: str = "") -> None:
    print(f"{'[PASS]' if cond else '[FAIL]'} {name}{(' — ' + detail) if detail else ''}")
    if not cond:
        FAILS.append(name)


def _schema() -> list:
    con = sqlite3.connect(str(_TMP / "agent.db"))
    try:
        return con.execute("PRAGMA table_info(user_settings)").fetchall()
    finally:
        con.close()


def _rows() -> list:
    con = sqlite3.connect(str(_TMP / "agent.db"))
    con.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in con.execute("SELECT * FROM user_settings ORDER BY user_id")]
    finally:
        con.close()


def main() -> int:
    db.connect()                      # 第 1 次 _migrate
    s1 = _schema()
    cols1 = [r[1] for r in s1]
    ck("web_search_enabled" in cols1, "D1 迁移后 user_settings 含 web_search_enabled 列",
       f"cols={cols1}")
    r1 = _rows()

    db.connect()                      # 第 2 次 _migrate(幂等性关键)
    s2 = _schema()
    r2 = _rows()
    ck(s1 == s2, "D2 再跑一次 _migrate:schema 逐字段不变(幂等)",
       f"{len(s1)} vs {len(s2)} 列")
    ck(r1 == r2, "D2b 再跑一次 _migrate:数据逐行不变(幂等)",
       f"{len(r1)} vs {len(r2)} 行")

    uid = r1[0]["user_id"] if r1 else 1
    ck(all(str(x.get("web_search_enabled") or "") == "" for x in r1),
       "D3 既有用户默认 ''(= 未设置 → 回落全局默认「关」),不误开",
       f"值={[x.get('web_search_enabled') for x in r1]}")

    db.set_web_search_enabled(uid, True)
    ck(db.get_web_search_enabled(uid) == "1", "D4 set(True) → '1'",
       f"实得 {db.get_web_search_enabled(uid)!r}")
    db.set_web_search_enabled(uid, False)
    ck(db.get_web_search_enabled(uid) == "0", "D4b set(False) → '0'",
       f"实得 {db.get_web_search_enabled(uid)!r}")
    db.set_web_search_enabled(uid, "")
    ck(db.get_web_search_enabled(uid) == "", "D4c set('') → ''(回到未设置)",
       f"实得 {db.get_web_search_enabled(uid)!r}")

    # ⚠ 排除 updated_at:set_* 本来就会刷新它(不是"被冲掉");只比对业务字段
    before = {k: v for k, v in (r1[0] if r1 else {}).items()
             if k not in ("web_search_enabled", "updated_at")}
    db.set_web_search_enabled(uid, True)
    after_row = next((x for x in _rows() if x["user_id"] == uid), {})
    kept = all(after_row.get(k) == v for k, v in before.items())
    ck(kept, "D5 只改 web_search_enabled:既有字段不被冲掉",
       f"model={after_row.get('model')!r} custom={after_row.get('custom_model')!r}")

    shutil.rmtree(_TMP.parent, ignore_errors=True)
    print(f"\n[migrate] {'ALL PASS' if not FAILS else 'FAIL: ' + ', '.join(FAILS)}")
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(main())
