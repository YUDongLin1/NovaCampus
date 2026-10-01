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
        # P4e M-B: web_search_enabled —— 用户级联网开关。'' == 未设置过 → 回落全局默认(关)。
        # TEXT 存 "1"/"0"(SQLite 无布尔;且要能区分"未设置"与"显式关",故不用 NOT NULL DEFAULT '0'
        # 之外的写法——未设置时本列即为 '',由 _web_enabled 判为未设置)。
        for col in ("custom_model", "llm_base_url", "llm_api_key", "web_search_enabled"):
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

    # T9: 会话持久化(按用户隔离)
    _conn.execute(
        """CREATE TABLE IF NOT EXISTS messages (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
               role TEXT NOT NULL CHECK(role IN ('user','assistant')),
               content TEXT NOT NULL,
               created_at TEXT NOT NULL
           )"""
    )
    _conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_user ON messages(user_id, id)")
    _conn.commit()

    # P4b C1: 会话与上下文管理(conversations 主表 + messages.conversation_id + 压缩摘要表;
    # persona_id 为 P4f 预留列,本单不实现人设逻辑)
    _conn.execute(
        """CREATE TABLE IF NOT EXISTS conversations (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
               title TEXT NOT NULL DEFAULT '新会话',
               persona_id INTEGER,
               archived INTEGER NOT NULL DEFAULT 0,
               created_at TEXT NOT NULL,
               updated_at TEXT NOT NULL
           )"""
    )
    _conn.execute("CREATE INDEX IF NOT EXISTS idx_conversations_user ON conversations(user_id, archived, id)")
    mcols = [r["name"] for r in _conn.execute("PRAGMA table_info(messages)")]
    if "conversation_id" not in mcols:
        with _lock:
            _conn.execute("ALTER TABLE messages ADD COLUMN conversation_id INTEGER")
            _conn.commit()
    # P4b-fix ①: assistant 消息回答时的来源快照(有效 sources 才落)——追问轮门控用它把
    # "可采信历史证据"限定为此前带有效来源的回答;user 消息与拒答模板恒为 NULL。
    if "sources_json" not in mcols:
        with _lock:
            _conn.execute("ALTER TABLE messages ADD COLUMN sources_json TEXT")
            _conn.commit()
    _conn.execute(
        """CREATE TABLE IF NOT EXISTS conversation_summary (
               conversation_id INTEGER PRIMARY KEY REFERENCES conversations(id) ON DELETE CASCADE,
               summary_text TEXT NOT NULL,
               covered_until_message_id INTEGER NOT NULL DEFAULT 0,
               updated_at TEXT NOT NULL
           )"""
    )
    _conn.commit()

    # P4d: 会话检索轨迹(retrieval_trace,供 graph 编排复盘与评测断言)
    ccols = [r["name"] for r in _conn.execute("PRAGMA table_info(conversations)")]
    if "retrieval_trace" not in ccols:
        with _lock:
            _conn.execute("ALTER TABLE conversations ADD COLUMN retrieval_trace TEXT")
            _conn.commit()

    # P4c C1: KB 文件夹 + documents.audience 学段元数据。
    # 迁移纪律(C1): 不删数据——只 CREATE IF NOT EXISTS / 幂等加列 / 建索引,
    # 不 UPDATE 任何既有行(folder_id 恒 NULL=根、audience 恒 'common'),
    # 重复启动不重复建表不重复赋值;计数守恒由 tests/test_p4c_kb.py 断言。
    _conn.execute(
        """CREATE TABLE IF NOT EXISTS folders (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               name TEXT NOT NULL,
               parent_id INTEGER REFERENCES folders(id) ON DELETE CASCADE,
               owner_id INTEGER NOT NULL REFERENCES users(id),
               -- private=仅建者可见( admin 例外);student/counselor/admin=该角色及以上可见
               visibility TEXT NOT NULL DEFAULT 'private'
                   CHECK(visibility IN ('private','student','counselor','admin')),
               created_at TEXT NOT NULL
           )"""
    )
    _conn.execute("CREATE INDEX IF NOT EXISTS idx_folders_owner ON folders(owner_id, parent_id)")
    dcols = [r["name"] for r in _conn.execute("PRAGMA table_info(documents)")]
    with _lock:
        if "folder_id" not in dcols:
            _conn.execute("ALTER TABLE documents ADD COLUMN folder_id INTEGER REFERENCES folders(id)")
        if "audience" not in dcols:
            _conn.execute(
                "ALTER TABLE documents ADD COLUMN audience TEXT NOT NULL DEFAULT 'common' "
                "CHECK(audience IN ('undergrad','postgrad','common'))"
            )
        _conn.execute("CREATE INDEX IF NOT EXISTS idx_documents_folder ON documents(folder_id)")
        _conn.execute("CREATE INDEX IF NOT EXISTS idx_documents_audience ON documents(audience)")
        _conn.commit()

    # ---------- P4f C1: 辅导员 persona(AI 辅导员人设) ----------
    # 迁移纪律(同 P4c C1): 只 CREATE IF NOT EXISTS / 幂等加列,**不 UPDATE 任何既有行**。
    # `conversations.persona_id` 列在 P4b 建表时已预留,本单只加外键索引(不加 FK 约束:
    # 既有库的 conversations 已有数据,加 FK 需重建表,违反"不删数据"纪律;
    # persona 删除后的处理见 `delete_persona` —— 置 `deleted_at` 软删除并**保留行**,
    # 于是 persona_id 永不断链,历史会话天然保留)。
    _conn.execute(
        """CREATE TABLE IF NOT EXISTS personas (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
               name TEXT NOT NULL,
               college TEXT NOT NULL DEFAULT '',
               -- 人设提示词:只影响**语气/身份/侧重点**,不得覆盖防幻觉规则段(见 agent.build_system_prompt)
               persona_prompt TEXT NOT NULL DEFAULT '',
               -- 回复风格:简短/详细/…(结构化枚举比自由文本更可控,前端下拉直接用)
               style TEXT NOT NULL DEFAULT 'balanced'
                   CHECK(style IN ('concise','balanced','detailed','warm','formal')),
               -- 绑定的检索范围(JSON 数组文本)。**不构成提权**:最终检索范围 =
               -- persona 绑定范围 ∩ 调用者 RBAC 可见范围(见 agent._resolve_persona_scope)。
               bound_folder_ids TEXT NOT NULL DEFAULT '[]',
               bound_categories TEXT NOT NULL DEFAULT '[]',
               -- private=仅建者;public=学生及以上也可用(admin 本就管全部,无独立档)
               visibility TEXT NOT NULL DEFAULT 'private'
                   CHECK(visibility IN ('private','public')),
               is_default INTEGER NOT NULL DEFAULT 0,
               deleted_at TEXT,          -- 软删除:历史会话保留并标记「人设已删除」
               created_at TEXT NOT NULL,
               updated_at TEXT NOT NULL
           )"""
    )
    _conn.execute("CREATE INDEX IF NOT EXISTS idx_personas_owner ON personas(owner_id, deleted_at)")
    # 同一用户最多一个 is_default=1(用**部分唯一索引**在库层兜住,避免应用层竞态
    # 产生两个默认人设导致前端选择器行为不确定)
    _conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_personas_one_default "
        "ON personas(owner_id) WHERE is_default=1 AND deleted_at IS NULL"
    )
    _conn.execute("CREATE INDEX IF NOT EXISTS idx_conversations_persona ON conversations(persona_id)")
    _conn.commit()

    _migrate_messages_to_conversations()


def _migrate_messages_to_conversations() -> None:
    """P4b C1: 为无会话归属的历史消息建历史会话(幂等,只处理 conversation_id IS NULL)。

    切分规则:同一 user_id 内,相邻消息间隔 >30 分钟即开新会话;迁移出的会话一律
    archived=1(不淹没 UI),标题取该组首条 user 消息前 20 字(否则「历史归档」);
    不删不改任何原文,迁移前后 messages 总数不变。
    """
    rows = _conn.execute(
        "SELECT id, user_id, role, content, created_at FROM messages "
        "WHERE conversation_id IS NULL ORDER BY user_id, id"
    ).fetchall()
    if not rows:
        return

    def _ts(s: str):
        try:
            return datetime.fromisoformat(s)
        except (ValueError, TypeError):
            return None

    groups: dict[tuple, list[int]] = {}
    prev: dict[int, tuple] = {}  # user_id -> (ts, group_key)
    for r in rows:
        uid = r["user_id"]
        ts = _ts(r["created_at"])
        p = prev.get(uid)
        new_session = p is None or ts is None or p[0] is None or (ts - p[0]).total_seconds() > 1800
        if new_session:
            gkey = (uid, r["id"])
            groups[gkey] = [r["id"]]
            prev[uid] = (ts, gkey)
        else:
            groups[p[1]].append(r["id"])
            prev[uid] = (ts, p[1])
    with _lock:
        for (uid, first_id), ids in groups.items():
            first = _conn.execute(
                "SELECT role, content FROM messages WHERE id=?", (first_id,)
            ).fetchone()
            title = (first["content"] or "")[:20] if first and first["role"] == "user" else ""
            if not title:
                title = f"历史归档 {first_id}"
            now = _now()
            cur = _conn.execute(
                "INSERT INTO conversations (user_id, title, persona_id, archived, created_at, updated_at) "
                "VALUES (?,?,NULL,1,?,?)",
                (uid, title, now, now),
            )
            cid = cur.lastrowid
            _conn.executemany(
                "UPDATE messages SET conversation_id=? WHERE id=?", [(cid, i) for i in ids]
            )
        _conn.commit()


def get_user_settings(user_id: int) -> dict:
    row = _conn.execute("SELECT * FROM user_settings WHERE user_id=?", (user_id,)).fetchone()
    if row is None:
        return {"model": "", "custom_model": "", "llm_base_url": "", "llm_api_key": "",
                "web_search_enabled": ""}
    d = dict(row)
    d.pop("user_id", None)
    d.pop("updated_at", None)
    return d


def _yn(v) -> str:
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


def insert_document(title: str, filename: str, role_min: str, uploaded_by: str,
                    category: str = "其他", folder_id: int | None = None,
                    audience: str = "common") -> int:
    """P4c C5: 上传时可带 folder_id 与 audience 学段标注(缺省=根目录/通用)。"""
    with _lock:
        cur = _conn.execute(
            "INSERT INTO documents (title, filename, role_min, uploaded_by, created_at, category,"
            " folder_id, audience) VALUES (?,?,?,?,?,?,?,?)",
            (title, filename, role_min, uploaded_by, _now(), category, folder_id, audience),
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


def find_document_by_url(url: str) -> dict | None:
    """P4a C4:按 filename(URL)查文档,导入质量门用于同 URL 去重。"""
    row = _conn.execute(
        "SELECT id, title, filename FROM documents WHERE filename = ? LIMIT 1", (url,)
    ).fetchone()
    return dict(row) if row else None


def list_documents(min_rank: int, category: str = "", folder_id: int | None = None,
                   audience: str = "") -> list[dict]:
    """KB 文档列表。P4c C5/C6: 增加 folder_id(含 'root' 语义=None 根目录)与 audience 筛选。"""
    allowed = [r for r, rank in config.ROLE_RANK.items() if rank <= min_rank]
    q = ",".join("?" * len(allowed))
    sql = f"""SELECT d.id, d.title, d.filename, d.role_min, d.uploaded_by, d.created_at, d.category,
                     d.folder_id, d.audience, COUNT(c.id) AS chunk_count
              FROM documents d LEFT JOIN chunks c ON c.doc_id = d.id
              WHERE d.role_min IN ({q})"""
    args: list = list(allowed)
    if category:
        sql += " AND d.category = ?"
        args.append(category)
    if folder_id == "root":
        sql += " AND d.folder_id IS NULL"
    elif isinstance(folder_id, int):
        sql += " AND d.folder_id = ?"
        args.append(folder_id)
    if audience in ("undergrad", "postgrad", "common"):
        sql += " AND d.audience = ?"
        args.append(audience)
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


# ---------- P4c C2/C3: 文件夹与检索 scope ----------

def _folder_visible_where(rank: int, user_id: int) -> tuple[str, list]:
    """文件夹可见性(沿用「不可见=不存在」约定,不泄露存在性):
    visibility='student' 所有人可见;'counselor'/'admin' 对应角色及以上;
    'private' 仅建者;admin(rank=3) 管全部。"""
    if rank >= 3:
        return ("1=1", [])
    conds = ["visibility='student'"]
    args: list = []
    if rank >= 2:
        conds.append("visibility='counselor'")
    conds.append("(visibility='private' AND owner_id=?)")
    args.append(user_id)
    return ("(" + " OR ".join(conds) + ")", args)


def visible_folder_ids(user_id: int, role: str) -> set[int]:
    """P4c 硬约束 1: scope 解析用——请求的 folder_ids 与此集合取交集,
    越权/不存在的 folder 一律静默忽略,响应不得泄露其是否存在。"""
    rank = config.ROLE_RANK[role]
    w, args = _folder_visible_where(rank, user_id)
    rows = _conn.execute(f"SELECT id FROM folders WHERE {w}", args).fetchall()
    return {r[0] for r in rows}


def folder_name_exists(name: str, parent_id: int | None, exclude_id: int | None = None,
                       requester_visible: set[int] | None = None) -> bool:
    """C2 同层重名检查:requester_visible 传入时只对"请求者看得见的重名"拒绝,
    避免误伤别人 private 文件夹的同名。"""
    sql = "SELECT id FROM folders WHERE name=? AND parent_id IS ?"
    args: list = [name, parent_id]
    if exclude_id:
        sql += " AND id != ?"
        args.append(exclude_id)
    rows = [r[0] for r in _conn.execute(sql, args).fetchall()]
    if not rows:
        return False
    if requester_visible is None:
        return True
    return any(rid in requester_visible for rid in rows)


def create_folder(name: str, parent_id: int | None, owner_id: int, visibility: str) -> int:
    with _lock:
        cur = _conn.execute(
            "INSERT INTO folders (name, parent_id, owner_id, visibility, created_at) VALUES (?,?,?,?,?)",
            (name, parent_id, owner_id, visibility, _now()),
        )
        _conn.commit()
        return cur.lastrowid


def get_folder(folder_id: int) -> dict | None:
    row = _conn.execute("SELECT * FROM folders WHERE id=?", (folder_id,)).fetchone()
    return dict(row) if row else None


def update_folder(folder_id: int, **fields) -> None:
    sets = ",".join(f"{k}=?" for k in fields)
    with _lock:
        _conn.execute(f"UPDATE folders SET {sets} WHERE id=?", (*fields.values(), folder_id))
        _conn.commit()


def folder_child_ids(folder_id: int) -> list[int]:
    """直接子文件夹 id(不含自身)。"""
    return [r[0] for r in _conn.execute(
        "SELECT id FROM folders WHERE parent_id=?", (folder_id,)).fetchall()]


def folder_descendant_ids(folder_id: int) -> list[int]:
    """子树全部 id(BFS;用于删除范围与环检测,不含 folder_id 自身)。"""
    out: list[int] = []
    frontier = [folder_id]
    while frontier:
        qs = ",".join("?" * len(frontier))
        rows = _conn.execute(
            f"SELECT id FROM folders WHERE parent_id IN ({qs})", frontier).fetchall()
        ids = [r[0] for r in rows]
        out += ids
        frontier = ids
    return out


def folder_visible_doc_count(folder_ids: list[int], min_rank: int) -> int:
    """这些文件夹下、对该角色可见的文档数(判定"空库"用,硬约束 3)。"""
    if not folder_ids:
        return 0
    allowed = [r for r, rank in config.ROLE_RANK.items() if rank <= min_rank]
    fq = ",".join("?" * len(folder_ids))
    aq = ",".join("?" * len(allowed))
    row = _conn.execute(
        f"SELECT COUNT(*) FROM documents WHERE folder_id IN ({fq}) AND role_min IN ({aq})",
        [*folder_ids, *allowed],
    ).fetchone()
    return row[0]


def delete_folders(folder_ids: list[int]) -> int:
    """删除文件夹子树;其下文档 folder_id 置 NULL(移回根)——**不删文档**,保证 KB 守恒(C9)。"""
    if not folder_ids:
        return 0
    qs = ",".join("?" * len(folder_ids))
    with _lock:
        cur = _conn.execute(f"UPDATE documents SET folder_id=NULL WHERE folder_id IN ({qs})", folder_ids)
        _conn.execute(f"DELETE FROM folders WHERE id IN ({qs})", folder_ids)
        _conn.commit()
    return cur.rowcount


_UNSET = object()


def update_document_meta(doc_id: int, folder_id=_UNSET,
                         audience: str | None = None) -> None:
    """P4c C2/C5: 移动/标注学段。folder_id 传 **None=移回根目录**、不传(默认哨兵)=不改;
    必须用哨兵区分"显式移回根"与"未提供"——否则 null 会被当成"未提供"丢掉。"""
    sets: list[str] = []
    args: list = []
    if folder_id is not _UNSET:
        sets.append("folder_id=?")
        args.append(folder_id)
    if audience is not None:
        sets.append("audience=?")
        args.append(audience)
    if not sets:
        return
    with _lock:
        _conn.execute(f"UPDATE documents SET {','.join(sets)} WHERE id=?", (*args, doc_id))
        _conn.commit()


def move_documents(doc_ids: list[int], folder_id: int | None) -> int:
    """P4c C2: 批量移动(含移回根)。返回实际更新条数。"""
    if not doc_ids:
        return 0
    qs = ",".join("?" * len(doc_ids))
    with _lock:
        cur = _conn.execute(
            f"UPDATE documents SET folder_id=? WHERE id IN ({qs})", (folder_id, *doc_ids))
        _conn.commit()
    return cur.rowcount


def list_folders_with_counts(user_id: int, role: str) -> list[dict]:
    """文件夹树(仅可见项)+ 每夹对该角色可见的文档数。"""
    rank = config.ROLE_RANK[role]
    w, args = _folder_visible_where(rank, user_id)
    rows = _conn.execute(
        f"SELECT * FROM folders WHERE {w} ORDER BY parent_id IS NOT NULL, name", args).fetchall()
    allowed = [r for r, rk in config.ROLE_RANK.items() if rk <= rank]
    aq = ",".join("?" * len(allowed))
    out = []
    for r in rows:
        d = dict(r)
        d["doc_count"] = _conn.execute(
            f"SELECT COUNT(*) FROM documents WHERE folder_id=? AND role_min IN ({aq})",
            [d["id"], *allowed]).fetchone()[0]
        out.append(d)
    return out


def audience_conflict(question_keywords: list[str], min_rank: int) -> bool:
    """P4c C5/F3: 问题命中学段敏感词时,检查 KB 是否**同时**存在本科/研究生两段的已标注材料。

    两边都有才值得追问学段(不猜)。当前库全部为 audience='common' → 恒 False,
    追问路径不会被存量评测用例触发(零回归);一旦后续按学段标注出成对材料即自动生效。
    """
    allowed = [r for r, rank in config.ROLE_RANK.items() if rank <= min_rank]
    aq = ",".join("?" * len(allowed))
    for kw in question_keywords:
        like = f"%{kw}%"
        rows = _conn.execute(
            f"""SELECT DISTINCT d.audience FROM documents d JOIN chunks c ON c.doc_id=d.id
                WHERE d.role_min IN ({aq}) AND d.audience IN ('undergrad','postgrad')
                  AND (d.title LIKE ? OR c.content LIKE ?)""",
            [*allowed, like, like],
        ).fetchall()
        if {"undergrad", "postgrad"} <= {r[0] for r in rows}:
            return True
    return False


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


def _scope_where(folder_ids: list[int] | None, categories: list[str] | None,
                 audience: str | None) -> tuple[str, list]:
    """P4c C3: scope 过滤片段(只收窄、不放宽,与 RBAC 的 role_min IN (...) 取交集)。

    folder_ids 传入前必须已由 main.resolve_scope 完成"越权 folder 静默忽略"
    (可见性解析),本函数只做纯过滤;audience 学段过滤始终放行 common,
    避免误杀未标注文档。返回 (where 片段, 参数列表)。
    """
    where: list[str] = []
    args: list = []
    if folder_ids:
        where.append(f"d.folder_id IN ({','.join('?' * len(folder_ids))})")
        args += [int(f) for f in folder_ids]
    if categories:
        where.append(f"d.category IN ({','.join('?' * len(categories))})")
        args += [str(c) for c in categories]
    if audience in ("undergrad", "postgrad"):
        where.append("d.audience IN (?, 'common')")
        args.append(audience)
    return (" AND " + " AND ".join(where)) if where else "", args


def all_chunks_for_search(min_rank: int, folder_ids: list[int] | None = None,
                          categories: list[str] | None = None,
                          audience: str | None = None) -> list[dict]:
    """取出当前角色可见的全部分块(含向量),供内存检索。

    P4c C3: scope 与 RBAC 取交集——folder_ids/categories/audience 只会收窄候选集,
    不可能放宽 role_min 过滤(文档自身 role_min 恒生效,文件夹可见性无法提权)。
    folder_ids=None 表示未指定 scope(全库,原行为);folder_ids==[] 表示"指定了
    scope 但解析后为空"→ 直接返回空列表(硬约束 3: 绝不静默回落全库)。
    """
    allowed = [r for r, rank in config.ROLE_RANK.items() if rank <= min_rank]
    q = ",".join("?" * len(allowed))
    if folder_ids is not None and not folder_ids:
        return []
    where_extra, extra_args = _scope_where(folder_ids, categories, audience)
    rows = _conn.execute(
        f"""SELECT c.id, c.content, c.embedding, d.title, d.role_min, d.id AS doc_id
            FROM chunks c JOIN documents d ON d.id=c.doc_id
            WHERE d.role_min IN ({q}){where_extra}""",
        allowed + extra_args,
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


def count_visible_documents(min_rank: int, folder_ids: list[int] | None = None,
                            categories: list[str] | None = None,
                            audience: str | None = None) -> int:
    """P4c 硬约束 3: 判定 scope 指定的范围内是否**真的有可见文档**——
    为 0 时 main 层返回明确提示,绝不静默回落全库检索。"""
    allowed = [r for r, rank in config.ROLE_RANK.items() if rank <= min_rank]
    q = ",".join("?" * len(allowed))
    if folder_ids is not None and not folder_ids:
        return 0
    extra_where, extra_args = _scope_where(folder_ids, categories, audience)
    row = _conn.execute(
        f"SELECT COUNT(*) FROM documents d WHERE d.role_min IN ({q}){extra_where}",
        allowed + extra_args,
    ).fetchone()
    return row[0]


def fts_available() -> bool:
    """T6 ⑥b: FTS5 全文索引是否可用(_migrate 探测)。"""
    return _fts_ok


def fts_search(query: str, role_mins: list[str], top_k: int,
               folder_ids: list[int] | None = None, categories: list[str] | None = None,
               audience: str | None = None) -> list[tuple[int, float]] | None:
    """T6 ⑥b: FTS5 关键词检索(bm25 排序,限定角色可见集)。

    匹配串为整句引号短语(短语在 trigram 分词下等价于其三连字的连续匹配,
    实测与 trigram-OR 命中数一致而语义更精确);短语无 trigram(不足 3 字)时
    返回 None,由调用方回退内存 2-gram 计次(行为不变)。
    返回 [(chunk_id, bm25 分数)] 按 bm25 升序(越小越相关);
    FTS5 不可用/异常/零命中返回 None(调用方回退,拒答阈值行为不变)。
    P4c C3: scope 过滤在 FTS 层同步生效——否则 top_k 会被 scope 外的块占满,
    指定小库时表现为"假性空结果"(坑 22 同源:指标好看 ≠ 真的检索到了)。
    """
    if not _fts_ok or not query.strip():
        return None
    if folder_ids is not None and not folder_ids:
        return None
    try:
        q = '"' + query.replace('"', '""') + '"'
        roles = ",".join("?" * len(role_mins))
        extra_where, extra_args = _scope_where(folder_ids, categories, audience)
        rows = _conn.execute(
            f"""SELECT c.id, bm25(chunks_fts) AS score
                FROM chunks_fts f
                JOIN chunks c ON c.id = f.rowid
                JOIN documents d ON d.id = c.doc_id
                WHERE chunks_fts MATCH ? AND d.role_min IN ({roles}){extra_where}
                ORDER BY score LIMIT ?""",
            [q, *role_mins, *extra_args, top_k],
        ).fetchall()
        if not rows:
            return None
        return [(r[0], r[1]) for r in rows]
    except Exception:  # FTS5 异常(MATCH 语法/表缺失等)一律回退内存计数
        return None


def add_message(user_id: int, role: str, content: str, conversation_id: int | None = None,
                sources: list[dict] | None = None) -> int:
    """T9: 追加一条会话消息(role: user/assistant);P4b 起可挂 conversation_id。返回消息 id。
    P4b-fix ①: assistant 消息可带回答时实际使用的 sources 快照(空/None 不落),
    供追问轮门控判定"可采信历史证据"。"""
    sources_json = json.dumps(sources, ensure_ascii=False) if sources else None
    with _lock:
        cur = _conn.execute(
            "INSERT INTO messages (user_id, role, content, created_at, conversation_id, sources_json) "
            "VALUES (?,?,?,?,?,?)",
            (user_id, role, content, _now(), conversation_id, sources_json),
        )
        if conversation_id:
            _conn.execute("UPDATE conversations SET updated_at=? WHERE id=?", (_now(), conversation_id))
        _conn.commit()
    return cur.lastrowid


def delete_message(message_id: int, conversation_id: int) -> bool:
    """P4b-fix ⑤: 客户端中止时回滚本轮 user 消息(仅限指定会话内的该条,防误删)。"""
    with _lock:
        cur = _conn.execute(
            "DELETE FROM messages WHERE id=? AND conversation_id=?", (message_id, conversation_id)
        )
        _conn.commit()
    return cur.rowcount > 0


def get_messages(user_id: int, limit: int = 50) -> list[dict]:
    """T9: 该用户最近 limit 条消息,时间正序返回(按 user_id 隔离)。"""
    rows = _conn.execute(
        "SELECT role, content, created_at FROM ("
        "  SELECT id, role, content, created_at FROM messages"
        "  WHERE user_id=? ORDER BY id DESC LIMIT ?"
        ") ORDER BY id ASC",
        (user_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]


# ---------- P4f C1: persona(AI 辅导员人设)CRUD ----------
#
# 【权限模型(硬约束:persona 不得提权)】
#   可见性判据 `_persona_visible_where`(唯一权威实现,list/get 共用):
#     admin      → 全部 persona(管全部)
#     非 admin   → 自己建的(owner)+ visibility='public' 的
#   即「辅导员只管自己的;学生只能用 public 的;admin 管全部」。
#   ⚠ persona 的 bound_folder_ids **不构成授权**:它只是"缩小检索范围"的配置,
#     最终范围 = persona 绑定范围 **∩** 调用者 RBAC 可见范围(在 main 层与
#     `_resolve_scope` 求交,复用同一入口,不得绕过)。
_STYLE_VALUES = ("concise", "balanced", "detailed", "warm", "formal")
# ⚠ 档位名用规格原文的 `public`,**不**沿用 folders 的 `student`/`counselor`/`admin`:
#   persona 的可见性只有「谁能用」这一个维度(没有"仅管理员"档 —— admin 本来就管全部),
#   沿用 folders 的三档名会让人误以为存在"仅管理员可见的人设"这条不存在的语义。
#   private=仅建者;public=学生及以上也可用。
_PERSONA_VISIBILITY_VALUES = ("private", "public")


def _persona_row_to_dict(row) -> dict:
    d = dict(row)
    for k in ("bound_folder_ids", "bound_categories"):
        try:
            d[k] = json.loads(d.get(k) or "[]")
        except (ValueError, TypeError):
            d[k] = []
    d["is_default"] = bool(d.get("is_default"))
    d["deleted"] = bool(d.get("deleted_at"))
    return d


def _persona_visible_where(role: str, user_id: int) -> tuple[str, list]:
    """persona 可见性判据(与文件夹的 `_folder_visible_where` 同构)。

    ⚠ **唯一权威实现**:`list_personas`(列表)与 `get_persona`(单条,经 `_persona_can_use`)
       必须共用它。第一版把这两处写成了两套 if/elif,结果学生**列表里看不到任何 public 人设**
       (`elif role != "student"` 把学生挡掉了)而 `get_persona` 又放行 —— 同一件事两个权威实现,
       下拉框空、接口却说"可用"(坑 45:同一判据只应有一处)。
    """
    if role == "admin":
        return "1=1", []
    # 非 admin:自己的 + visibility='public' 的
    return "(owner_id=? OR visibility='public')", [user_id]


def list_personas(user_id: int, role: str) -> list[dict]:
    """按角色可见性列出 persona(**不含已软删除的**)。纯查询,不提权。"""
    connect()   # 确保 _conn 就绪
    w, args = _persona_visible_where(role, user_id)
    rows = _conn.execute(
        f"SELECT * FROM personas WHERE deleted_at IS NULL AND {w} "
        "ORDER BY is_default DESC, id ASC", args
    ).fetchall()
    return [_persona_row_to_dict(r) for r in rows]


def get_persona(persona_id: int, user_id: int, role: str) -> dict | None:
    """取单个 persona 并做可见性判定。不可见 → **None(与不存在同表现,不泄露存在性)**。"""
    connect()
    row = _conn.execute("SELECT * FROM personas WHERE id=? AND deleted_at IS NULL",
                        (persona_id,)).fetchone()
    if not row:
        return None
    d = _persona_row_to_dict(row)
    if not _persona_can_use(d, user_id, role):
        return None
    return d


def _persona_can_use(p: dict, user_id: int, role: str) -> bool:
    """该 persona 对 (user_id, role) 是否可用。判据与 `list_personas` **同源**
    (`_persona_visible_where`),不允许各写一套。"""
    if p.get("deleted"):
        return False
    if role == "admin":
        return True
    if int(p.get("owner_id") or 0) == int(user_id):
        return True
    return p.get("visibility") == "public"


def create_persona(user_id: int, name: str, college: str = "", persona_prompt: str = "",
                   style: str = "balanced", bound_folder_ids: list | None = None,
                   bound_categories: list | None = None, visibility: str = "private",
                   is_default: bool = False) -> int:
    connect()
    now = _now()
    with _lock:
        cur = _conn.execute(
            "INSERT INTO personas (owner_id,name,college,persona_prompt,style,"
            "bound_folder_ids,bound_categories,visibility,is_default,created_at,updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,0,?,?)",
            (user_id, (name or "").strip()[:40] or "未命名辅导员", (college or "").strip()[:40],
             (persona_prompt or "").strip()[:2000], style,
             json.dumps(list(bound_folder_ids or []), ensure_ascii=False),
             json.dumps(list(bound_categories or []), ensure_ascii=False),
             visibility, now, now),
        )
        pid = cur.lastrowid
        _conn.commit()
    # ⚠ 必须在锁**外**调 set_default_persona:_lock 是普通 `threading.Lock`,**不可重入**,
    #   嵌套 acquire 会死锁(本单第一版就踩了:自测直接挂住,不是断言红,是最难查的那种)。
    if is_default:
        set_default_persona(pid, user_id)
    return pid


def update_persona(persona_id: int, user_id: int, role: str, patch: dict) -> dict | None:
    """按可见性更新。不可见/不存在 → None(不区分,防存在性泄露)。"""
    p = get_persona(persona_id, user_id, role)
    if not p:
        return None
    # 只有 owner 或 admin 能改(辅导员不能用别人的公共人设)
    if int(p["owner_id"]) != int(user_id) and role != "admin":
        return None
    fields, vals = [], []
    for col, caster, limit in (
        ("name", str, 40), ("college", str, 40), ("persona_prompt", str, 2000),
    ):
        if col in patch:
            fields.append(f"{col}=?")
            vals.append(caster(patch[col]).strip()[:limit])
    if "style" in patch and patch["style"] in _STYLE_VALUES:
        fields.append("style=?")
        vals.append(patch["style"])
    if "visibility" in patch and patch["visibility"] in _PERSONA_VISIBILITY_VALUES:
        fields.append("visibility=?")
        vals.append(patch["visibility"])
    for col in ("bound_folder_ids", "bound_categories"):
        if col in patch and isinstance(patch[col], list):
            fields.append(f"{col}=?")
            vals.append(json.dumps(patch[col], ensure_ascii=False))
    if not fields:
        return get_persona(persona_id, user_id, role)
    with _lock:
        _conn.execute(f"UPDATE personas SET {','.join(fields)}, updated_at=? WHERE id=?",
                      (*vals, _now(), persona_id))
        _conn.commit()
    # ⚠ 同 create_persona:必须在锁外调(_lock 不可重入,嵌套会死锁)
    if patch.get("is_default"):
        set_default_persona(persona_id, user_id)
    return get_persona(persona_id, user_id, role)


def set_default_persona(persona_id: int, user_id: int) -> None:
    """把某人的人设设为默认(同一人只允许一个默认,库层部分唯一索引兜底)。"""
    with _lock:
        _conn.execute("UPDATE personas SET is_default=0 WHERE owner_id=?", (user_id,))
        _conn.execute("UPDATE personas SET is_default=1, updated_at=? WHERE id=? AND owner_id=?",
                      (_now(), persona_id, user_id))
        _conn.commit()


def delete_persona(persona_id: int, user_id: int, role: str) -> bool:
    """**软删除**:置 deleted_at,**保留行**。于是 conversations.persona_id 永不断链,
    历史会话保留并在读取时标记「人设已删除」(见 `list_conversations` / `get_conversation`)。"""
    p = get_persona(persona_id, user_id, role)
    if not p:
        return False
    if int(p["owner_id"]) != int(user_id) and role != "admin":
        return False
    with _lock:
        _conn.execute("UPDATE personas SET deleted_at=?, is_default=0, updated_at=? WHERE id=?",
                      (_now(), _now(), persona_id))
        _conn.commit()
    return True


def persona_display_name(persona_id: int | None) -> str:
    """会话列表用的人设显示名。**已删除** → 固定文案「人设已删除」(规格硬要求)。"""
    if not persona_id:
        return ""
    row = _conn.execute("SELECT name, deleted_at FROM personas WHERE id=?", (persona_id,)).fetchone()
    if not row:
        return "人设已删除"
    return "人设已删除" if row["deleted_at"] else (row["name"] or "")


# ---------- P4b C6: 会话 CRUD(可见性一律 user_id 过滤;越权与不存在同表现) ----------

def create_conversation(user_id: int, title: str = "新会话",
                        persona_id: int | None = None) -> int:
    now = _now()
    with _lock:
        cur = _conn.execute(
            "INSERT INTO conversations (user_id, title, persona_id, archived, created_at, updated_at) "
            "VALUES (?,?,?,0,?,?)",
            (user_id, (title or "新会话")[:20], persona_id, now, now),
        )
        _conn.commit()
    return cur.lastrowid


def update_conversation_trace(conv_id: int, trace: list | None) -> None:
    """P4d: 落检索轨迹(intent/retrieve/rewrite 各节点耗时、改写前后查询、质量信号),
    供复盘与评测断言(`retrieval_trace.skipped=true` / 是否发生改写)。"""
    if not conv_id or trace is None:
        return
    with _lock:
        _conn.execute("UPDATE conversations SET retrieval_trace=? WHERE id=?",
                      (json.dumps(trace, ensure_ascii=False)[:8000], conv_id))
        _conn.commit()


def get_conversation(conv_id: int, user_id: int) -> dict | None:
    row = _conn.execute(
        "SELECT * FROM conversations WHERE id=? AND user_id=?", (conv_id, user_id)
    ).fetchone()
    return dict(row) if row else None


def list_conversations(user_id: int, include_archived: bool = False, limit: int = 200) -> list[dict]:
    # P4f: 带出 persona_id + 人设显示名(已软删除 → 「人设已删除」,规格硬要求)。
    # 用 LEFT JOIN 而非额外查询:会话列表是首屏渲染,避免 N+1。
    q = ("SELECT c.id, c.title, c.archived, c.updated_at, c.persona_id, "
         "       p.name AS persona_name, p.deleted_at AS persona_deleted_at, "
         "       COUNT(m.id) AS message_count "
         "FROM conversations c "
         "LEFT JOIN personas p ON p.id = c.persona_id "
         "LEFT JOIN messages m ON m.conversation_id = c.id "
         "WHERE c.user_id=?")
    if not include_archived:
        q += " AND c.archived=0"
    q += " GROUP BY c.id ORDER BY c.archived ASC, c.updated_at DESC, c.id DESC LIMIT ?"
    rows = _conn.execute(q, (user_id, limit)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        if d.get("persona_id"):
            d["persona_name"] = ("人设已删除" if d.get("persona_deleted_at")
                                 else (d.get("persona_name") or ""))
        else:
            d["persona_name"] = ""
        d.pop("persona_deleted_at", None)
        out.append(d)
    return out


def set_conversation_persona(conv_id: int, user_id: int, persona_id: int | None) -> bool:
    """对话中切换人设。会话必须属于该用户,否则 False(与不存在同表现)。"""
    if not get_conversation(conv_id, user_id):
        return False
    with _lock:
        _conn.execute("UPDATE conversations SET persona_id=?, updated_at=? WHERE id=? AND user_id=?",
                      (persona_id, _now(), conv_id, user_id))
        _conn.commit()
    return True


def rename_conversation(conv_id: int, user_id: int, title: str) -> bool:
    with _lock:
        cur = _conn.execute(
            "UPDATE conversations SET title=?, updated_at=? WHERE id=? AND user_id=?",
            ((title or "").strip()[:20] or "新会话", _now(), conv_id, user_id),
        )
        _conn.commit()
    return cur.rowcount > 0


def set_conversation_archived(conv_id: int, user_id: int, archived: bool) -> bool:
    with _lock:
        cur = _conn.execute(
            "UPDATE conversations SET archived=?, updated_at=? WHERE id=? AND user_id=?",
            (1 if archived else 0, _now(), conv_id, user_id),
        )
        _conn.commit()
    return cur.rowcount > 0


def delete_conversation(conv_id: int, user_id: int) -> dict | None:
    """级联删除:只删该会话的消息与摘要;会话不属于该用户 → None(与不存在同表现)。"""
    if not get_conversation(conv_id, user_id):
        return None
    with _lock:
        n_msg = _conn.execute(
            "DELETE FROM messages WHERE conversation_id=?", (conv_id,)
        ).rowcount
        n_sum = _conn.execute(
            "DELETE FROM conversation_summary WHERE conversation_id=?", (conv_id,)
        ).rowcount
        _conn.execute("DELETE FROM conversations WHERE id=?", (conv_id,))
        _conn.commit()
    return {"messages_deleted": n_msg, "summary_deleted": n_sum}


def conversation_messages(conv_id: int, limit: int = 50, offset: int = 0) -> tuple[list[dict], int]:
    total = _conn.execute(
        "SELECT count(*) FROM messages WHERE conversation_id=?", (conv_id,)
    ).fetchone()[0]
    rows = _conn.execute(
        "SELECT id, role, content, created_at FROM messages WHERE conversation_id=? "
        "ORDER BY id ASC LIMIT ? OFFSET ?",
        (conv_id, limit, offset),
    ).fetchall()
    return [dict(r) for r in rows], total


def get_conversation_history(conv_id: int) -> list[dict]:
    """历史注入用:时间正序全量(含消息 id 与 sources_json,供压缩覆盖标记、
    评测隔离断言与 P4b-fix ① 追问轮门控的可采信证据判定)。"""
    rows = _conn.execute(
        "SELECT id, role, content, sources_json FROM messages WHERE conversation_id=? ORDER BY id ASC",
        (conv_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def upsert_conversation_summary(conv_id: int, summary_text: str, covered_until: int) -> None:
    with _lock:
        _conn.execute(
            "INSERT INTO conversation_summary (conversation_id, summary_text, covered_until_message_id, updated_at) "
            "VALUES (?,?,?,?) ON CONFLICT(conversation_id) DO UPDATE SET "
            "summary_text=excluded.summary_text, covered_until_message_id=excluded.covered_until_message_id, "
            "updated_at=excluded.updated_at",
            (conv_id, summary_text, covered_until, _now()),
        )
        _conn.commit()


def get_conversation_summary(conv_id: int) -> dict | None:
    row = _conn.execute(
        "SELECT * FROM conversation_summary WHERE conversation_id=?", (conv_id,)
    ).fetchone()
    return dict(row) if row else None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
