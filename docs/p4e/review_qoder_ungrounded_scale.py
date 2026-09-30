#!/usr/bin/env python3
"""Qoder 独立探针：整轮里「有来源却零可核查事实」的答案到底出现多少次，以及 judge_qa 是否放过它。

起因：我这轮（不带测试钩子）跑完 55 用例，`evals/badcases.json` 多出 11 条 `ungrounded`
（= 闸门判无效、重生一次后仍无效），但 qa 仍然 18/18 全过。
若两者同时为真，说明**产品发出了空话、评测却说 PASS** —— 这是比阈值松紧更严重的问题，
必须实测量化，不能靠推断。（对应 HANDOFF 坑 39/45：断言不判红＝没有断言。）

做法：进程内直接驱动 agent（不走 HTTP，不脏会话），把 18 条 qa 问句各跑一次，
对每条答案同时算：
  A) 产品闸门口径 answer_is_grounded（有来源 且 含 [n] 或数字）
  B) 评测 judge_qa 口径（关键词/来源命中 + 非答案检测）
统计「A 判无效 但 B 判 PASS」的条数 —— 这就是假阳性的真实规模。
"""
import asyncio
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(r"E:/AILearn/NovaCampus")
sys.path.insert(0, str(ROOT / "novaagent"))
sys.path.insert(0, str(ROOT / "evals"))

import httpx  # noqa: E402
from novaagent import agent as A  # noqa: E402
from novaagent import config, db  # noqa: E402

import run_evals as R  # noqa: E402

OUT = ROOT / "docs" / "p4e" / "evidence" / "review" / "qoder_ungrounded_scale.json"
OUT.parent.mkdir(parents=True, exist_ok=True)

CASES = json.loads((ROOT / "evals" / "cases.json").read_text(encoding="utf-8"))["cases"]
QA = [c for c in CASES if c["type"] == "qa"]

DB_COPY = os.path.join(tempfile.gettempdir(), "p4e_ungrounded_scale.db")
shutil.copyfile(str(config.DB_PATH), DB_COPY)
config.DB_PATH = Path(DB_COPY)


async def main():
    db.connect()
    rows = []
    async with httpx.AsyncClient(timeout=240) as c:
        for case in QA:
            role = case.get("role", "student")
            pw = {"admin": "admin123", "counselor": "counselor123", "student": "student123"}[role]
            tok = (await c.post("http://127.0.0.1:8923/api/login",
                                json={"username": role, "password": pw})).json()["token"]
            j = (await c.post("http://127.0.0.1:8923/api/chat",
                              json={"question": case["question"]},
                              headers={"Authorization": "Bearer " + tok})).json()
            ans = j.get("answer") or ""
            srcs = j.get("sources") or []
            gate = (j.get("context") or {}).get("grounding_gate")
            grounded = A.answer_is_grounded(ans, srcs)          # 产品闸门口径
            ok_eval, detail = R.judge_qa(case, ans, srcs)        # 评测口径
            rows.append({
                "id": case["id"], "n_sources": len(srcs), "len": len(ans),
                "gate_grounded": grounded, "gate_hit_this_turn": bool((gate or {}).get("hit")),
                "judge_qa_pass": ok_eval, "detail": detail[:120],
                "answer_head": ans[:90].replace("\n", " "),
            })
            print("%-7s src=%d gate_grounded=%-5s judge_pass=%-5s %s"
                  % (case["id"], len(srcs), grounded, ok_eval, "" if grounded or not srcs else "  <== 有来源却零可核查事实"))
    db.close() if hasattr(db, "close") else None
    ungrounded = [r for r in rows if r["n_sources"] > 0 and not r["gate_grounded"]]
    escaped = [r for r in ungrounded if r["judge_qa_pass"]]
    rep = {
        "n_qa": len(rows), "with_sources": sum(1 for r in rows if r["n_sources"] > 0),
        "ungrounded_with_sources": len(ungrounded),
        "ungrounded_but_judge_pass": len(escaped),
        "ids_escaped": [r["id"] for r in escaped],
        "gate_hit_rate": sum(1 for r in rows if r["gate_hit_this_turn"]),
        "rows": rows,
        "note": ("口径 A=产品闸门 answer_is_grounded（有来源须含 [n] 或数字）；"
                 "口径 B=评测 judge_qa（关键词/来源命中 + 非答案检测）。"
                 "B 放过 A 判无效的条数即『空话仍 PASS』的规模。"),
    }
    json.dump(rep, open(str(OUT), "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("\n[结论] 有来源却零可核查事实 = %d 条；其中 judge_qa 仍判 PASS = %d 条（%s）"
          % (len(ungrounded), len(escaped), rep["ids_escaped"]))
    print("[report]", OUT)


asyncio.run(main())
