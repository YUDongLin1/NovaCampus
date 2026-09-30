#!/usr/bin/env python3
"""P4d-fix ①配套探针：为「替代 rind-02 的域内无据用例」选问句。

背景：rind-02(学平险学生原句) 迁移为 qa 型后，P4a 门控的 `refusal_indomain` 覆盖会
少一条。只迁移不补 = 覆盖变薄(坑 22)。故必须新增一条**域内真无据 + 学生口吻长问句**。

选问句的事实依据(不能靠猜)：先直查 KB 里到底有没有相关文档，再用候选问句实测
「是否拒答 / 来源数 / attempts」，避免又造一条"库内其实有据"的假拒答用例
——那正是 rind-02 被打回的根因(F2 修好后"库内无据"前提失效)。
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import httpx

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = "http://127.0.0.1:8902"
HERE = Path(__file__).parent
DB = HERE.parent.parent / "novaagent" / "data" / "agent.db"

# 候选问句：学生口吻、长问句、域内校园事务。
# 逐条附"为什么预期库内无据"，并在下面用查库 + 实测双向验证。
CANDIDATES = [
    ("cand-A", "我在成都七中读高一，我妈让我把户口迁到学校这边，请问需要办哪些手续"
               "、带什么原件、找哪个部门的老师盖章？宿舍洗衣机的押金在哪儿交？"),
    ("cand-B", "我下学期要交换去西班牙，学校这边需要我办什么手续？签证材料"
               "和学院那边谁负责？宿舍空调的遥控器丢了要押金吗，在哪交？"),
    ("cand-C", "我考研上岸外校了，录取通知书要学校开什么证明才能用来办报到和调档案？"
               "毕业离校时宿舍钥匙、饭卡、图书馆借的东西分别要在哪几个地方交回？"),
]


def kb_titles_containing(keywords: list[str]) -> list[str]:
    con = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True)
    try:
        out = []
        for (t,) in con.execute("select title from documents"):
            if any(k in t for k in keywords):
                out.append(t)
        return out
    finally:
        con.close()


def main() -> int:
    report = {"db_probe": {}, "live": {}}
    # 1) 查库：确认这些主题 KB 里确实没有
    probe_keys = ["户口", "迁移", "交换", "留学", "签证", "录取", "调档", "报到",
                  "洗衣机", "空调", "遥控器", "钥匙", "饭卡", "图书馆"]
    hits = kb_titles_containing(probe_keys)
    report["db_probe"] = {"keywords": probe_keys, "hit_titles": hits,
                          "hit_count": len(hits)}
    print("=" * 72)
    print("[查库] 主题关键词 → 命中文档标题")
    print(f"  关键词: {probe_keys}")
    print(f"  命中 {len(hits)} 条: {hits}")

    # 2) 实测：逐条问，看是否拒答
    with httpx.Client(timeout=180, trust_env=False) as c:
        tok = c.post(f"{BASE}/api/login",
                     json={"username": "student", "password": "student123"}).json()["token"]
        for cid, q in CANDIDATES:
            r = c.post(f"{BASE}/api/chat",
                       headers={"Authorization": f"Bearer {tok}"}, json={"question": q})
            r.raise_for_status()
            d = r.json()
            ans = d.get("answer", "")
            srcs = [s.get("title") for s in d.get("sources") or []]
            ctx = d.get("context") or {}
            marks = [m for m in ("未在知识库", "未检索到", "未覆盖", "暂无", "知识库中未",
                                 "无法回答", "不在知识库", "没有相关") if m in ans]
            rec = {"question": q, "sources": srcs, "source_count": len(srcs),
                   "marks": marks, "declined": bool(marks) or not srcs,
                   "attempts": ctx.get("attempts"), "intent": ctx.get("intent"),
                   "rewritten": ctx.get("rewritten"), "answer_len": len(ans),
                   "answer_head": ans[:300]}
            report["live"][cid] = rec
            print("=" * 72)
            print(f"{cid} | sources={len(srcs)} marks={marks} declined={rec['declined']} "
                  f"attempts={rec['attempts']} rewritten={rec['rewritten']}")
            print(f"  问: {q}")
            print(f"  来源: {srcs}")
            print(f"  答案头: {ans[:300]}")

    dest = HERE / "evidence" / "after" / "rind_replacement_probe.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[evidence] {dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())