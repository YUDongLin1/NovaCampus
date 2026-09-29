#!/usr/bin/env python3
"""KB 体检(P4a C5/C6)— 扫描 agent.db:重复标题/超短正文/疑似登录页/口令与个人信息/
名单特征/孤儿分块/FTS 一致性,输出 reports/kb_doctor_<ts>.json。

用法:NO_PROXY 不需要(直读 sqlite)。PYTHONIOENCODING=utf-8 python evals/kb_doctor.py
分级:danger(口令/登录页/重复标题/孤儿分块/FTS 损坏,必须清零)/ warn(手机号/身份证/
名单特征/超短正文,需人工审核)。退出码:danger>0 → 1。
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError, OSError):
    pass

DB = Path(__file__).resolve().parent.parent / "novaagent" / "data" / "agent.db"
LOGIN_FEATURES = ["浏览器版本过旧", "兼容性提示", "请输入验证码", "用户名", "登录密码", "忘记密码"]
PASSWORD_RES = [
    (r"(用户名|口令|密码|账号)\s*[/／]\s*(口令|密码|用户名|账号)", "口令斜杠式"),
    (r"演示账号|演示口令|默认口令", "演示账号/口令"),
    (r"(admin|counselor|student)123", "演示口令字面量"),
    (r"密码(均为|都为|同为)", "密码均为句式"),
]
RE_MOBILE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
# 18 位身份证:6 位地区 + 8 位出生(年+合法月日) + 3 位顺序 + 校验位;
# 带出生日期合法性校验,避免把 PECD2016... 这类业务编号误报为身份证
RE_IDCARD = re.compile(r"(?<!\d)\d{6}(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx](?!\d)")


def main() -> int:
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    docs = [dict(r) for r in conn.execute(
        "SELECT id, title, filename, role_min, category FROM documents ORDER BY id")]
    chunks = [dict(r) for r in conn.execute(
        "SELECT doc_id, content FROM chunks")]
    by_doc: dict[int, list[str]] = {}
    for c in chunks:
        by_doc.setdefault(c["doc_id"], []).append(c["content"])

    danger: list[dict] = []
    warn: list[dict] = []

    def add(level: str, kind: str, doc_id: int | None, detail: str) -> None:
        (danger if level == "danger" else warn).append(
            {"kind": kind, "doc_id": doc_id, "detail": detail})

    # 1) 重复标题
    seen: dict[str, list[int]] = {}
    for d in docs:
        seen.setdefault(d["title"], []).append(d["id"])
    for title, ids in seen.items():
        if len(ids) > 1:
            add("danger", "duplicate_title", ids[0], f"标题《{title}》重复 {len(ids)} 篇: {ids}")

    # 2) 逐文档:登录页/口令/个人信息/名单/超短正文
    for d in docs:
        body = "\n".join(by_doc.get(d["id"], []))
        head = body[:600]
        if d["title"] in ("登录", "未命名网页") or sum(f in head for f in LOGIN_FEATURES) >= 2:
            add("danger", "login_page", d["id"], f"疑似登录页《{d['title']}》({d['filename']})")
        for pat, label in PASSWORD_RES:
            if re.search(pat, body):
                add("danger", "credential", d["id"], f"《{d['title']}》命中口令样式:{label}")
        if RE_MOBILE.search(body):
            add("warn", "mobile", d["id"], f"《{d['title']}》疑似含手机号")
        if RE_IDCARD.search(body):
            add("warn", "idcard", d["id"], f"《{d['title']}》疑似含身份证号")
        if ("名单" in d["title"] or "名单" in body[:400]) and ("姓名" in body or "学号" in body):
            add("warn", "name_list", d["id"], f"《{d['title']}》名单特征(需人工确认)")
        total = len(body.strip())
        if 0 < total < 200:
            add("warn", "short_body", d["id"], f"《{d['title']}》正文仅 {total} 字")

    # 3) 孤儿分块
    doc_ids = {d["id"] for d in docs}
    orphans = {c["doc_id"] for c in chunks if c["doc_id"] not in doc_ids}
    for oid in orphans:
        add("danger", "orphan_chunks", oid, f"chunks 存在 doc_id={oid} 但 documents 无对应")

    # 4) FTS 一致性:外部内容表 count 恒等于 chunks(T6 教训),须用 MATCH 抽样验证索引可用。
    #    ⚠ trigram 分词下 <3 字查询 MATCH 恒 0 是已知限制(HANDOFF 坑 11 变体),
    #    故取样正文里的一段 ≥3 字原文做 MATCH,保证"索引可用性"而非"词频"。
    n_chunks = len(chunks)
    try:
        sample = next((c["content"] for c in chunks if len(c["content"]) >= 8), "")
        term = sample[:4] if sample else ""
        fts_n = conn.execute(
            "SELECT count(*) FROM chunks_fts WHERE chunks_fts MATCH ?", (term,)
        ).fetchone()[0] if term else 0
        if fts_n == 0:
            add("danger", "fts_broken", None,
                f"chunks_fts 对原文取样「{term}」MATCH 恒 0(索引空/损坏)")
    except sqlite3.OperationalError as e:
        add("danger", "fts_broken", None, f"chunks_fts 查询失败: {e}")

    result = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "db": str(DB),
        "documents": len(docs),
        "chunks": n_chunks,
        "summary": {"danger": len(danger), "warn": len(warn)},
        "danger": danger,
        "warn": warn,
    }
    out = Path(__file__).resolve().parent.parent / "reports"
    out.mkdir(exist_ok=True)
    path = out / f"kb_doctor_{time.strftime('%Y%m%d_%H%M%S')}.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[kb_doctor] documents={len(docs)} chunks={n_chunks} "
          f"danger={len(danger)} warn={len(warn)}")
    for f in danger:
        print(f"  [DANGER] {f['kind']} doc={f['doc_id']} {f['detail']}")
    for f in warn:
        print(f"  [warn]   {f['kind']} doc={f['doc_id']} {f['detail']}")
    print(f"[report] {path}")
    print("[PASS] 0 高危项" if not danger else "[FAIL] 存在高危项,请清理后复检")
    return 1 if danger else 0


if __name__ == "__main__":
    sys.exit(main())
