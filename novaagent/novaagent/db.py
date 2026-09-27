"""SQLite 存储层:用户/会话/文档/分块。向量以 JSON 存 BLOB,查询时载入 numpy
(MVP 语料量级 <1e4 块,内存余弦足够;升级路径:sqlite-vec / pgvector)。"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from . import config

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None
_fts_ok = False          # T6 ⑥b: FTS5 可用性(_migrate 探测,trigram→unicode61 降级)
_fts_tokenizer = ''

def connect() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        Path(config.DB_PATH).parent.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(config.DB_PATH, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('student','counselor','admin')),
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                filename TEXT NOT NULL,
                role_min TEXT NOT NULL CHECK(role_min IN ('student','counselor','admin')),
                uploaded_by TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                doc_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                idx INTEGER NOT NULL,
                content TEXT NOT NULL,
                embedding TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks(doc_id);
            """
        )
        _migrate()
        seed_users()
    return _conn


def _migrate() -> None:
    """轻量迁移:补齐旧库新增列/表。"""
    cols = [r["name"] for r in _conn.execute("PRAGMA table_info(documents)")]
    if "category" not in cols:
        with _lock:
            _conn.execute("ALTER TABLE documents ADD COLUMN category TEXT NOT NULL DEFAULT '其他'")
            _conn.commit()
    if "summary" not in cols:
        with _lock:
            _conn.execute("ALTER TABLE documents ADD COLUMN summary TEXT NOT NULL DEFAULT ''")
            _conn.commit()
    _conn.execute(
        """CREATE TABLE IF NOT EXISTS user_settings (
               user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
               model TEXT NOT NULL DEFAULT '',
               updated_at TEXT NOT NULL
           )"""
    )
    us_cols = [r["name"] for r in _conn.execute("PRAGMA table_info(user_settings)")]
    with _lock:
        for col in ("custom_model", "llm_base_url", "llm_api_key"):
            if col not in us_cols:
                _conn.execute(f"ALTER TABLE user_settings ADD COLUMN {col} TEXT NOT NULL DEFAULT ''")
        _conn.commit()

    # T6 ⑥b: FTS5 外部内容全文索引(外部内容表;tokenizer 降级链 trigram → unicode61 → 不可用)
    global _fts_ok, _fts_tokenizer
    _fts_ok, _fts_tokenizer = False, ""
    for tok in ("trigram", "unicode61"):
        try:
            _conn.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5("
                f"content, content='chunks', content_rowid='id', tokenize='{tok}')"
            )
            _fts_ok, _fts_tokenizer = True, tok
            break
        except sqlite3.OperationalError:
            continue
    if _fts_ok:
        _conn.executescript(
            """
            CREATE TRIGGER IF NOT EXISTS chunks_fts_ai AFTER INSERT ON chunks BEGIN
                INSERT INTO chunks_fts(rowid, content) VALUES (new.id, new.content);
            END;
            CREATE TRIGGER IF NOT EXISTS chunks_fts_ad AFTER DELETE ON chunks BEGIN
                INSERT INTO chunks_fts(chunks_fts, rowid, content) VALUES('delete', old.id, old.content);
            END;
            CREATE TRIGGER IF NOT EXISTS chunks_fts_au AFTER UPDATE ON chunks BEGIN
                INSERT INTO chunks_fts(chunks_fts, rowid, content) VALUES('delete', old.id, old.content);
                INSERT INTO chunks_fts(rowid, content) VALUES (new.id, new.content);
            END;
            """
        )
        # T6 根因修复:外部内容表 count(chunks_fts) 直读内容表,计数门控永不触发,
        # 索引恒空 → MATCH 恒 0。改为无条件幂等重建(485 行亚秒级),每次启动执行。
        _conn.execute("INSERT INTO chunks_fts(chunks_fts) VALUES('rebuild')")
        _conn.commit()


def get_user_settings(user_id: int) -> dict:
    row = _conn.execute("SELECT * FROM user_settings WHERE user_id=?", (user_id,)).fetchone()
    if row is None:
        return {"model": "", "custom_model": "", "llm_base_url": "", "llm_api_key": ""}
    d = dict(row)
    d.pop("user_id", None)
    d.pop("updated_at", None)
    return d


def set_user_settings(user_id: int, **fields) -> None:
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


def update_document_summary(doc_id: int, summary: str) -> None:
    with _lock:
        _conn.execute("UPDATE documents SET summary=? WHERE id=?", (summary, doc_id))
        _conn.commit()


def seed_users() -> None:
    """开发种子账号(演示用,生产应改为注册+强密码)。"""
    if _conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"] > 0:
        return
    for username, password, role in [
        ("admin", "admin123", "admin"),
        ("counselor", "counselor123", "counselor"),
        ("student", "student123", "student"),
    ]:
        add_user(username, password, role)


def add_user(username: str, password: str, role: str) -> None:
    salt = "novacampus-dev"
    h = hashlib.sha256((salt + password).encode()).hexdigest()
    with _lock:
        _conn.execute(
            "INSERT OR IGNORE INTO users (username, password_hash, role, created_at) VALUES (?,?,?,?)",
            (username, h, role, _now()),
        )
        _conn.commit()


def verify_user(username: str, password: str) -> sqlite3.Row | None:
    salt = "novacampus-dev"
    h = hashlib.sha256((salt + password).encode()).hexdigest()
    row = _conn.execute(
        "SELECT * FROM users WHERE username=? AND password_hash=?", (username, h)
    ).fetchone()
    return row


def create_session(user_id: int) -> str:
    import uuid

    token = uuid.uuid4().hex
    with _lock:
        _conn.execute(
            "INSERT INTO sessions (token, user_id, created_at) VALUES (?,?,?)",
            (token, user_id, _now()),
        )
        _conn.commit()
    return token


def user_by_token(token: str) -> sqlite3.Row | None:
    return _conn.execute(
        """SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token=?""",
        (token,),
    ).fetchone()


def insert_document(title: str, filename: str, role_min: str, uploaded_by: str, category: str = "其他") -> int:
    with _lock:
        cur = _conn.execute(
            "INSERT INTO documents (title, filename, role_min, uploaded_by, created_at, category) VALUES (?,?,?,?,?,?)",
            (title, filename, role_min, uploaded_by, _now(), category),
        )
        _conn.commit()
        return cur.lastrowid


def insert_chunks(doc_id: int, chunks: list[tuple[int, str, list[float]]]) -> None:
    with _lock:
        _conn.executemany(
            "INSERT INTO chunks (doc_id, idx, content, embedding) VALUES (?,?,?,?)",
            [(doc_id, i, c, json.dumps(v)) for i, c, v in chunks],
        )
        _conn.commit()


def delete_document(doc_id: int) -> bool:
    with _lock:
        cur = _conn.execute("DELETE FROM documents WHERE id=?", (doc_id,))
        _conn.execute("DELETE FROM chunks WHERE doc_id=?", (doc_id,))
        _conn.commit()
    return cur.rowcount > 0


def list_documents(min_rank: int, category: str = "") -> list[dict]:
    allowed = [r for r, rank in config.ROLE_RANK.items() if rank <= min_rank]
    q = ",".join("?" * len(allowed))
    sql = f"""SELECT d.id, d.title, d.filename, d.role_min, d.uploaded_by, d.created_at, d.category,
                     COUNT(c.id) AS chunk_count
              FROM documents d LEFT JOIN chunks c ON c.doc_id = d.id
              WHERE d.role_min IN ({q})"""
    args: list = list(allowed)
    if category:
        sql += " AND d.category = ?"
        args.append(category)
    sql += " GROUP BY d.id ORDER BY d.id DESC"
    rows = _conn.execute(sql, args).fetchall()
    return [dict(r) for r in rows]


def list_categories(min_rank: int) -> list[str]:
    allowed = [r for r, rank in config.ROLE_RANK.items() if rank <= min_rank]
    q = ",".join("?" * len(allowed))
    rows = _conn.execute(
        f"SELECT DISTINCT category FROM documents WHERE role_min IN ({q}) AND category != '其他' ORDER BY category",
        allowed,
    ).fetchall()
    return [r["category"] for r in rows]


def get_user_model(user_id: int) -> str:
    row = _conn.execute("SELECT model FROM user_settings WHERE user_id=?", (user_id,)).fetchone()
    return (row["model"] if row and row["model"] else "") or ""


def set_user_model(user_id: int, model: str) -> None:
    with _lock:
        _conn.execute(
            """INSERT INTO user_settings (user_id, model, updated_at) VALUES (?,?,?)
               ON CONFLICT(user_id) DO UPDATE SET model=excluded.model, updated_at=excluded.updated_at""",
            (user_id, model, _now()),
        )
        _conn.commit()


def get_document(doc_id: int, min_rank: int) -> dict | None:
    """取文档;不可见(权限不足)与不存在同样返回 None,避免探测。"""
    row = _conn.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
    if row is None or config.ROLE_RANK[row["role_min"]] > min_rank:
        return None
    return dict(row)


def get_chunks(doc_id: int) -> list[dict]:
    rows = _conn.execute(
        "SELECT idx, content FROM chunks WHERE doc_id=? ORDER BY idx", (doc_id,)
    ).fetchall()
    return [dict(r) for r in rows]


def all_chunks_for_search(min_rank: int) -> list[dict]:
    """取出当前角色可见的全部分块(含向量),供内存检索。"""
    allowed = [r for r, rank in config.ROLE_RANK.items() if rank <= min_rank]
    q = ",".join("?" * len(allowed))
    rows = _conn.execute(
        f"""SELECT c.id, c.content, c.embedding, d.title, d.role_min, d.id AS doc_id
            FROM chunks c JOIN documents d ON d.id=c.doc_id
            WHERE d.role_min IN ({q})""",
        allowed,
    ).fetchall()
    return [
        {
            "id": r["id"],
            "doc_id": r["doc_id"],
            "content": r["content"],
            "title": r["title"],
            "role_min": r["role_min"],
            "vector": np.asarray(json.loads(r["embedding"]), dtype="float32"),
        }
        for r in rows
    ]


def fts_available() -> bool:
    """T6 ⑥b: FTS5 全文索引是否可用(_migrate 探测)。"""
    return _fts_ok


def fts_search(query: str, role_mins: list[str], top_k: int) -> list[tuple[int, float]] | None:
    """T6 ⑥b: FTS5 关键词检索(bm25 排序,限定角色可见集)。

    匹配串为整句引号短语(短语在 trigram 分词下等价于其三连字的连续匹配,
    实测与 trigram-OR 命中数一致而语义更精确);短语无 trigram(不足 3 字)时
    返回 None,由调用方回退内存 2-gram 计次(行为不变)。
    返回 [(chunk_id, bm25 分数)] 按 bm25 升序(越小越相关);
    FTS5 不可用/异常/零命中返回 None(调用方回退,拒答阈值行为不变)。
    """
    if not _fts_ok or not query.strip():
        return None
    try:
        q = '"' + query.replace('"', '""') + '"'
        roles = ",".join("?" * len(role_mins))
        rows = _conn.execute(
            f"""SELECT c.id, bm25(chunks_fts) AS score
                FROM chunks_fts f
                JOIN chunks c ON c.id = f.rowid
                JOIN documents d ON d.id = c.doc_id
                WHERE chunks_fts MATCH ? AND d.role_min IN ({roles})
                ORDER BY score LIMIT ?""",
            [q, *role_mins, top_k],
        ).fetchall()
        if not rows:
            return None
        return [(r[0], r[1]) for r in rows]
    except Exception:  # FTS5 异常(MATCH 语法/表缺失等)一律回退内存计数
        return None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
