#!/usr/bin/env python3
"""周报 MCP Server(NovaCampus P1)— 辅导员碎片记录 → 结构化周报 → 归档

架构约定:分类智能交给 WeKnora 里的 Agent(LLM)完成,本 Server 只做
确定性的存取与渲染 —— 工具职责单一,便于评测与复用。

工具(12 个):
  add_fragment         记录一条工作碎片(未指定分类时由 Agent 判断后传入)
  list_fragments       按日期范围列出碎片
  update_fragment      补录/修改一条碎片的学生姓名与摘要
  delete_fragment      删除记录错误的碎片
  export_talk_records  按月导出谈心谈话记录(台账整句,确定性渲染)
  render_weekly_report 按日期范围聚合碎片,渲染结构化周报 Markdown 草稿
  archive_report       归档定稿周报(SQLite + Markdown 文件),供后续回灌知识库
  add_minutes          存一条 AI 整理后的会议纪要
  list_minutes         列出会议纪要
  get_minutes          读取单条会议纪要(含原始内容)
  update_minutes       保存用户对纪要的在线编辑
  delete_minutes       删除一条会议纪要(软删除)

迁移纪律(与 novaagent/db.py 同源):只 CREATE IF NOT EXISTS / 幂等加列,
**不 UPDATE 任何既有行**——历史碎片的新列一律落默认空串,由消费方显示占位,
不回填、不伪造。

运行:python server.py(环境变量 WEEKLY_DATA_DIR / WEEKLY_PORT)
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
from datetime import date, datetime, timedelta
from pathlib import Path

from mcp.server.mcpserver import MCPServer

DATA_DIR = Path(os.environ.get("WEEKLY_DATA_DIR", "./data-weekly"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "weekly.db"
REPORTS_DIR = DATA_DIR / "reports"
REPORTS_DIR.mkdir(exist_ok=True)

CATEGORIES = ["谈心谈话", "事务办理", "活动组织", "异常突发", "其他"]

TALK_CATEGORY = "谈心谈话"
# 历史碎片没有姓名/摘要(迁移不回填),导出与展示用固定占位串,不留空也不伪造。
PLACEHOLDER_NAME = "（未登记姓名）"
PLACEHOLDER_SUMMARY = "（未生成摘要）"

_lock = threading.Lock()
_conn = sqlite3.connect(DB_PATH, check_same_thread=False)
_conn.row_factory = sqlite3.Row
_conn.executescript(
    """
    CREATE TABLE IF NOT EXISTS fragments (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        content     TEXT NOT NULL,
        category    TEXT NOT NULL DEFAULT '其他',
        occurred_at TEXT NOT NULL,
        created_at  TEXT NOT NULL,
        deleted     INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS reports (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        title      TEXT NOT NULL,
        start_date TEXT NOT NULL,
        end_date   TEXT NOT NULL,
        content_md TEXT NOT NULL,
        file_path  TEXT NOT NULL,
        archived_at TEXT NOT NULL
    );
    """
)


# ---------- 学生姓名 / 谈话摘要 / 会议纪要 ----------
# ⚠ 幂等加列,**不 UPDATE 既有行**:存量碎片的新列恒为 '',由前端与导出层显示占位串。
#   与 novaagent/db.py 的迁移纪律同源(只 CREATE IF NOT EXISTS / ALTER 加列 / 建索引)。
def _migrate() -> None:
    fcols = {r["name"] for r in _conn.execute("PRAGMA table_info(fragments)")}
    for col in ("student_name", "summary"):
        if col not in fcols:
            _conn.execute(f"ALTER TABLE fragments ADD COLUMN {col} TEXT NOT NULL DEFAULT ''")

    # 会议纪要:结构化字段分列存(前端编辑与导出都要按字段取),
    # 待办用 JSON 文本存数组(每项含 事项/责任人/截止时间),不拆子表——
    # 单条纪要的待办数量个位数,拆表只增加 JOIN 与一致性负担。
    _conn.execute(
        """CREATE TABLE IF NOT EXISTS minutes (
               id            INTEGER PRIMARY KEY AUTOINCREMENT,
               title         TEXT NOT NULL DEFAULT '',
               meeting_time  TEXT NOT NULL DEFAULT '',
               attendees     TEXT NOT NULL DEFAULT '',
               discussion    TEXT NOT NULL DEFAULT '',
               resolutions   TEXT NOT NULL DEFAULT '',
               todos         TEXT NOT NULL DEFAULT '[]',
               raw_content   TEXT NOT NULL DEFAULT '',
               source_type   TEXT NOT NULL DEFAULT 'text',
               audio_name    TEXT NOT NULL DEFAULT '',
               created_at    TEXT NOT NULL,
               updated_at    TEXT NOT NULL,
               deleted       INTEGER NOT NULL DEFAULT 0
           )"""
    )
    _conn.execute("CREATE INDEX IF NOT EXISTS idx_minutes_active ON minutes(deleted, id)")
    _conn.commit()


_migrate()

mcp = MCPServer(
    "weekly-report",
    instructions=(
        "辅导员周报助手。标准流程(每步一个动作,按顺序执行):\n"
        "1) 用户随口说工作碎片 → 调用 add_fragment 记录。"
        "分类未明说时,从 "
        f"{CATEGORIES}"
        " 中选最贴切的一类传入 category。\n"
        "2) 分类为「谈心谈话」→ 同时传 student_name(用户原话里提到的学生姓名;"
        "没提到就留空)与 summary(一句规范摘要,形如「就该学生职业规划情况进行谈心谈话」,"
        "主题只能取自用户原话)。\n"
        "3) 用户要写周报 → 先 render_weekly_report 生成草稿,再基于草稿润色输出给用户。\n"
        "4) 用户确认定稿 → 调用 archive_report 归档。\n"
        "边界:一句话里含多条互不相关的碎片 → 分多次调用 add_fragment,每次一条;"
        "用户要改或删已有记录 → 用 update_fragment / delete_fragment,不要新增重复记录;"
        "用户要整理会议内容 → 走 add_minutes / list_minutes,不要塞进工作碎片;"
        "问题与工作记录无关(闲聊、问政策) → 直接回答,不调用任何工具。"
    ),
)


def _today() -> str:
    return date.today().isoformat()


def _valid_date(s: str) -> str:
    date.fromisoformat(s)  # 值校验,不合法会抛 ValueError
    return s


def _ok(**kw) -> str:
    return json.dumps({"ok": True, **kw}, ensure_ascii=False)


def _err(msg: str) -> str:
    return json.dumps({"ok": False, "error": msg}, ensure_ascii=False)


@mcp.tool()
def add_fragment(content: str, category: str = "其他", occurred_at: str = "",
                 student_name: str = "", summary: str = "") -> str:
    """记录一条辅导员工作碎片。

    content: 碎片内容,一句话即可,尽量包含时间/对象/事项/结果;
    category: 必须是 谈心谈话/事务办理/活动组织/异常突发/其他 之一,由调用方(你)判断;
    occurred_at: 事件发生日期 YYYY-MM-DD,缺省为今天(注意区分"发生时间"与"记录时间");
    student_name: 谈心谈话类记录的学生姓名(界面必填;本层留空可落库,由前端显示占位);
    summary: 规范摘要,形如"就该学生职业规划情况进行谈心谈话",由调用方生成后传入,可为空。
    """
    content = content.strip()
    if not content:
        return _err("content 不能为空")
    if category not in CATEGORIES:
        category = "其他"
    occurred = _valid_date(occurred_at) if occurred_at else _today()
    with _lock:
        cur = _conn.execute(
            "INSERT INTO fragments (content, category, occurred_at, created_at,"
            " student_name, summary) VALUES (?,?,?,?,?,?)",
            (content, category, occurred, datetime.now().isoformat(timespec="seconds"),
             student_name.strip()[:40], summary.strip()[:200]),
        )
        _conn.commit()
        return _ok(fragment_id=cur.lastrowid, category=category, occurred_at=occurred)


@mcp.tool()
def list_fragments(start_date: str = "", end_date: str = "") -> str:
    """按发生日期范围(闭区间)列出碎片,缺省返回全部未删除记录。日期格式 YYYY-MM-DD。"""
    q, args = ("SELECT id, content, category, occurred_at, student_name, summary "
               "FROM fragments WHERE deleted=0"), []
    if start_date:
        q += " AND occurred_at >= ?"
        args.append(_valid_date(start_date))
    if end_date:
        q += " AND occurred_at <= ?"
        args.append(_valid_date(end_date))
    q += " ORDER BY occurred_at, id"
    with _lock:
        rows = [dict(r) for r in _conn.execute(q, args)]
    return _ok(count=len(rows), fragments=rows)


@mcp.tool()
def update_fragment(fragment_id: int, student_name: str = "", summary: str = "") -> str:
    """补录/修改一条碎片的姓名与摘要(详情页手改摘要、给历史记录补名字都走这里)。

    ⚠ 传空串表示**该字段不改**,不是"清空"。界面上没有"清空姓名/摘要"这个动作,
      因此不需要区分"显式清空"与"未提供"——若将来要支持清空,必须改用哨兵或 None,
      不能沿用这里的空串语义(同类坑见 novaagent/db.py 的 update_document_meta)。
    """
    with _lock:
        row = _conn.execute("SELECT id FROM fragments WHERE id=? AND deleted=0",
                            (fragment_id,)).fetchone()
        if row is None:
            return _err(f"未找到 id={fragment_id} 的有效碎片")
        sets, vals = [], []
        if student_name.strip():
            sets.append("student_name=?")
            vals.append(student_name.strip()[:40])
        if summary.strip():
            sets.append("summary=?")
            vals.append(summary.strip()[:200])
        if not sets:
            return _err("没有需要修改的字段")
        _conn.execute(f"UPDATE fragments SET {','.join(sets)} WHERE id=?", (*vals, fragment_id))
        _conn.commit()
    return _ok(fragment_id=fragment_id, updated=sets)


@mcp.tool()
def delete_fragment(fragment_id: int) -> str:
    """删除一条记错的碎片(软删除)。"""
    with _lock:
        cur = _conn.execute("UPDATE fragments SET deleted=1 WHERE id=? AND deleted=0", (fragment_id,))
        _conn.commit()
    return _ok(deleted=cur.rowcount) if cur.rowcount else _err(f"未找到 id={fragment_id} 的有效碎片")


def _talk_sentence(occurred_at: str, student_name: str, summary: str) -> str:
    """台账整句:「X年X月X日与XXX就该学生职业规划情况进行谈心谈话」。

    缺姓名/缺摘要各写自己的占位串,**不跳过该行、不猜测**——导出的价值在于
    条数与月份对得上,缺字段应当一眼可见并可回补。
    """
    y, m, d = (occurred_at.split("-") + ["", "", ""])[:3]
    try:
        date_txt = f"{int(y)}年{int(m)}月{int(d)}日"
    except ValueError:
        date_txt = occurred_at
    name = (student_name or "").strip() or PLACEHOLDER_NAME
    summ = (summary or "").strip() or PLACEHOLDER_SUMMARY
    return f"{date_txt}与{name}{summ}"


@mcp.tool()
def export_talk_records(month: str) -> str:
    """按月导出谈心谈话记录(该月每条一行台账整句)。month 格式 YYYY-MM。

    渲染在本层做(本 Server 的定位是"确定性的存取与渲染"),调用方只负责把
    rows 拼成 CSV 并加 UTF-8 BOM。按 occurred_at、id 升序。
    """
    if len(month) != 7 or month[4] != "-":
        return _err("month 必须是 YYYY-MM 格式")
    try:
        date.fromisoformat(f"{month}-01")
    except ValueError:
        return _err("month 必须是 YYYY-MM 格式")
    with _lock:
        rows = [dict(r) for r in _conn.execute(
            "SELECT id, occurred_at, student_name, summary, content FROM fragments "
            "WHERE deleted=0 AND category=? AND occurred_at LIKE ? ORDER BY occurred_at, id",
            (TALK_CATEGORY, f"{month}-%"),
        )]
    return _ok(
        month=month,
        count=len(rows),
        rows=[_talk_sentence(r["occurred_at"], r["student_name"], r["summary"]) for r in rows],
        fragments=rows,
    )


@mcp.tool()
def render_weekly_report(start_date: str, end_date: str = "") -> str:
    """聚合 [start_date, end_date] 内的碎片,渲染结构化周报 Markdown 草稿。

    end_date 缺省为 start_date 同周的周日。草稿返回后,你应润色措辞与总结,
    再让用户确认,确认后调用 archive_report 归档。
    """
    start = _valid_date(start_date)
    end = _valid_date(end_date) if end_date else str(
        date.fromisoformat(start) + timedelta(days=6 - date.fromisoformat(start).weekday())
    )
    with _lock:
        rows = [dict(r) for r in _conn.execute(
            "SELECT id, content, category, occurred_at FROM fragments "
            "WHERE deleted=0 AND occurred_at>=? AND occurred_at<=? ORDER BY occurred_at, id",
            (start, end),
        )]
    if not rows:
        return _err(f"{start} ~ {end} 没有已记录的碎片,请先用 add_fragment 记录")

    by_cat: dict[str, list[dict]] = {}
    for r in rows:
        by_cat.setdefault(r["category"], []).append(r)

    lines = [
        f"# 辅导员工作周报({start} ~ {end})",
        "",
        "## 本周概览",
        f"- 共记录 {len(rows)} 条工作事项:"
        + "、".join(f"{c} {len(v)} 条" for c, v in by_cat.items()),
        "",
    ]
    for cat in CATEGORIES:
        if cat not in by_cat:
            continue
        lines.append(f"## {cat}")
        for r in by_cat[cat]:
            d = r["occurred_at"][5:]  # MM-DD
            lines.append(f"- [{d}] {r['content']}")
        lines.append("")
    lines += ["## 下周计划", "- (待补充)", "", "> 本草稿由智枢 Agent 基于碎片记录自动整理,归档前请核对内容。"]
    return _ok(start_date=start, end_date=end, count=len(rows), report_markdown="\n".join(lines))


@mcp.tool()
def archive_report(title: str, start_date: str, end_date: str, content_md: str) -> str:
    """归档定稿周报:写入 SQLite 并保存 Markdown 文件,返回文件路径。

    title: 周报标题;content_md: 润色定稿后的完整 Markdown 内容(通常来自 render_weekly_report 的草稿)。
    """
    start, end = _valid_date(start_date), _valid_date(end_date)
    fname = f"{start}_{end}_周报.md"
    fpath = REPORTS_DIR / fname
    fpath.write_text(f"# {title}\n\n{content_md}", encoding="utf-8")
    with _lock:
        cur = _conn.execute(
            "INSERT INTO reports (title, start_date, end_date, content_md, file_path, archived_at) "
            "VALUES (?,?,?,?,?,?)",
            (title, start, end, content_md, str(fpath), datetime.now().isoformat(timespec="seconds")),
        )
        _conn.commit()
        return _ok(report_id=cur.lastrowid, file=str(fpath))


@mcp.tool()
def list_reports(start_date: str = "", end_date: str = "") -> str:
    """列出已归档周报(按归档时间倒序)。start_date/end_date 为可选过滤:
    只返回与 [start_date, end_date] 区间有重叠的周报。"""
    q = ("SELECT id, title, start_date, end_date, file_path, archived_at FROM reports WHERE 1=1")
    args: list[str] = []
    if start_date:
        q += " AND end_date >= ?"
        args.append(_valid_date(start_date))
    if end_date:
        q += " AND start_date <= ?"
        args.append(_valid_date(end_date))
    q += " ORDER BY id DESC"
    with _lock:
        rows = [dict(r) for r in _conn.execute(q, args)]
    return _ok(count=len(rows), reports=rows)


@mcp.tool()
def read_report(report_id: int) -> str:
    """读取一篇已归档周报的完整 Markdown 内容。"""
    with _lock:
        row = _conn.execute(
            "SELECT id, title, start_date, end_date, content_md, file_path, archived_at "
            "FROM reports WHERE id=?",
            (report_id,),
        ).fetchone()
    if row is None:
        return _err(f"未找到 id={report_id} 的归档周报")
    return _ok(**dict(row))


# ---------- 会议纪要(AI 整理结果的存取) ----------
# 【为什么在本层存】与谈心谈话碎片同库(data/weekly/weekly.db),备份/清理/以后做
#   台账统计都在一个库里;本层依旧只做确定性存取,**整理与转写不在这里**
#   (在 novaagent 侧,与 expand_fragment / summarize_document 同层)。
# 【todos 用 JSON 文本】每项 {item, owner, due};不拆子表(单条纪要待办个位数)。
_MIN_TEXT_LIMIT = 8000
_MIN_TODO_LIMIT = 40


def _minutes_row_to_dict(row) -> dict:
    d = dict(row)
    for k in ("todos", "discussion", "resolutions"):
        try:
            v = json.loads(d.get(k) or "[]")
        except (ValueError, TypeError):
            v = []
        d[k] = v if isinstance(v, list) else []
    d["todos"] = [t for t in d["todos"] if isinstance(t, dict)]
    d.pop("deleted", None)
    return d


def _json_lines(v, item_max: int = 500, max_items: int = 200) -> str:
    """数组 / JSON 文本 / 换行文本 → 存库的 JSON 数组文本(用于要点与决议两条纯文本数组)。

    ⚠ 为什么跨边界的是**字符串**而不是数组:MCP 工具的参数类型由函数签名生成 JSON Schema,
      声明成 `str` 的参数一旦收到 list,会在**协议层校验**就被打回
      (`Input should be a valid string [type=string_type]`),根本进不到函数体。
      所以纪要的三个数组字段(要点/决议/待办)跨边界时一律 JSON 文本,读回时再解析成数组。
    """
    if isinstance(v, (list, tuple)):
        items = [str(x).strip() for x in v]
    else:
        s = str(v or "").strip()
        if not s:
            items = []
        else:
            try:
                parsed = json.loads(s)
                items = [str(x).strip() for x in parsed] if isinstance(parsed, list) else [s]
            except (ValueError, TypeError):
                items = [p.strip() for p in re.split(r"[\n;；]+", s)]
    items = [x[:item_max] for x in items if x]
    return json.dumps(items[:max_items], ensure_ascii=False)


def _clean_minutes_fields(fields: dict) -> dict:
    """按字段清洗。要点/决议/待办三个**数组字段**存 JSON 文本,其余存纯文本。"""
    out = {}
    for key, limit in (
        ("title", 200), ("meeting_time", 100), ("attendees", 1000),
        ("raw_content", _MIN_TEXT_LIMIT), ("audio_name", 200),
    ):
        if key in fields:
            out[key] = str(fields[key] or "").strip()[:limit]
    for key in ("discussion", "resolutions"):
        if key in fields:
            out[key] = _json_lines(fields[key])
    if "source_type" in fields:
        st = str(fields["source_type"] or "text").strip()
        out["source_type"] = st if st in ("text", "file", "audio") else "text"
    if "todos" in fields:
        todos = fields["todos"]
        if isinstance(todos, str):
            try:
                todos = json.loads(todos or "[]")
            except (ValueError, TypeError):
                todos = []
        cleaned = []
        for t in (todos if isinstance(todos, list) else [])[:_MIN_TODO_LIMIT]:
            if not isinstance(t, dict):
                continue
            cleaned.append({
                "item": str(t.get("item") or "").strip()[:500],
                "owner": str(t.get("owner") or "").strip()[:60],
                "due": str(t.get("due") or "").strip()[:60],
            })
        out["todos"] = json.dumps(cleaned, ensure_ascii=False)
    return out


@mcp.tool()
def add_minutes(title: str = "", meeting_time: str = "", attendees: str = "",
                discussion: str = "", resolutions: str = "", todos: str = "[]",
                raw_content: str = "", source_type: str = "text",
                audio_name: str = "") -> str:
    """存一条 AI 整理后的会议纪要(结构化字段 + 原始内容,原始内容留存以便回看对照)。

    discussion/resolutions/todos 都是 **JSON 数组文本**(todos 每项形如
    {"item":"…","owner":"…","due":"…"});MCP 参数声明为 str,传 list 会在协议层校验被拒。
    source_type: text(粘贴)/file(上传笔记)/audio(录音转写);
    缺失字段照实存空串,**由调用方在入库前就填好占位提示**,本层不补内容。
    """
    now = datetime.now().isoformat(timespec="seconds")
    f = _clean_minutes_fields({
        "title": title, "meeting_time": meeting_time, "attendees": attendees,
        "discussion": discussion, "resolutions": resolutions, "todos": todos,
        "raw_content": raw_content, "source_type": source_type, "audio_name": audio_name,
    })
    with _lock:
        cur = _conn.execute(
            "INSERT INTO minutes (title, meeting_time, attendees, discussion, resolutions,"
            " todos, raw_content, source_type, audio_name, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (f.get("title", ""), f.get("meeting_time", ""), f.get("attendees", ""),
             f.get("discussion", ""), f.get("resolutions", ""), f.get("todos", "[]"),
             f.get("raw_content", ""), f.get("source_type", "text"),
             f.get("audio_name", ""), now, now),
        )
        _conn.commit()
        return _ok(minutes_id=cur.lastrowid)


@mcp.tool()
def list_minutes(start_date: str = "", end_date: str = "") -> str:
    """列出会议纪要(id/标题/时间/参会人/更新时间,**不含正文**,列表页够用)。

    start_date/end_date 按**创建日期**过滤(纪要没有可靠的"发生日期"语义,
    不像碎片那样用 occurred_at —— 会议时间常缺失)。
    """
    q = ("SELECT id, title, meeting_time, attendees, source_type, created_at, updated_at "
         "FROM minutes WHERE deleted=0")
    args: list[str] = []
    if start_date:
        q += " AND date(created_at) >= ?"
        args.append(_valid_date(start_date))
    if end_date:
        q += " AND date(created_at) <= ?"
        args.append(_valid_date(end_date))
    q += " ORDER BY id DESC"
    with _lock:
        rows = [dict(r) for r in _conn.execute(q, args)]
    return _ok(count=len(rows), minutes=rows)


@mcp.tool()
def get_minutes(minutes_id: int) -> str:
    """读取单条会议纪要全文(含各结构化字段与原始内容)。"""
    with _lock:
        row = _conn.execute("SELECT * FROM minutes WHERE id=? AND deleted=0",
                            (minutes_id,)).fetchone()
    if row is None:
        return _err(f"未找到 id={minutes_id} 的会议纪要")
    return _ok(**_minutes_row_to_dict(row))


@mcp.tool()
def update_minutes(minutes_id: int, title: str = "", meeting_time: str = "",
                   attendees: str = "", discussion: str = "", resolutions: str = "",
                   todos: str = "[]") -> str:
    """保存用户对纪要的在线编辑 —— **整条覆盖**,不是逐字段补丁。

    ⚠ 与 update_fragment 的"空串=不改"语义**故意不同**:纪要是在线编辑整表单提交,
      用户清空某段就是要把该段清空,所以这里全部字段按传入值覆盖。
      只改一个字段的调用方必须先取回整条再提交(前端已经是这么做的)。
    """
    f = _clean_minutes_fields({
        "title": title, "meeting_time": meeting_time, "attendees": attendees,
        "discussion": discussion, "resolutions": resolutions, "todos": todos,
    })
    with _lock:
        if _conn.execute("SELECT id FROM minutes WHERE id=? AND deleted=0",
                         (minutes_id,)).fetchone() is None:
            return _err(f"未找到 id={minutes_id} 的会议纪要")
        _conn.execute(
            "UPDATE minutes SET title=?, meeting_time=?, attendees=?, discussion=?,"
            " resolutions=?, todos=?, updated_at=? WHERE id=?",
            (f.get("title", ""), f.get("meeting_time", ""), f.get("attendees", ""),
             f.get("discussion", ""), f.get("resolutions", ""), f.get("todos", "[]"),
             datetime.now().isoformat(timespec="seconds"), minutes_id),
        )
        _conn.commit()
    return _ok(minutes_id=minutes_id, updated=True)


@mcp.tool()
def delete_minutes(minutes_id: int) -> str:
    """删除一条会议纪要(软删除,与碎片同纪律)。"""
    with _lock:
        cur = _conn.execute("UPDATE minutes SET deleted=1 WHERE id=? AND deleted=0",
                            (minutes_id,))
        _conn.commit()
    return _ok(deleted=cur.rowcount) if cur.rowcount else _err(f"未找到 id={minutes_id} 的纪要")


if __name__ == "__main__":

    # 双传输并存:SSE(/sse,WeKnora MCP 客户端使用)+ Streamable HTTP(/mcp,通用客户端)
    from contextlib import asynccontextmanager

    import uvicorn
    from starlette.applications import Starlette

    # 默认只监听回环地址:本服务无鉴权层,默认对外全网卡监听等于把
    # 周报原始记录暴露到局域网。确需容器/跨机访问时由部署方显式设
    # WEEKLY_HOST=0.0.0.0,并自行在前置层加认证。
    host = os.environ.get("WEEKLY_HOST", "127.0.0.1")
    port = int(os.environ.get("WEEKLY_PORT", "8000"))

    sse_asgi = mcp.sse_app(sse_path="/sse", message_path="/messages/", host=host)
    http_asgi = mcp.streamable_http_app(streamable_http_path="/mcp", host=host)

    @asynccontextmanager
    async def lifespan(_app):
        # streamable_http_app 的 lifespan 负责 StreamableHTTPSessionManager 启动,
        # 必须带着跑,否则 /mcp 请求会报 task group 未初始化
        async with http_asgi.router.lifespan_context(http_asgi):
            async with sse_asgi.router.lifespan_context(sse_asgi):
                yield

    app = Starlette(routes=[*http_asgi.routes, *sse_asgi.routes], lifespan=lifespan)
    uvicorn.run(app, host=host, port=port)
