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
print("C0-② rind-07 两段式「不得夹带无据断言」（坑 54 宽词修正）")
rind07 = next(c for c in r2c if c["id"] == "rind-07")
r7_absent = rind07.get("expect_absent_keywords") or []
r7_coocur = rind07.get("expect_absent_keywords_cooccur") or []
check("无条件段 >=3 个词（规格硬要求）", len(r7_absent) >= 3, str(r7_absent))
check("无条件段不含宽词 证明/录取/钥匙/图书馆",
      not ({"证明", "录取", "钥匙", "图书馆"} & set(r7_absent)), str(r7_absent))
check("共现段已配置（证明/录取/钥匙/图书馆）",
      {p[0] for p in r7_coocur} >= {"证明", "录取"}, str([p[0] for p in r7_coocur]))

# a) 正向:真正的拒答模板(无处置动作、无宽词共现)必须 PASS
TEMPLATE_OK = ("知识库中暂无相关内容，无法就该问题给出有依据的回答。\n"
               "（缺口说明：知识库中未检索到与该问题相关的分块。为避免误导，"
               "本回答由系统模板生成，未采用模型自由发挥。）\n"
               "建议通过学校官方网站（https://www.swjtu.edu.cn/）或对应职能部门页面查询联系方式。\n"
               "如需更精确的解答，请补充：具体政策/通知的名称或文号、适用的年级学段、办理时间等背景信息。")
ok8, d8 = R.judge_refusal_indomain(rind07, TEMPLATE_OK, [])
check("拒答模板原文 → PASS", ok8, d8)

# b) 反向(规格点名要的那条):含「需医院诊断证明」的**正当引用**不得被误判为夹带。
#    ⚠ 用例写法踩了两次坑,都记在这里:
#      ① `refusal_indomain` 先看有没有拒答 —— 直接喂纯作答答案会 FAIL 在"未拒答"上,
#         根本走不到 absent 检查(等于没测到目标代码路径);
#      ② 拒答说明里**不能出现零命中处置词**——本用例答案要如实说"哪部分无据",
#         若写成「暂无离校物品**交回**的相关内容」,"交回"本身就是零命中处置词,
#         正确判红。缺口描述必须避开处置动词(用"物品处置"这类中性说法)。
#    故构造"拒答 + 仍如实给出有出处引用"的答案(检索增强后的真实形态:库内只有休学
#    材料能答、离校处置类诉求确实无据),确保断言真正落在 absent 判据上。
JUST = ("知识库中暂无离校物品处置的相关内容，无法就该部分给出有依据的回答。\n"
        "（缺口说明：现有条款只覆盖因病休学的材料要求，未覆盖毕业生离校物品处置。）\n"
        "另需说明：因病休学需提交医院诊断证明书，由二级甲等医院开具并加盖公章[1]；"
        "证明材料齐全后由辅导员提交学院审批[2]。该规定为学籍管理要求，"
        "与离校事项无关，请以学校最新通知为准。")
ok9, d9 = R.judge_refusal_indomain(
    rind07, JUST, [{"title": "西南交通大学研究生学籍管理规定"}, {"title": "西南交通大学学生请假管理办法"}])
check("正当引用「需医院诊断证明」→ PASS（宽词不再误伤）", ok9, d9)

# c) 反向:真正的夹带——零命中处置词出现即 FAIL
for word, tag in (("交回", "宿舍钥匙应在离校时交回"), ("退卡", "饭卡需退卡"),
                  ("提档", "档案须提档"), ("调档", "可申请调档")):
    ans = "知识库中暂无相关内容。离校时" + tag + "，具体请咨询相关部门。"
    bad, dbad = R.judge_refusal_indomain(rind07, ans, [])
    check(f"夹带处置词「{word}」→ FAIL", bad is False, dbad)

# d) 反向:宽词 + 零命中处置词共现才算夹带(共现判据的正例)
ok10, d10 = R.judge_refusal_indomain(
    rind07, "知识库中暂无相关内容。录取通知书相关材料需交回后再办。", [])
check("「证明/录取」与零命中处置词共现 → FAIL", ok10 is False, d10)

# e) 反向:共现段不能被"只有宽词、无处置词"绕过成假阳性
#    ⚠ 判例一:只出现「录取」+「报到」这种**有正当出处**的组合(教育部令 41 号 5 块)
#       必须 PASS —— 这条曾把共现侧的 `报到` 打成假阳性,是本单真实修掉的一个缺陷。
ok11, d11 = R.judge_refusal_indomain(
    rind07, "知识库中暂无相关内容。如需在校办理录取报到，请以学校最新通知为准。", [])
check("仅宽词「录取」+ 有出处的「报到」共现 → PASS（不误伤）", ok11, d11)
#    判例二:「图书馆」+「借阅」**应当 FAIL** —— 这正是本用例 7 项诉求之一
#       (「图书馆借的东西在哪归还」),库内 0 条款可答,答案一旦认领就是夹带无据断言。
#       ⚠ 这条判例第一版我写成了"应 PASS",自测当场判红——**是我把判例写反了**,
#       不是判据错。记在这里:共现段不是"越宽越安全",它只在"处置动作"上收紧。
ok11b, d11b = R.judge_refusal_indomain(
    rind07, "知识库中暂无相关内容。图书馆借阅的东西请在离校时归还前台。", [])
check("「图书馆」+「借阅」共现 → FAIL（第 6 项诉求被认领）", ok11b is False, d11b)

# f) 反向:同一断言在 qa 型也生效（_check_absent_keywords 两型共用，防只修一型）
qa_probe = {"expect_keywords": ["诊断证明"], "expect_absent_keywords": ["交回"],
            "expect_absent_keywords_cooccur": [["录取", ["提档"]]]}
ok12, d12 = R.judge_qa(qa_probe, "因病休学需医院诊断证明书[1]。", [{"title": "研究生学籍管理规定"}])
check("qa 型:正当「诊断证明」→ PASS", ok12, d12)
ok13, d13 = R.judge_qa(qa_probe, "需医院诊断证明书[1]；录取后需提档。", [{"title": "研究生学籍管理规定"}])
check("qa 型:共现段生效（录取+提档）→ FAIL", ok13 is False, d13)

print("\n" + "=" * 72)
print(f"[selftest] {'全部通过 ✓' if not fails else '存在失败 ✗'}")
for f in fails:
    print("  -", f)
sys.exit(1 if fails else 0)