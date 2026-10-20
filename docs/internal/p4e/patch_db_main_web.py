#!/usr/bin/env python3
"""P4e M-B:user_settings.web_search_enabled(迁移幂等)+ main.py 两个 chat 端点接开关。

用法: novaagent/.venv/Scripts/python.exe docs/p4e/patch_db_main_web.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "novaagent" / "novaagent" / "db.py"
MAIN = ROOT / "novaagent" / "novaagent" / "main.py"
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError, OSError):
    pass

# ---------------- db.py ----------------
D1_OLD = '''    us_cols = [r["name"] for r in _conn.execute("PRAGMA table_info(user_settings)")]
    with _lock:
        for col in ("custom_model", "llm_base_url", "llm_api_key"):
            if col not in us_cols:
                _conn.execute(f"ALTER TABLE user_settings ADD COLUMN {col} TEXT NOT NULL DEFAULT ''")
        _conn.commit()
'''
D1_NEW = '''    us_cols = [r["name"] for r in _conn.execute("PRAGMA table_info(user_settings)")]
    with _lock:
        # P4e M-B: web_search_enabled —— 用户级联网开关。'' == 未设置过 → 回落全局默认(关)。
        # TEXT 存 "1"/"0"(SQLite 无布尔;且要能区分"未设置"与"显式关",故不用 NOT NULL DEFAULT '0'
        # 之外的写法——未设置时本列即为 '',由 _web_enabled 判为未设置)。
        for col in ("custom_model", "llm_base_url", "llm_api_key", "web_search_enabled"):
            if col not in us_cols:
                _conn.execute(f"ALTER TABLE user_settings ADD COLUMN {col} TEXT NOT NULL DEFAULT ''")
        _conn.commit()
'''

D2_OLD = '''    if row is None:
        return {"model": "", "custom_model": "", "llm_base_url": "", "llm_api_key": ""}
'''
D2_NEW = '''    if row is None:
        return {"model": "", "custom_model": "", "llm_base_url": "", "llm_api_key": "",
                "web_search_enabled": ""}
'''

D3_OLD = '''def set_user_settings(user_id: int, **fields) -> None:
    cur_fields = get_user_settings(user_id)
    cur_fields.update({k: v for k, v in fields.items() if v is not None})
    with _lock:
        _conn.execute(
            """INSERT INTO user_settings (user_id, model, custom_model, llm_base_url, llm_api_key, updated_at)
               VALUES (?,?,?,?,?,?)
               ON CONFLICT(user_id) DO UPDATE SET model=excluded.model, custom_model=excluded.custom_model,
                   llm_base_url=excluded.llm_base_url, llm_api_key=excluded.llm_api_key,
                   updated_at=excluded.updated_at""",
            (user_id, cur_fields["model"], cur_fields["custom_model"],
             cur_fields["llm_base_url"], cur_fields["llm_api_key"], _now()),
        )
        _conn.commit()
'''
D3_NEW = '''def _yn(v) -> str:
    """布尔/字符串 → "1"/"0"(SQLite 无布尔,列存 TEXT)。空串表示「未设置」。"""
    if v is None or v == "":
        return ""
    if isinstance(v, bool):
        return "1" if v else "0"
    s = str(v).strip().lower()
    if s in ("1", "true", "yes", "on"):
        return "1"
    if s in ("0", "false", "no", "off"):
        return "0"
    return ""


def set_user_settings(user_id: int, **fields) -> None:
    cur_fields = get_user_settings(user_id)
    cur_fields.update({k: v for k, v in fields.items() if v is not None})
    with _lock:
        _conn.execute(
            """INSERT INTO user_settings (user_id, model, custom_model, llm_base_url, llm_api_key,
                                         web_search_enabled, updated_at)
               VALUES (?,?,?,?,?,?,?)
               ON CONFLICT(user_id) DO UPDATE SET model=excluded.model, custom_model=excluded.custom_model,
                   llm_base_url=excluded.llm_base_url, llm_api_key=excluded.llm_api_key,
                   web_search_enabled=excluded.web_search_enabled,
                   updated_at=excluded.updated_at""",
            (user_id, cur_fields["model"], cur_fields["custom_model"],
             cur_fields["llm_base_url"], cur_fields["llm_api_key"],
             _yn(cur_fields.get("web_search_enabled")), _now()),
        )
        _conn.commit()


def get_web_search_enabled(user_id: int) -> str:
    """P4e M-B:用户级联网开关原值('' = 未设置过 → 由调用方回落全局默认)。"""
    return str(get_user_settings(user_id).get("web_search_enabled") or "")


def set_web_search_enabled(user_id: int, enabled) -> None:
    set_user_settings(user_id, web_search_enabled=_yn(enabled))
'''

# ---------------- main.py ----------------
M0_OLD = '''@app.get("/api/me/settings")
async def get_settings(user=Depends(current_user)):
'''
M0_NEW = '''def _web_search_override(body: dict):
    """P4e M-B:单次请求覆盖。**键不存在 → None**(交回用户级/全局默认),显式 false 才强制关。"""
    v = body.get("web_search")
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ("1", "true", "yes", "on")


def _web_on(s: dict) -> bool:
    """用户设置 → 布尔(未设置过回落全局默认,默认关)。"""
    from . import config
    v = str(s.get("web_search_enabled") or "").strip().lower()
    if v in ("1", "true", "yes", "on"):
        return True
    if v in ("0", "false", "no", "off"):
        return False
    return config.WEB_SEARCH_ENABLED


@app.get("/api/me/settings")
async def get_settings(user=Depends(current_user)):
'''

M1_OLD = '''        "effective_model": eff["model"],
        "username": user["username"], "role": user["role"], "role_zh": ROLE_ZH[user["role"]],
    }
'''
M1_NEW = '''        "effective_model": eff["model"],
        "username": user["username"], "role": user["role"], "role_zh": ROLE_ZH[user["role"]],
        # P4e M-B: 当前联网开关状态(UI 要能看见当前是开还是关)
        "web_search_enabled": _web_on(s),
    }
'''

M2_OLD = '''@app.put("/api/me/settings")
async def put_settings(body: dict, user=Depends(current_user)):
    custom = body.get("custom")
'''
M2_NEW = '''@app.put("/api/me/settings")
async def put_settings(body: dict, user=Depends(current_user)):
    # P4e M-B: 用户级默认开关(与 custom/model 互斥无关,独立处理)
    if body.get("web_search") is not None:
        db.set_web_search_enabled(user["id"], body["web_search"])
    custom = body.get("custom")
'''

M3_OLD = '''    try:
        d = await agent.chat_for(user["id"], user["username"], user["role"], question, cid,
                                 scope=scope)
'''
M3_NEW = '''    try:
        d = await agent.chat_for(user["id"], user["username"], user["role"], question, cid,
                                 scope=scope, web_search=_web_search_override(body))
'''

M4_OLD = '''                async for ev in agent.chat_stream_for(user["id"], user["username"], user["role"],
                                                      question, cid, scope=scope):
'''
M4_NEW = '''                async for ev in agent.chat_stream_for(user["id"], user["username"], user["role"],
                                                      question, cid, scope=scope,
                                                      web_search=_web_search_override(body)):
'''

PAIRS = [
    (DB, [("D1", D1_OLD, D1_NEW, 1), ("D2", D2_OLD, D2_NEW, 1), ("D3", D3_OLD, D3_NEW, 1)]),
    (MAIN, [("M0", M0_OLD, M0_NEW, 1), ("M1", M1_OLD, M1_NEW, 1), ("M2", M2_OLD, M2_NEW, 1),
            ("M3", M3_OLD, M3_NEW, 1), ("M4", M4_OLD, M4_NEW, 1)]),
]


def main() -> int:
    for path, items in PAIRS:
        src = path.read_text(encoding="utf-8")
        for name, old, new, cnt in items:
            n = src.count(old)
            if n != cnt:
                print(f"[FAIL] {path.name} {name} 命中 {n} 次(期望 {cnt})")
                return 1
            src = src.replace(old, new, 1)
        path.write_text(src, encoding="utf-8")
        print(f"[OK] {path.name} 已接线")
    return 0


if __name__ == "__main__":
    sys.exit(main())
