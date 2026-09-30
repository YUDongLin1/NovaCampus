#!/usr/bin/env python3
"""P4e M-E 合规红线探针(C 级):把**实际发出的联网请求体**逐字段落盘并逐条比对。

单据要求:「这条**要读代码追**,不是测功能」——所以本探针不靠"看一遍代码觉得没问题",
而是:
  L1 直接抓 `websearch.search()` 发出的 httpx 请求体;
  L2 走完整 `agent.chat_for(..., web_search=True)` 流水线(带**会话历史**、带**库内来源**、
     带 contacts/系统提示词),抓该轮唯一一次联网请求体。

红线:出网只有「当前问题文本」一个字符串——无库内 chunk、无会话历史、无系统提示词、
无改写串里带的语料片段、无学生个人信息、无 contacts.json 内容;日志不记问题以外字段。

⚠ DB:用 agent.db 的**只读副本/只读连接**,生产库零改动;不访问 E:\\<internal-affairs-dir>\\。
⚠ 问句:一律构造的公开知识题(ISO 4217),不是任何真实学工问句。

退出码:0 = 全过;1 = 有 FAIL;2 = 抓取失败。
证据:docs/p4e/evidence/web_compliance.json
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError, OSError):
    pass

_TMP = Path(tempfile.mkdtemp(prefix="nova_compliance_")) / "novaagent" / "data"
_TMP.mkdir(parents=True, exist_ok=True)
_SRC = ROOT / "novaagent" / "data" / "agent.db"
if _SRC.exists():
    shutil.copy2(_SRC, _TMP / "agent.db")
os.environ["NOVA_DATA_DIR"] = str(_TMP)
os.environ["NOVA_GRAPH_ENABLED"] = "0"
sys.path.insert(0, str(ROOT / "novaagent"))

import httpx  # noqa: E402

from novaagent import agent, config, db, llm, rag, websearch  # noqa: E402

OUT = ROOT / "docs" / "p4e" / "evidence" / "web_compliance.json"
QUESTION = "ISO 4217 标准里人民币的三字母代码是什么？"   # 构造的公开知识题
PLANTED = ("埋点-姓名1同学", "埋点-学号20259999", "埋点-手机号13800001111")  # 个人信息埋点

FAILS: list = []
CAPTURED: list = []


def ck(cond: bool, name: str, detail: str = "") -> None:
    print(f"{'[PASS]' if cond else '[FAIL]'} {name}{(' — ' + detail) if detail else ''}")
    if not cond:
        FAILS.append(name)


# ---------------- 抓取真实的 httpx 请求体 ----------------
_ORIG_POST = httpx.AsyncClient.post


async def _spy_post(self, url, *a, **kw):
    if "/responses" in str(url):          # 只抓联网(Responses)请求
        CAPTURED.append({"url": str(url), "json": kw.get("json"), "headers": dict(kw.get("headers") or {})})
    return await _ORIG_POST(self, url, *a, **kw)


httpx.AsyncClient.post = _spy_post        # type: ignore[assignment]


# ---------------- 被测物:不该出网的敏感样本 ----------------
def _sample_chunks(n: int = 5, chars: int = 24) -> list[str]:
    """从库里取真实 chunk 片段(只读连接)。"""
    con = sqlite3.connect(f"file:{_SRC}?mode=ro", uri=True)
    try:
        rows = con.execute("SELECT content FROM chunks LIMIT ?", (n,)).fetchall()
    except sqlite3.Error:
        rows = []
    finally:
        con.close()
    return [(r[0] or "")[:chars] for r in rows if (r[0] or "").strip()]


def _contacts_marks() -> list[str]:
    p = ROOT / "novaagent" / "novaagent" / "data" / "contacts.json"
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return []
    marks: list[str] = []
    for c in data.get("contacts", [])[:3]:
        for k in ("dept", "url", "phone"):
            v = c.get(k)
            if isinstance(v, str) and v.strip():
                marks.append(v.strip())
            elif isinstance(v, list) and v:
                marks.append(str(v[0]))
    return marks[:6]


FORBIDDEN: list[tuple[str, str]] = []


def build_forbidden() -> None:
    FORBIDDEN.clear()
    for i, s in enumerate(_sample_chunks()):
        FORBIDDEN.append((f"库内 chunk#{i} 片段", s))
    for i, s in enumerate(_contacts_marks()):
        FORBIDDEN.append((f"contacts.json#{i}", s))
    FORBIDDEN.append(("SYSTEM_PROMPT 片段", agent.SYSTEM_PROMPT[:40]))
    FORBIDDEN.append(("联网区块模板片段", agent.WEB_CONTEXT_BLOCK.strip()[:30]))
    for s in PLANTED:
        FORBIDDEN.append(("个人信息埋点", s))


def _strings(x):
    """递归取出请求体里所有**字符串值**(不序列化——json.dumps 会把 \n 转义成 \\n,
    让"库内 chunk 片段"这类含换行的样本**永远匹配不上**,尺子会静默空转)。"""
    if isinstance(x, str):
        yield x
    elif isinstance(x, dict):
        for v in x.values():
            yield from _strings(v)
    elif isinstance(x, (list, tuple)):
        for v in x:
            yield from _strings(v)


def scan(payload: dict) -> list[str]:
    """同一把尺子:对请求体里的每个字符串值逐条扫。E6 反向用例证明它能判红。"""
    vals = list(_strings(payload))
    hits = []
    for label, s in FORBIDDEN:
        if s and len(s) >= 6 and any(s in v for v in vals):
            hits.append(f"{label}: {s[:24]!r}")
    return hits


def check_payload(payload: dict, tag: str) -> None:
    keys = sorted((payload or {}).keys())
    # tool_choice 是**控制字段**(强制联网),不是内容字段;内容仍只有 input 一个字符串
    ck(keys == ["input", "model", "tool_choice", "tools"],
       f"{tag} 请求体顶层键 == {{model,input,tools,tool_choice}}", f"实得 {keys}")
    ck((payload or {}).get("tool_choice") == {"type": "web_search"},
       f"{tag} tool_choice 强制联网(实测:不加则静态知识题 0 源)",
       f"tool_choice={(payload or {}).get('tool_choice')!r}")
    ck((payload or {}).get("input") == QUESTION, f"{tag} input **逐字等于**当前问题文本",
       f"input={(payload or {}).get('input')!r}")
    ck((payload or {}).get("tools") == [{"type": "web_search"}], f"{tag} tools 恒为 web_search",
       f"tools={(payload or {}).get('tools')!r}")
    hits = scan(payload or {})
    ck(not hits, f"{tag} 请求体内不含任何禁出网内容(chunk/历史/系统提示词/个人信息/contacts)",
       "; ".join(hits[:5]))
    ck(not any(pl in v for pl in PLANTED for v in _strings(payload)),
       f"{tag} 不含历史里埋的个人信息", "")


# ---------------- 日志捕获 ----------------
class _Cap(logging.Handler):
    def __init__(self):
        super().__init__()
        self.lines: list[str] = []

    def emit(self, record):
        try:
            self.lines.append(record.getMessage())
        except Exception:  # noqa: BLE001
            pass


async def main() -> int:
    db.connect()
    build_forbidden()
    print(f"[env] DATA_DIR={config.DATA_DIR}(库副本) 禁出网样本 {len(FORBIDDEN)} 条")
    if not config.LLM_API_KEY:
        print("[FATAL] 缺 LLM_API_KEY,无法实测出网请求体")
        return 2

    # ---------- L1:直接调用 websearch.search ----------
    cap = _Cap()
    logging.getLogger("novaagent.websearch").addHandler(cap)
    root_cap = _Cap()
    logging.getLogger().addHandler(root_cap)
    res = await websearch.search(QUESTION)
    ck(bool(CAPTURED), "L1 抓到真实联网请求体", f"n={len(CAPTURED)}")
    p1 = CAPTURED[-1]["json"] if CAPTURED else {}
    check_payload(p1, "L1")
    ck(res.get("n_sources", 0) >= 0, "L1 调用完成", f"n_sources={res.get('n_sources')} error={res.get('error')!r}")

    # ---------- L2:完整流水线(带历史 + 带库内来源) ----------
    convo = db.create_conversation(1, title="compliance-probe")
    # 埋:会话历史(含个人信息样式的埋点)+ 库内来源 + 联网开关打开
    db.add_message(1, "user", f"我叫{PLANTED[0]}，学号 {PLANTED[1]}，手机 {PLANTED[2]}。", convo)
    db.add_message(1, "assistant", "好的，已记录。", convo)

    async def _fake_search(q, mr, scope=None):
        # 故意让本地**有来源**——验证「本地有据时压根不出网」
        return ([{"ref": 1, "title": "EVAL-研究生学籍管理规定", "content": "最长学习年限为 5 年。",
                  "score": 0.99, "role_min": "student", "doc_id": 1, "chunk_id": 1}],
                {"top_score": 0.99, "n_above_threshold": 2, "rerank_available": True})

    async def _empty_search(q, mr, scope=None):
        return ([], {"top_score": None, "n_above_threshold": 0, "rerank_available": False})

    async def _fake_chat(messages, tools=None, max_tokens=2048, temperature=0.3,
                         model="", base_url="", api_key=""):
        return {"role": "assistant", "content": "（桩答案）人民币代码为 CNY[1]。"}

    real_llm_chat, llm.chat = llm.chat, _fake_chat
    try:
        # L2a:本地有据 → **不应**发起联网请求
        rag.search_with_quality = _fake_search   # type: ignore[assignment]
        n_before = len(CAPTURED)
        await agent.AgentService().chat_for(1, "student", "student", QUESTION, convo,
                                            web_search=True)
        ck(len(CAPTURED) == n_before,
           "L2a 本地有据时**不出网**(联网只是补充通道,不是每次都发)",
           f"新增请求 {len(CAPTURED) - n_before} 次")

        # L2b:本地无据 + 开关开 → 才发起,且请求体必须干净
        rag.search_with_quality = _empty_search  # type: ignore[assignment]
        n_before = len(CAPTURED)
        await agent.AgentService().chat_for(1, "student", "student", QUESTION, convo,
                                            web_search=True)
        ck(len(CAPTURED) == n_before + 1, "L2b 本地无据 + 开关开 → 恰好发起 1 次联网请求",
           f"新增 {len(CAPTURED) - n_before} 次")
        if len(CAPTURED) > n_before:
            check_payload(CAPTURED[-1]["json"], "L2b")

        # L2c:开关关 → 一次都不发(合规硬闸)
        n_before = len(CAPTURED)
        await agent.AgentService().chat_for(1, "student", "student", QUESTION, convo,
                                            web_search=False)
        ck(len(CAPTURED) == n_before, "L2c 开关关闭 → 绝不发起联网请求",
           f"新增 {len(CAPTURED) - n_before} 次")
    finally:
        llm.chat = real_llm_chat

    # ---------- 日志 ----------
    logs = cap.lines + root_cap.lines
    bad_logs = [ln for ln in logs if any(s in ln for _, s in FORBIDDEN if len(s) >= 6)]
    ck(not bad_logs, "E4 日志未记录问题以外的敏感字段(chunk/contacts/个人信息/系统提示词)",
       "; ".join(bad_logs[:3]))

    # ---------- E6 反向用例:同一把尺子必须能判红 ----------
    poisoned = {"model": "x", "input": QUESTION + " " + (_sample_chunks(1) or ["库内原文片段"])[0],
                "tools": [{"type": "web_search"}]}
    ck(bool(scan(poisoned)), "E6 反向:请求体里夹库内 chunk → 同一把尺子必须判红(尺子不是空转)",
       f"命中 {len(scan(poisoned))} 条")
    ck(not scan({"model": "x", "input": QUESTION, "tools": [{"type": "web_search"}],
                 "tool_choice": {"type": "web_search"}}),
       "E6b 干净请求体 → 同一把尺子判绿(无假阳性)")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "question": QUESTION,
        "forbidden_samples": [{"label": a, "len": len(b)} for a, b in FORBIDDEN],
        "captured_payloads": [{"url": c["url"], "json": c["json"],
                               "header_keys": sorted((c["headers"] or {}).keys())}
                              for c in CAPTURED],
        "log_lines_sample": logs[:10],
        "fails": FAILS,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[report] {OUT}")
    shutil.rmtree(_TMP.parent, ignore_errors=True)
    print(f"\n[compliance] {'ALL PASS' if not FAILS else 'FAIL: ' + ', '.join(FAILS)}")
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
