#!/usr/bin/env python3
"""P4d-fix Review 独立探针：`rind-07` 的"域内无据"前提到底成不成立。

为什么查这条：`rind-02` 上一轮被打回，根因就是**前提失效**——用例按"库内无据"写，
但 KB 里其实有 4 篇学平险文档，F2 修好后必然转红。`rind-07` 是**用来补这条覆盖的替代用例**，
如果它也是伪前提，等于用同一个错误换了个 id。

实现方的自证只查了 **65 篇标题**（`evidence/after/rind_replacement_probe.json`）。
本探针把口径推到 **正文层**（这才是检索真正能召回的东西），并区分三种"无据"：

  L1 标题层无据        —— 实现方测的，最弱
  L2 主题词正文层零命中 —— 更强
  L3 语义层无对应条款  —— 只有这一层成立，"要求拒答"才是对的断言

关键风险：主题词在正文里有大量**巧合命中**（「钥匙」「空调」都在《学生公寓管理办法》里，
「档案」10 篇、「录取」6 篇、「离校」12 篇），但巧合 ≠ 条款。P4e 之后检索变强，
召回了这些文档、答案据实引用，就可能被 `expect_absent_keywords` 判成"夹带无据断言"。
所以本探针同时量化这个**前瞻风险**，作为交给下一单的哨兵项。

只读库副本，绝不写 agent.db。
"""
from __future__ import annotations

import io
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

OUT = ROOT / "docs" / "p4d" / "evidence" / "review" / "rind07_premise.json"

# 问句里的实际诉求。**token 选的是"只有答案真能办这事才会出现"的词**，
# 不用「证明」——它在全库 42 块里出现（休学要"诊断证明"、开除发"学习证明"），
# 拿它判"有条款"会假阳，拿它判"夹带无据"会误伤真引用（本探针第 4 节的发现）。
ASKS = {
    "考研录取需要学校开什么证明": ["录取", "调档", "提档"],
    "拿录取通知办报到": ["报到"],
    "调档案/提档": ["调档", "提档", "档案转递", "转递"],
    "离校时宿舍钥匙在哪里交回": ["钥匙"],
    "离校时饭卡在哪里交回/退卡": ["饭卡", "校园卡", "一卡通"],
    "图书馆借阅的东西在哪里归还": ["图书馆"],
    "洗衣机/空调/遥控器离校怎么处理": ["洗衣机", "遥控器", "空调"],
}
# 实现方自测用过的 13 个标题层关键词（用于复算其结论）
THEIR_KWS = ["户口", "迁移", "交换", "留学", "签证", "录取", "调档", "报到",
             "洗衣机", "空调", "遥控器", "钥匙", "饭卡", "图书馆"]

results: dict = {}
fails: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print("  [%s] %s%s" % ("OK " if cond else "FAIL", name, (" — " + detail) if detail else ""))
    if not cond:
        fails.append("%s: %s" % (name, detail))


def main() -> None:
    dst = os.path.join(tempfile.gettempdir(), "p4dfix_review_rind07.db")
    shutil.copyfile(str(ROOT / "novaagent" / "data" / "agent.db"), dst)
    co = sqlite3.connect(dst)
    co.row_factory = sqlite3.Row

    docs = {r["id"]: dict(r) for r in co.execute(
        "select id,title,role_min from documents where role_min='student'")}
    print("student 可见文档 =", len(docs), "| 全库文档 =",
          co.execute("select count(*) c from documents").fetchone()["c"])

    # 逐词统计：标题命中 / 正文命中块数（只看学生可见文档）
    per_kw = {}
    for kw in sorted(set(THEIR_KWS) | {w for v in ASKS.values() for w in v}):
        titles = [d["title"] for d in docs.values() if kw in d["title"]]
        body = co.execute(
            "select d.id,d.title,count(*) c from chunks c join documents d on d.id=c.doc_id "
            "where d.role_min='student' and c.content like ? group by d.id order by c desc",
            ("%" + kw + "%",)).fetchall()
        per_kw[kw] = {"title_hits": len(titles), "body_docs": len(body),
                      "body_chunks": sum(r["c"] for r in body),
                      "top_doc": body[0]["title"][:40] if body else ""}

    print("\n=== 逐词覆盖（L1 标题 / L2 正文）===")
    for kw, v in sorted(per_kw.items(), key=lambda x: -x[1]["body_chunks"]):
        print("  %-5s title=%-2d body_docs=%-2d body_chunks=%-3d %s"
              % (kw, v["title_hits"], v["body_docs"], v["body_chunks"], v["top_doc"]))
    results["per_keyword"] = per_kw

    # 复算实现方"13 词标题层 0 命中"
    zero_title = [k for k in THEIR_KWS if per_kw[k]["title_hits"] == 0]
    print("\n=== 复算实现方口径 ===")
    check("实现方'13 词标题层 0 命中'可复现", len(zero_title) == len(THEIR_KWS),
          "0 命中 %d/%d" % (len(zero_title), len(THEIR_KWS)))

    # L3：问句诉求是否有对应条款。判据是"存在一条回答该诉求的规定"，
    # 用"诉求专属动词/名词组合"在同一段落共现来近似（宁可宽，共现即算可疑）。
    print("\n=== L3 语义层：逐诉求查条款 ===")
    l3 = {}
    for ask, tokens in ASKS.items():
        # 正文同时含 诉求词 与 处置词（交回/归还/退还/办理/手续/流程/地点/处）视为疑似有条款
        hits = []
        for tok in tokens:
            rows = co.execute(
                "select d.title,c.content from chunks c join documents d on d.id=c.doc_id "
                "where d.role_min='student' and c.content like ?", ("%" + tok + "%",)).fetchall()
            for r in rows:
                i = r["content"].find(tok)
                win = r["content"][max(0, i - 120):i + 160]
                if re.search(r"(交回|退卡|退还|归还|注销|转递|提档|调档|开具(?!的)?[^，。;]{0,6}证明)", win) \
                        and "诊断证明" not in win and "学习证明" not in win:
                    hits.append((r["title"][:34], tok, win.replace("\n", " ")[:150]))
        l3[ask] = hits
        print("  %-22s 疑似条款 %d 处 %s" % (ask, len(hits), hits[0][0] if hits else ""))
    results["l3_suspect_clauses"] = {k: v[:3] for k, v in l3.items()}
    any_clause = [k for k, v in l3.items() if v]
    check("L3：没有任何学生可见条款能直接回答 7 项诉求之一", not any_clause,
          "疑似可答诉求=%s" % any_clause)

    # 前瞻风险量化：主题词在正文的巧合命中（检索将来可能召回）
    print("\n=== 前瞻风险（P4e 检索变强后可能被召回并据实引用）===")
    overlap = {k: v for k, v in per_kw.items() if v["body_chunks"] > 0}
    results["forward_risk_keywords"] = list(overlap)
    print("  正文有巧合命中的词 =", ", ".join(sorted(overlap)))
    print("  ⚠ 其中出现在 expect_absent_keywords 里的 =",
          ", ".join(sorted(k for k in overlap if k in
                           ("证明", "钥匙", "饭卡", "图书馆", "调档", "录取"))))

    # 「交回」全库零命中 → 离校物品清单确实无条款（这是 L3 成立的核心证据）
    print("\n=== 核心词频（'交回'类处置动词）===")
    freq = {}
    for kw in ("交回", "退还", "退卡", "提档", "调档", "转递", "开具证明"):
        n = co.execute("select count(*) c from chunks where content like ?",
                       ("%" + kw + "%",)).fetchone()["c"]
        freq[kw] = n
        print("  全库含'%s'的块 = %d" % (kw, n))
    results["disposal_term_freq"] = freq
    check("'交回'与'提档'全库 0 块（离校物品/调档流程确实无据）",
          freq["交回"] == 0 and freq["提档"] == 0,
          "交回=%d 提档=%d" % (freq["交回"], freq["提档"]))

    # === 第 4 节：expect_absent_keywords 每个词的"宽窄" ===
    # 「无据」成立不等于「断言」安全：absent 词若在库里高频出现，检索一增强就会误伤真引用。
    print("\n=== expect_absent_keywords 宽窄量化（student 可见块数）===")
    case = json.load(io.open(str(ROOT / "evals" / "cases.json"), encoding="utf-8"))["cases"]
    r7 = next(c for c in case if c["id"] == "rind-07")
    generic = {}
    for kw in r7["expect_absent_keywords"]:
        n = co.execute("select count(*) c from chunks c join documents d on d.id=c.doc_id "
                       "where d.role_min='student' and c.content like ?", ("%" + kw + "%",)).fetchone()["c"]
        generic[kw] = n
        print("  %-4s 学生可见块含该词 = %-3d %s" % (kw, n, "← 宽词，误伤风险" if n >= 5 else ""))
    results["absent_keyword_breadth"] = generic
    wide = [k for k, v in generic.items() if v >= 5]
    results["wide_absent_keywords"] = wide
    check("absent 词全部为库里零/低频出现的具体事项词（无宽词）", not wide,
          "宽词=%s 对应块数=%s" % (wide, {k: generic[k] for k in wide}))

    co.close()
    results["pass"] = not fails
    results["fails"] = fails
    OUT.parent.mkdir(parents=True, exist_ok=True)
    json.dump(results, io.open(str(OUT), "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("\n[rind07] %s  失败 %d 条 | 报告 %s" % ("全部通过 ✓" if not fails else "存在 FAIL ✗", len(fails), OUT))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
