#!/usr/bin/env python3
"""P4d-fix 尺子自测（纯本地、不连服务、不烧整轮评测）。

在集中跑之前先把两把新尺子单独验一遍，避免"改完尺子才发现误伤"：

  ② `compute_recall` 标题归一：
     a) qa-09 的「离校请销假」× 全角标题必须命中（修前恒 0.0）；
     b) **全部 19 条 qa 的 expect_sources 归一前后逐条比对**——除 qa-09 外不得有任何变化
        （防归一过头把本该 0 的判成 1，即"修尺子修出新假阳性"）；
     c) 反向用例：构造一个库内确实没有的串，归一后仍必须 0.0。

  ④ 非答案检测：
     a) 用实测保存的三条真实答案回放（qa-12 非答案 / rind-02 真答案 / qa-13 真答案），
        断言只有 qa-12 被判非答案；
     b) 反向：一条正常含免责句但有实质内容的答案必须 PASS。

  ① judge_qa 的 expect_absent_keywords：95585 出现即 FAIL、不出现即 PASS。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT / "evals"))

import run_evals as R  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
FACTS = json.loads((HERE / "evidence" / "after" / "answers_facts.json").read_text(encoding="utf-8"))
BY_ID = {r["id"]: r for r in FACTS}

fails: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  [{'OK ' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    if not cond:
        fails.append(f"{name}: {detail}")


print("=" * 72)
print("② compute_recall 标题归一")

# a) qa-09 缺陷场景
qa09 = {"expect_sources": ["离校请销假"]}
srcs09 = [{"title": "西南交通大学学生离校请（销）假管理办法（试行）（西交校学生〔2018〕224号）"}]
r = R.compute_recall(qa09, srcs09)
check("qa-09 全角标题 × 半角期望串 → 命中", r == 1.0, f"R@k={r}")

# 归一函数本身的样例（normalize_title 返回主形态 C；多形态匹配由 _title_forms 承担）
check("normalize_title 去书名号", R.normalize_title("《西南交通大学学生纪律处分规定》") == "西南交通大学学生纪律处分规定")
check("normalize_title 全角括号→半角（形态C）", R.normalize_title("请（销）假") == "请(销)假",
      R.normalize_title("请（销）假"))
check("normalize_title 六角括号→方括号", R.normalize_title("〔2025〕15 号") == "[2025]15号",
      R.normalize_title("〔2025〕15 号"))
check("_title_forms 含形态A(去括号保留内容)", "离校请销假" in R._title_forms("离校请（销）假"),
      R._title_forms("离校请（销）假"))
check("_title_forms 含形态B(删括号连内容)", "离校请假" in R._title_forms("离校请（销）假"),
      R._title_forms("离校请（销）假"))
check("_title_forms 保住 (学平险) 插入语", any("学平险" in f for f in R._title_forms("理赔须知(学平险)")),
      R._title_forms("理赔须知(学平险)"))

# b) 全部 qa 用例：归一前后逐条比对（除 qa-09 外必须完全一致）
spec = json.loads((ROOT / "evals" / "cases.json").read_text(encoding="utf-8"))
print("\n  [全部 qa 用例] 归一前 vs 归一后（sources 取实测/构造的 KB 标题池）")
pool_titles = [
    "西南交通大学学生离校请（销）假管理办法（试行）（西交校学生〔2018〕224号）",
    "西南交通大学研究生学籍管理规定（西交校研〔2023〕2号）",
    "西南交通大学研究生奖学金评定办法",
    "西南交通大学本科生国家奖助学金评审管理办法（西交校学生〔2025〕16 号）",
    "西南交通大学本科生奖助学金评审管理办法（西交校学生〔2025〕15 号）",
    "关于2026年度大学生医疗保险缴费的通知",
    "大学生意外伤害保险理赔须知(学平险)",
    "西南交通大学学生申诉管理规定（西交校〔2020〕12号）",
    "西南交通大学家庭经济困难学生学费缓缴实施办法（西交校学生〔2025〕23号）",
    "西南交通大学学生服务消过管理规定（西交校学生〔2023〕13 号）",
]
changed = []
for c in spec["cases"]:
    if c["type"] != "qa":
        continue
    exp = c.get("expect_sources") or []
    if not exp:
        continue
    srcs = [{"title": t} for t in pool_titles]
    raw = round(sum(1 for sub in exp if any(sub in t["title"] for t in srcs)) / len(exp), 4)
    norm = R.compute_recall(c, srcs)
    flag = "" if raw == norm else "  ← 归一生效"
    print(f"    {c['id']:7s} expect={exp} raw={raw} norm={norm}{flag}")
    if raw != norm:
        changed.append(c["id"])
check("归一仅影响 qa-09", changed == ["qa-09"], f"实际变化={changed}")

# c) 反向：库内确实没有的串，归一后必须仍 0.0
r_neg = R.compute_recall({"expect_sources": ["不存在的研究生课程选修办法"]}, [{"title": "西南交通大学研究生学籍管理规定（西交校研〔2023〕2号）"}])
check("反向用例仍为 0.0（归一没造假阳性）", r_neg == 0.0, f"R@k={r_neg}")

print("\n" + "=" * 72)
print("④ 非答案检测（回放实测答案）")
q12 = BY_ID["qa-12"]["answer"]
r02 = BY_ID["rind-02"]["answer"]
q13 = BY_ID["qa-13"]["answer"]
print(f"  长度: qa-12={len(q12)}(实质 {R.substantive_len(q12)}) / "
      f"rind-02={len(r02)}(实质 {R.substantive_len(r02)}) / "
      f"qa-13={len(q13)}(实质 {R.substantive_len(q13)})")
check("qa-12 判非答案", R.judge_qa({"expect_keywords": ["奖助学金"]}, q12, [{"title": "本科生奖助学金办法"}])[0] is False,
      str(R.judge_qa({"expect_keywords": ["奖助学金"]}, q12, [{"title": "本科生奖助学金办法"}])[1]))
ok2, d2 = R.judge_qa({"expect_keywords": [["学平险", "学生平安保险"], ["历史", "最新通知"]]}, r02,
                     [{"title": "大学生意外伤害保险理赔须知(学平险)"}])
check("rind-02 真答案不被误伤", ok2, d2)
ok3, d3 = R.judge_qa({"expect_keywords": ["电器"]}, q13, [{"title": "学生公寓管理办法"}])
check("qa-13 真答案不被误伤（末行声明未覆盖）", ok3, d3)

print("\n  [反向] 含免责句但有实质内容 + 引用标记")
ok4, d4 = R.judge_qa({"expect_keywords": ["学平险"]},
                     "学平险理赔需出院证、诊断证明书、费用发票等材料[1]；未在知识库覆盖的现行投保方式请以最新通知为准。",
                     [{"title": "大学生意外伤害保险理赔须知(学平险)"}])
check("有引用标记的短答案 → PASS（长度不作主判据）", ok4, d4)

print("\n  [反向] 短实质 + 免责句（无数字无引用）")
ok4b, d4b = R.judge_qa({"expect_keywords": ["学平险"]},
                       "学平险由学校统一组织投保。投保方式未在知识库覆盖，请以最新通知为准。",
                       [{"title": "大学生意外伤害保险理赔须知(学平险)"}])
check("无引用标记且无数字 → 判非答案（宁可严）", ok4b is False, d4b)

print("\n  [反向] 无来源仍必须 FAIL")
ok5, d5 = R.judge_qa({"expect_keywords": ["奖助学金"]}, "研究生奖助学金未在知识库覆盖，请以最新通知为准。", [])
check("零来源 → FAIL", ok5 is False, d5)

print("\n" + "=" * 72)
print("① judge_qa 的 expect_absent_keywords（95585 不得作现行）")
r2c = json.loads((ROOT / "evals" / "cases.json").read_text(encoding="utf-8"))["cases"]
rind02 = next(c for c in r2c if c["id"] == "rind-02")
check("rind-02 已是 qa 型", rind02["type"] == "qa", rind02["type"])
ok6, d6 = R.judge_qa(rind02, r02, [{"title": "大学生意外伤害保险理赔须知(学平险)"},
                                 {"title": "关于2026年度大学生医疗保险缴费的通知"}])
check("实测答案（无 95585）→ PASS", ok6, d6)
bad = r02.replace("知识库", "知识库") + "\n出险请拨 95585 报案。"
ok7, d7 = R.judge_qa(rind02, bad, [{"title": "大学生意外伤害保险理赔须知(学平险)"}])
check("答案含 95585 → FAIL（硬断言生效）", ok7 is False, d7)
print(f"    失败详情: {d7}")

print("\n" + "=" * 72)
print(f"[selftest] {'全部通过 ✓' if not fails else '存在失败 ✗'}")
for f in fails:
    print("  -", f)
sys.exit(1 if fails else 0)