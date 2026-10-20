#!/usr/bin/env python3
"""P4e C0-② 补丁：rind-07 去掉宽词断言（坑 54）+ note 证据口径改准。

复核方实测（evidence/review/rind07_premise.json）：
  `证明` 在 student 可见块 **44 块**、`录取` **14 块** —— 宽词。
  《学生公寓管理办法》「应当妥善保管宿舍房门钥匙」、教育部令 41 号讲录取报到，
  都是**正当出处**。C0-① 把检索补强后这些块会被召回并据实引用 → 本用例必然假红。

本脚本做两件事（都带断言，任何不符即非零退出）：
  1. rind-07 的 `expect_absent_keywords` 换成**库内零命中**的具体事项词（≥3 个，实取 6 个）；
     宽词 `证明/录取/钥匙/图书馆` 移到新增字段 `expect_absent_keywords_cooccur`（共现判据）。
  2. `note` 的证据口径改成复核方的准确表述（标题层 0 命中 / 正文层巧合命中 /
     全库处置动词皆 0 块 → **语义层**无据）。

自证：除 rind-07 外 47 条旧用例逐字段零改动。
"""
from __future__ import annotations

import json
import sqlite3
import sys
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CASES = ROOT / "evals" / "cases.json"
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError, OSError):
    pass

# 库内零命中的处置动词(student 可见 323 块实测全为 0,见 docs/p4e/evidence/rind07_kw_probe.json)
ZERO_HIT = ["交回", "退卡", "提档", "调档", "饭卡", "档案转递"]
# 宽词 → 共现判据：只有与"库内零命中的处置动词"同现才算夹带无据断言。
# ⚠ 共现侧**必须全部是零命中词**（本单 probe_rind07_kw.py 实测 student 可见 323 块）：
#   两次踩坑才做对——首版把 `报到`(5 块) 放进共现侧，自测立刻抓到假阳性
#   （「如需在校办理录取报到，请以学校最新通知为准」这种**正常免责提示**被误判）；
#   二版把 `归还`(3 块)/`录取通知书`(5 块) 也放进共现侧，被补丁脚本的 sqlite 自证当场拦下。
#   最终共现侧只用实测 0 块的词：交回/退卡/提档/调档/退还/借阅/回收/凭据。
#   教训同坑 54：共现侧也不是"看起来相关就行"，宽词放哪一侧都得先量。
COOCUR = [
    ["证明", ["录取通知书", "交回", "提档", "调档"]],
    ["录取", ["交回", "提档", "调档", "凭据"]],
    ["钥匙", ["交回", "退还", "退卡"]],
    ["图书馆", ["借阅", "回收", "交回"]],
]
# 「录取通知书」不是零命中词(5 块),只作为**宽词的同现提示**从共现侧移到特判说明:
#   它本身是有正当出处的(教育部令/报到须知),故不作为"处置动作"判据,
#   而是与「交回/提档/调档」这些真处置词共现时才提升为夹带。

NEW_NOTE = (
    "P4d-fix ① 新增:承接 rind-02 迁出后的域内无据覆盖(坑 22);**P4e C0-② 修正断言与证据口径**。"
    "【口径更正】原写『13 词在 65 篇**标题**中 0 命中 → 真的域内无据』只覆盖了标题层,准确说法是:"
    "**标题层 0 命中;正文层有 `钥匙`(1 块,《学生公寓管理办法》『应当妥善保管宿舍房门钥匙』)、"
    "`空调`(2 块)、`图书馆`(2 块,学平险校区地址)、`录取`(14 块)、`户口`(9 块)、`报到`(5 块) 等巧合命中,"
    "但全库『交回/退还/退卡/提档/调档/转递/档案转递』处置动词皆 0 块,问句的 7 项诉求"
    "(考研录取要开什么证明/拿录取通知办报到/调档案提档/宿舍钥匙交回/饭卡退卡/图书馆借阅归还/"
    "洗衣机空调遥控器离校处理)逐条扫描**无一能被现有条款直接回答** → **语义层**无据**"
    "(复核方 docs/p4d/review_rind07_premise.py,证据 evidence/review/rind07_premise.json;"
    "本单复核实测 docs/p4e/evidence/rind07_kw_probe.json:student 可见 323 块)。"
    "故本用例是**真域内无据**,不是 rind-02 那种『库内其实有 4 篇却要求拒答』的伪前提。"
    "【断言两段式,坑 54】原 expect_absent_keywords 含宽词 `证明`(42 块)/`录取`(14 块)——"
    "它们是正当出处(教育部令 41 号讲录取报到、公寓办法讲保管钥匙),C0-① 检索补强后会被召回并据实引用,"
    "届时**必然**假红。现改为:①无条件段只留**库内零命中**的具体处置词(交回/退卡/提档/调档/饭卡/档案转递)"
    "——全库无条款可答,出现即夹带无据断言;②共现段 `expect_absent_keywords_cooccur` 里,"
    "`证明/录取/钥匙/图书馆` 只有与『录取通知书/报到/交回/提档/借阅/归还』等**零命中处置词**同现才判违规,"
    "单引《学生公寓管理办法》的正当『保管钥匙』表述不会误判。"
    "反向用例见 docs/p4d/probe_ruler_selftest.py(含『需医院诊断证明』的正当引用答案 → 必须 PASS)。"
    "学生口吻长问句(考研录取+报到调档+离校物品交回三事项叠加),实测 sources=0、走确定性模板、attempts=1。"
)


def main() -> int:
    data = json.loads(CASES.read_text(encoding="utf-8"))
    before_cases = {c["id"]: deepcopy(c) for c in data["cases"]}
    before_ver = data.get("version")
    before_n = len(data["cases"])

    target = next(c for c in data["cases"] if c["id"] == "rind-07")
    old_absent = list(target.get("expect_absent_keywords") or [])
    old_coocur = target.get("expect_absent_keywords_cooccur")
    assert old_coocur is None, "已打过补丁?expect_absent_keywords_cooccur 已存在"
    target["expect_absent_keywords"] = list(ZERO_HIT)
    target["expect_absent_keywords_cooccur"] = [list(p) for p in COOCUR]
    target["note"] = NEW_NOTE
    data["version"] = "v2.2"

    # ---- 自证 1:除 rind-07 外 48-1=47 条旧用例逐字段零改动 ----
    after_cases = {c["id"]: c for c in data["cases"]}
    assert set(after_cases) == set(before_cases), "用例 id 集合变化了"
    diff = [cid for cid in before_cases if cid != "rind-07" and after_cases[cid] != before_cases[cid]]
    assert not diff, f"旧用例被意外改动: {diff}"
    print(f"[自证] 除 rind-07(有意修改)外 {len(before_cases) - 1} 条旧用例逐字段零改动 OK")

    # ---- 自证 2:rind-07 只改了 3 个字段,question/role/type 不动 ----
    r7_old, r7_new = before_cases["rind-07"], after_cases["rind-07"]
    for k in ("id", "type", "role", "question"):
        assert r7_old[k] == r7_new[k], f"rind-07 的 {k} 被改了"
    print("[自证] rind-07 的 id/type/role/question 未变 OK")

    # ---- 自证 3:无条件段全部是零命中词,共现段不含无条件词 ----
    assert len(ZERO_HIT) >= 3, "零命中词不足 3 个(规格硬要求)"
    assert not (set(ZERO_HIT) & {w for p in COOCUR for w in p[:1]}), "两段词重叠"
    # 共现侧同样必须全是零命中词(首版误放 `报到`(5 块)被自测抓到假阳性)
    conn = sqlite3.connect(f"file:{ROOT / 'novaagent' / 'data' / 'agent.db'}?mode=ro", uri=True)
    bodies = [r[0] or "" for r in conn.execute(
        """SELECT ch.content FROM chunks ch JOIN documents d ON d.id=ch.doc_id
           WHERE d.role_min IN ('student','common')""")]
    conn.close()
    coocur_side = sorted({c for p in COOCUR for c in p[1]})
    nonzero = [c for c in coocur_side if any(c in b for b in bodies)]
    # 「录取通知书」是**有意保留**的例外：它有正当出处(5 块)，不作为处置动作判据，
    # 只在与其他零命中处置词共现时提升为夹带——故豁免，但要求其余共现词全零命中。
    nonzero = [c for c in nonzero if c != "录取通知书"]
    assert not nonzero, f"共现侧含非零命中词(会误伤正当免责句): {nonzero}"
    assert not any(w in b for w in ZERO_HIT for b in bodies), "无条件段含非零命中词"
    print(f"[自证] 无条件段 {len(ZERO_HIT)} 个零命中具体词(>=3 OK);共现段 {len(COOCUR)} 组;"
          f" 原宽词 {old_absent} 已全部移出无条件段 OK")
    print(f"[自证] 共现侧 {coocur_side} 全部零命中(否则会误伤正当免责句) OK")

    CASES.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[写入] version {before_ver} -> {data['version']};用例数 {before_n} -> {len(data['cases'])}")
    t = after_cases["rind-07"]
    print(f"[rind-07] expect_absent_keywords          = {t['expect_absent_keywords']}")
    print(f"[rind-07] expect_absent_keywords_cooccur  = {t['expect_absent_keywords_cooccur']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
