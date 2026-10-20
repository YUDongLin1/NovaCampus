#!/usr/bin/env python3
"""P4d-fix ①：改 evals/cases.json（迁移 rind-02 + 新增 rind-07），并做旧用例零改动自证。

纪律（打回指令）：`cases.json` **只准新增/迁移，不得改动其它旧用例的断言字段**。
所以本脚本：
  1. 先对 cases.json 做**深度快照**；
  2. 只做两处动作：①把 rind-02 由 refusal_indomain **迁移**为 qa（同一 id，不新增重复条目）
     + ②在 rind-06 之后**新增** rind-07（替代 rind-02 迁走后的域内无据覆盖，防覆盖变薄·坑 22）；
  3. 改完再对**除 rind-02 以外的全部旧用例**逐字段深度比对，任何差异即报错退出（非零码），
     即"旧用例逐字段零改动"是脚本自己验的，不靠人眼。

用法: novaagent/.venv/Scripts/python.exe docs/p4d/patch_cases_p4d_fix.py [--check-only]
"""
from __future__ import annotations

import json
import sys
from copy import deepcopy
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CASES = Path(__file__).resolve().parent.parent.parent / "evals" / "cases.json"

# ① rind-02 迁移为 qa 型。
# 依据（实测 docs/p4d/evidence/after/answers_facts.json，温度 0，graph 编排，8902）：
#   attempts=2、rewritten=True、4 条来源（学平险理赔须知/2026 医保缴费通知/2016 学平险通知/医保假期提示）
#   答案 571 字，实质内容 456 字：区分了学平险 vs 医保两个独立项目、给 2026 医保缴费标准 448 元、
#   **明确声明 [1] 为 2012 年历史材料、[3] 为 2016 旧通知"不能作为现行依据"**、
#   **未复述 95585**（历史文件里的报案电话没被当现行）、出口指向保卫处/校医院/学管。
#   → "库内无据"前提已随 F2 修复失效（KB 确有 doc 114/115/110/111 四篇，role_min=student），
#     期望拒答与 C4 硬指标（学生原句必须命中）互斥，必须迁移。
# 断言设计：
#   expect_keywords  两组 any-of：①必须点名"学平险"这个险种 ②必须声明时效/以最新通知为准
#   expect_sources   学平险 + 医保两族材料都须被召回（归口说明需要两个来源支撑）
#   expect_absent_keywords  95585 —— **硬要求保留**：历史文件里的报案电话不得作现行给出
# 新增 expect_absent_keywords 字段由 run_evals.py 的 judge_qa 支持（P4d-fix ④ 同批实现）。
RIND02_MIGRATED = {
    "id": "rind-02",
    "type": "qa",
    "role": "student",
    "question": "我们学校有学平险吗，我看我们计财处只有医保这项",
    "expect_keywords": [
        ["学平险", "学生平安保险", "学生平安团体保险"],
        ["历史", "旧", "现行", "最新通知", "以保卫处", "以校医院"],
    ],
    "expect_sources": ["学平险", "医保"],
    "expect_absent_keywords": ["95585"],
    "note": ("P4d-fix ①:由 refusal_indomain **迁移为 qa**。原断言(期望拒答+保卫处出口 87600392)"
             "基于 F2 缺陷现场(『库内无据』),F2 修好后该前提失效——KB 实有 doc114 学平险理赔须知/"
             "doc115 2016 学平险通知/doc110 2026 医保缴费/doc111 医保假期提示 四篇(role_min=student),"
             "与 C4 硬指标『学生原句必须命中』互斥。实测:attempts=2、rewritten=True、4 条来源、"
             "答案 571 字(实质 456)区分学平险 vs 医保、声明 2012/2016 文件为历史材料不可作现行、"
             "出口指向保卫处/校医院。**expect_absent_keywords=[95585] 为硬要求**:"
             "doc114 正文含 95585 报案电话,该文件带【时效声明】要求不得作现行给出。"
             "域内无据覆盖由新增 rind-07 承接(坑 22:只迁移不补=覆盖变薄)。"),
}

# ② 新增 rind-07：替代 rind-02 迁走后空出的 `refusal_indomain` 覆盖。
# 依据（实测 docs/p4d/evidence/after/rind_replacement_probe.json）：
#   查库 13 个主题关键词（户口/迁移/交换/留学/签证/录取/调档/报到/洗衣机/空调/遥控器/钥匙/饭卡/图书馆）
#   → 命中 KB 标题 **0 条**（真域内无据，非"库内其实有据"——那正是 rind-02 被打回的根因）；
#   实测 sources=0、marks=暂无、attempts=1、rewritten=False，
#   走 refusal.build_refusal 确定性模板（「相关度达标的来源不足 2 条」+ 系统模板指纹 + 官网出口）。
# 选 cand-C（考研上岸外校 + 毕业离校交回物品）：与迁走的 rind-02 同属"毕业生/在校生办事"域内事务，
# 且是学生口吻长问句（多事项叠加），比单词式短问更能压住"部分命中就作答"的倾向。
RIND07_NEW = {
    "id": "rind-07",
    "type": "refusal_indomain",
    "role": "student",
    "question": ("我考研上岸外校了，录取通知书要学校开什么证明才能用来办报到和调档案？"
                 "毕业离校时宿舍钥匙、饭卡、图书馆借的东西分别要在哪几个地方交回？"),
    "expect_absent_keywords": ["证明", "钥匙", "饭卡", "图书馆", "调档", "录取"],
    "note": ("P4d-fix ① 新增:承接 rind-02 迁出后的域内无据覆盖(坑 22)。**先查库后实测**:"
             "13 个主题关键词(户口/迁移/交换/留学/签证/录取/调档/报到/洗衣机/空调/遥控器/钥匙/"
             "饭卡/图书馆)在 KB 65 篇标题中命中 **0 条** → 真的域内无据,不是 rind-02 那种"
             "『库内其实有 4 篇学平险却要求拒答』的伪前提。实测 sources=0、走确定性模板、"
             "attempts=1。学生口吻长问句(考研录取+报到调档+离校物品交回三事项叠加),"
             "expect_absent_keywords 覆盖这 6 个高频臆造点:答中任何一个即判夹带无据断言。"),
}


def main() -> int:
    check_only = "--check-only" in sys.argv
    raw = CASES.read_text(encoding="utf-8")
    spec = json.loads(raw)
    before_cases = deepcopy(spec["cases"])
    before_version = spec["version"]

    ids_before = [c["id"] for c in before_cases]
    assert len(ids_before) == len(set(ids_before)), "用例 id 有重复，先修数据"
    print(f"[before] version={before_version} 用例数={len(before_cases)}")

    # ---- 动作 ①：rind-02 迁移（保持 id 与在列表中的位置不变）----
    idx = next(i for i, c in enumerate(before_cases) if c["id"] == "rind-02")
    migrated = deepcopy(RIND02_MIGRATED)
    print(f"[①] rind-02: {before_cases[idx]['type']} → {migrated['type']}"
          f"(id/question/role 不变,位置 [{idx}] 不变)")

    # ---- 动作 ②：新增 rind-07(插在 rind-06 之后,保持同组聚拢)----
    assert not any(c["id"] == "rind-07" for c in before_cases), "rind-07 已存在,中止"
    ins = max(i for i, c in enumerate(before_cases) if c["id"].startswith("rind-")) + 1
    print(f"[②] 新增 rind-07 于位置 [{ins}](rind-06 之后)")

    if check_only:
        print("[check-only] 不写盘")
        return 0

    after_cases = deepcopy(before_cases)
    after_cases[idx] = migrated
    after_cases.insert(ins, deepcopy(RIND07_NEW))

    # ---- 自证：除 rind-02 外，全部旧用例逐字段零改动 ----
    diffs: list[str] = []
    before_map = {c["id"]: c for c in before_cases}
    after_map = {c["id"]: c for c in after_cases}
    assert set(after_map) - set(before_map) == {"rind-07"}, "新增项不止 rind-07"
    assert not (set(before_map) - set(after_map)), "有旧用例被删除"
    for cid, b in before_map.items():
        a = after_map[cid]
        if cid == "rind-02":
            continue  # 有意迁移
        if a != b:
            keys = set(a) | set(b)
            for k in sorted(keys):
                if a.get(k) != b.get(k):
                    diffs.append(f"{cid}.{k}: {b.get(k)!r} → {a.get(k)!r}")
    if diffs:
        print("[FAIL] 旧用例被意外改动:")
        for d in diffs:
            print("  -", d)
        return 1
    print(f"[自证] 除 rind-02(有意迁移)外 {len(before_map) - 1} 条旧用例逐字段零改动 ✓")

    # rind-02 迁移的"未越权"自证：只允许改 type 与断言字段，question/role 必须原样
    old_r2 = before_map["rind-02"]
    for k in ("question", "role", "id"):
        if migrated.get(k) != old_r2.get(k):
            print(f"[FAIL] rind-02.{k} 被改动（迁移不得改问句/角色）")
            return 1
    print("[自证] rind-02 迁移未改 question/role/id ✓")

    # ---- 计数与 version ----
    n = len(after_cases)
    from collections import Counter
    cnt = Counter(c["type"] for c in after_cases)
    spec["cases"] = after_cases
    spec["version"] = "v2.1"          # 口径变更：47 → 48（R@k 归一 + rind-02 迁移 + rind-07 新增）
    spec["description"] = (
        "NovaAgent 评测集:48 条(qa 18 / refusal_indomain 6 / refusal 6 / permission_api 4 / "
        "kb_hidden 3 / scoped_qa 3 / P4b 新路径 4 / P4d 意图直答 2 + 改写重试 2);"
        "P4a 增 F1/F2/F3 配对用例与域内无据拒答;P4c 增 @ scope;P4d 增 intent/rewrite 两类;"
        "**P4d-fix ① rind-02 由 refusal_indomain 迁移为 qa(F2 修复后『库内无据』前提失效)"
        "并新增 rind-07 承接域内无据覆盖(坑 22:迁出 1 补 1,refusal_indomain 仍为 6 条,覆盖未变薄);"
        "**P4d-fix ② compute_recall 两侧标题归一(全/半角括号·书名号·空白),"
        "R@k 0.9412 → 1.0 属口径变更(EVAL_BASELINE §十五)**"
    )
    print(f"[after ] version={spec['version']} 用例数={n}")
    print(f"[after ] 类型分布: {dict(sorted(cnt.items()))}")

    CASES.write_text(json.dumps(spec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[write] {CASES}")
    return 0


if __name__ == "__main__":
    sys.exit(main())