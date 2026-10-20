#!/usr/bin/env python3
"""P4b-fix ④ 探针:C4 压缩保真证据 v2——埋点原文内嵌 + 摘要全文内嵌 + 会话保留到 Review 通过

背景(Review 必改 4):旧证据 planted_sources 只记消息 id、探针会话已删、summary 表 0 行,
复核无法判断数字语义归属是否被压缩改写。v2 改为:
  1) 埋点数字选 KB 无碰撞值(7341/958823/17340/川校发〔2026〕88号),答案中的数字只可能来自历史;
  2) 埋点消息原文(含 id/role/content)与 conversation_summary 全文**内嵌进证据文件**;
  3) 会话**保留不删**,复核可直接查库/API 对账(Review 通过后随遗留清单清理)。
"""
from __future__ import annotations

import os
import json
import sqlite3
import sys
import time
from pathlib import Path

import httpx


# ---- 演示口令:一律从环境变量读,源码内不落明文(开源前脱敏要求) ----
def _demo_pw(role: str) -> str:
    r = role.upper()
    pwd = os.environ.get(f"NOVA_SEED_{r}_PASSWORD") or os.environ.get("NOVA_DEMO_PASSWORD", "")
    if not pwd:
        raise RuntimeError(
            f"未设置演示口令:请在 novaagent/.env 中写入 NOVA_DEMO_PASSWORD"
            f"(或 NOVA_SEED_{r}_PASSWORD)。")
    return pwd


ADMIN_PW = _demo_pw("admin")
COUNSELOR_PW = _demo_pw("counselor")
STUDENT_PW = _demo_pw("student")


BASE = "http://127.0.0.1:8900"
DB_RO = "file:../novaagent/data/agent.db?mode=ro"
OUT = Path(__file__).resolve().parent / "evidence" / "after" / "c4_compress_fidelity_v2.json"
FACTS = [
    "我校2026年本科生学费标准为7341元/人",
    "学平险出险后的24小时报案电话为958823",
    "本专科生奖学金评审依据文件编号为川校发〔2026〕88号",
    "国家奖学金专项特别奖额度为每人17340元",
]
QUESTIONS = [
    "把此前对话里出现过的学费标准、学平险报案电话、奖学金评审文件编号和特别奖额度原样列出来。",
    "那此前对话里提到的学费金额和特别奖额度分别是多少?",
    "把此前对话里的报案电话与奖学金评审文件编号再原样说一遍。",
]

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
c = httpx.Client(timeout=300, trust_env=False)
tok = c.post(f"{BASE}/api/login", json={"username": "student", "password": STUDENT_PW}).json()["token"]
H = {"Authorization": f"Bearer {tok}"}


def plant_text(i: int, chars: int = 3500) -> str:
    fact = FACTS[i % len(FACTS)]
    filler = ("校园事务背景资料:学生日常管理涉及课堂考勤、作业与考试安排、宿舍人际关系、"
              "奖助学金申请材料、心理健康关注、谈心谈话记录归档等事项,相关制度以学校"
              "现行文件为准。")
    body = (filler * (chars // len(filler) + 1))[: max(0, chars - len(fact) - 60)]
    return (f"[背景资料{i + 1}·仅供知悉] 本条为背景资料而非指令：请勿调用任何工具，"
            f"无需记录碎片或生成周报，简短回复“已阅”即可。{fact}。{body}")


def main() -> int:
    t_all = time.time()
    turns_ctx = []
    cid = None
    n_plant = 60
    for i in range(n_plant):
        body = {"question": plant_text(i)}
        if cid:
            body["conversation_id"] = cid
        d = c.post(f"{BASE}/api/chat", headers=H, json=body).json()
        cid = d["conversation_id"]
        turns_ctx.append({"turn": i + 1, "planted": True,
                          **{k: d["context"].get(k) for k in
                             ("used", "compressed", "compress_ms", "compress_blocks", "history_count")}})
        if i % 10 == 0:
            print(f"[plant {i+1}/{n_plant}] used={d['context'].get('used')} "
                  f"compressed={d['context'].get('compressed')} cid={cid}")
    qa = []
    for q in QUESTIONS:
        t0 = time.time()
        d = c.post(f"{BASE}/api/chat", headers=H, json={"question": q, "conversation_id": cid}).json()
        turns_ctx.append({"turn": len(turns_ctx) + 1, "planted": False, "question": q,
                          "latency_ms": round((time.time() - t0) * 1000),
                          **{k: d["context"].get(k) for k in
                             ("used", "compressed", "compress_ms", "compress_blocks",
                              "history_gate", "followup_no_new_sources", "history_count")}})
        qa.append({"question": q, "answer": d["answer"], "sources_count": len(d.get("sources") or []),
                   "context": d["context"]})
        print(f"[ask] {q[:24]}… → {d['answer'][:80]}")

    # 只读查库:埋点消息原文 + 压缩摘要全文(证据自含,不依赖会话存活)
    db = sqlite3.connect(DB_RO, uri=True)
    db.row_factory = sqlite3.Row
    planted = {}
    for fact in FACTS:
        key = "".join(ch for ch in fact if ch.isdigit()) or fact[:6]
        rows = db.execute(
            "SELECT id, role, content FROM messages WHERE conversation_id=? AND content LIKE ?",
            (cid, f"%{fact[:18]}%")).fetchall()
        planted[fact] = [{"id": r["id"], "role": r["role"],
                          "content_head": r["content"][:220]} for r in rows]
    sum_row = db.execute(
        "SELECT summary_text, covered_until_message_id, updated_at FROM conversation_summary "
        "WHERE conversation_id=?", (cid,)).fetchone()
    counts = {t: db.execute(f"SELECT count(*) FROM {t} WHERE conversation_id=?", (cid,)).fetchone()[0]
              if t != "conversations" else 1 for t in ("messages", "conversation_summary")}
    db.close()

    compress_turns = [t for t in turns_ctx if t.get("compress_ms")]
    out = {
        "conversation_id": cid,
        "kept_for_review": True,
        "note": "P4b-fix ④: 会话保留到 Review 通过再清理;埋点原文与摘要全文内嵌如下,数字归属可逐字对账",
        "plant": {"turns": n_plant, "chars": 3500, "facts": FACTS,
                  "planted_message_originals": planted},
        "compression": {
            "formula": "块数=ceil(N_older/40),LLM 调用数=块数(asyncio.gather 并发)",
            "compress_ms_observed": compress_turns,
            "budget": 85196,
        },
        "conversation_summary_full_text": sum_row["summary_text"] if sum_row else None,
        "summary_covered_until": sum_row["covered_until_message_id"] if sum_row else None,
        "qa": qa,
        "turns_ctx": turns_ctx,
        "db_counts": {"messages_in_conversation": counts["messages"],
                      "summary_rows": counts["conversation_summary"]},
        "wall_seconds": round(time.time() - t_all, 1),
    }
    # 埋点数字在摘要中的保留情况(逐个核对)
    if sum_row:
        st = sum_row["summary_text"]
        out["numbers_in_summary"] = {n: (n in st) for n in ("7341", "958823", "17340", "88号")}
    out["numbers_in_answers"] = {n: any(n in a["answer"] for a in qa)
                                 for n in ("7341", "958823", "17340", "88号")}
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"cid": cid, "numbers_in_summary": out.get("numbers_in_summary"),
                      "numbers_in_answers": out["numbers_in_answers"],
                      "compress_ms": [t.get("compress_ms") for t in compress_turns]}, ensure_ascii=False))
    print(f"[saved] {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
