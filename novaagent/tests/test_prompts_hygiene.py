#!/usr/bin/env python
"""提示词卫生检查(零额度)。

不发任何 LLM / embedding / ASR 请求:全部断言都是**纯文本与纯函数**运算。
它守的是"提示词与代码契约对不上"这一整类事故 —— 这类事故在真实调用里表现为
502 或静默降级,而评测轮次要烧额度才能发现,太晚了。

跑法:
    novaagent/.venv/Scripts/python.exe tests/test_prompts_hygiene.py
退出码:0 = 全过;1 = 有红。
"""
from __future__ import annotations

import ast
import json
import re
import string
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
NOVA = HERE.parent
ROOT = NOVA.parent
sys.path.insert(0, str(NOVA))

RESULTS: list[tuple[bool, str, str]] = []


def check(cond, label, detail=""):
    RESULTS.append((bool(cond), label, "" if cond else str(detail)))
    print(f"[{'PASS' if cond else 'FAIL'}] {label}" + ("" if cond else f"  → {detail}"))


from novaagent import prompts as P  # noqa: E402
from novaagent import agent, minutes, talk_summary as ts  # noqa: E402

SNAPSHOT = HERE / "fixtures" / "p4e_agent_snapshot.py.txt"


def fields(tpl: str) -> set[str]:
    """模板里真正会被 .format 替换掉的字段名(双花括号是字面量,不算)。"""
    return {name for _, name, _, _ in string.Formatter().parse(tpl) if name}


def render(tpl: str) -> str:
    """按调用点的方式渲染一遍 —— 示例必须**渲染后**才是模型真正看到的文本。

    (渲染前 schema 的字面花括号是双写的,直接拿原文找 JSON 会找不到。)
    """
    return tpl.format(**{f: "样本" for f in fields(tpl)})


# ================================================== 1. 逐字保护段没被误改

# 这四段受 P4e 黄金快照锁着;此处只断言"快照里仍能找到逐字的规则段",
# 与 test_p4f_persona 的组装等价断言互补:那条查组装,这条查常量本体。
if SNAPSHOT.exists():
    snap = SNAPSHOT.read_text(encoding="utf-8")
    check(P._HARD_RULES in snap, "受保护段 _HARD_RULES 与 P4e 快照逐字一致",
          "_HARD_RULES 被改动 —— 属口径变更,须重跑基线并记账")
    check(P._BASE_STYLE in snap, "受保护段 _BASE_STYLE 与 P4e 快照逐字一致")
    check(P._BASE_IDENTITY in snap, "受保护段 _BASE_IDENTITY 与 P4e 快照逐字一致")
else:
    check(False, "P4e 黄金快照文件存在", str(SNAPSHOT))

check(agent._HARD_RULES is P._HARD_RULES,
      "agent 侧引用的是 prompts 里那一份(搬移后没留下第二份副本)",
      "agent.py 里仍有同名常量 —— 两份会分叉")

# ================================================== 2. 占位符契约(改前必炸的那类)

EXPECTED = {
    "SUMMARY_PROMPT": {"content"},
    "COMPRESS_PROMPT": {"history"},
    "HISTORY_GATE_NOTE": {"reason"},
    "EXPAND_PROMPT": {"category", "content"},
    "WEB_CONTEXT_BLOCK": {"urls"},
    "INTENT_PROMPT": {"q"},
    "REWRITE_PROMPT": {"q", "prev"},
    "MINUTES_PROMPT": {"raw"},
    "TOPIC_PROMPT": {"content"},
}
for name, want in EXPECTED.items():
    tpl = getattr(P, name)
    got = fields(tpl)
    check(got == want, f"{name} 字段名与调用点一致 {sorted(want)}", f"实际 {sorted(got)}")
    # 渲染必须不抛异常:MINUTES_PROMPT 曾因 schema 用单花括号而在 .format 时抛
    # KeyError('\n  "title"'),接口每次 502、模型请求数为 0。
    try:
        tpl.format(**{f: "样本" for f in want})
        ok, err = True, ""
    except Exception as e:  # noqa: BLE001
        ok, err = False, f"{type(e).__name__}: {e}"
    check(ok, f"{name} 可被 .format 渲染(单花括号回归锁)", err)

check("{content}" in P._REGEN_HINT or "{" not in P._REGEN_HINT,
      "_REGEN_HINT 不含未声明占位符(它以 .strip() 原文追加)")

# ================================================== 3. 示例必须能过自家解析器
# 原则:给模型看的样例,模型大概率照抄。样例自己都过不了解析,功能就是坏的。

m = re.search(r"示例:(\{.*\})", render(P.INTENT_PROMPT))
check(m is not None, "INTENT_PROMPT 含一条完整示例 JSON")
if m:
    try:
        d = json.loads(m.group(1))
        check(set(d) == {"intent", "need_retrieval", "audience_hint", "normalized_query"},
              "INTENT 示例的键 == 字段契约声明的四个", sorted(d))
        check(d["intent"] in ("chitchat", "time", "retrieval"),
              "INTENT 示例的 intent 落在 graph.py 允许的枚举内", d["intent"])
        check(isinstance(d["need_retrieval"], bool),
              "INTENT 示例把 need_retrieval 写成布尔字面量(不是字符串)",
              type(d["need_retrieval"]).__name__)
        check(d["audience_hint"] in ("undergrad", "postgrad", "common", ""),
              "INTENT 示例的 audience_hint 合法", d["audience_hint"])
    except json.JSONDecodeError as e:
        check(False, "INTENT 示例是合法 JSON", str(e))

m = re.search(r"输出:(\{.*\})\n", render(P.MINUTES_PROMPT))
check(m is not None, "MINUTES_PROMPT 含一条完整示例输出")
if m:
    try:
        parsed = minutes.parse_minutes_output(m.group(1))
        check(isinstance(parsed, dict) and parsed.get("resolutions") == ["会议确定下周三交材料"],
              "MINUTES 示例能过真实解析器 parse_minutes_output", list(parsed)[:8])
    except Exception as e:  # noqa: BLE001
        check(False, "MINUTES 示例能过真实解析器 parse_minutes_output", f"{type(e).__name__}: {e}")

check(P.MINUTES_PROMPT.count("{{") == P.MINUTES_PROMPT.count("}}"),
      "MINUTES schema 的字面花括号成对转义", "单双不配对会让 .format 抛 KeyError")

# evals 的 judge 提示词:示例值必须是合法 JSON(原口径写的是 {"score": 0.x},
# 模型照抄则 float() 抛异常 → 静默降级成词面覆盖率 proxy,分数系统性偏低)。
fa_src = (ROOT / "evals" / "faithfulness.py").read_text(encoding="utf-8")
fa_prompt = ""
for node in ast.walk(ast.parse(fa_src)):
    if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) \
            and isinstance(node.value.value, str) and "忠实度" in node.value.value:
        fa_prompt = node.value.value
check(bool(fa_prompt), "从 evals/faithfulness.py 取到 judge 提示词")
if fa_prompt:
    fa_rendered = fa_prompt.format(question="问", context="料", answer="答")
    check("0.x" not in fa_rendered, "judge 示例不含非法 JSON 值 0.x")
    # 用 judge **自己的**解析路径吃自己给的示例(faithfulness.py 里是
    # re.search(r"\{[^{}]*\}") → json.loads → float(["score"]))
    jm = re.search(r"\{[^{}]*\}", fa_rendered, re.S)
    check(jm is not None, "judge 含一条完整示例")
    if jm:
        try:
            score = float(json.loads(jm.group(0))["score"])
            check(0.0 <= score <= 1.0, "judge 示例能过它自己的解析路径", score)
        except (json.JSONDecodeError, KeyError, ValueError, TypeError) as e:
            check(False, "judge 示例能过它自己的解析路径", f"{type(e).__name__}: {e}")
    # 评分档必须覆盖 0~1 不留缝(原口径 0.1~0.4 与 0.5~0.9 之间 0.4~0.5 无定义)
    check(all(b in fa_rendered for b in ("1.0", "0.7", "0.4", "0.1", "0.0")),
          "judge 评分档端点连续(不留 0.4~0.5 的缝)", "")
    check("大部分" not in fa_rendered and "约一半" not in fa_rendered,
          "judge 不含「大部分/约一半」这类未量化的空话")
    check("K/N" in fa_rendered, "judge 把评分改成了可数的 K/N 判据")

# ================================================== 4. 枚举与代码同源

enum_lines = re.search(r"可选枚举[^\n]*\n((?:\S+\n)+)", P.TOPIC_PROMPT)
listed = enum_lines.group(1).strip().splitlines() if enum_lines else []
check(tuple(listed) == ts.TALK_TOPICS,
      "TOPIC_PROMPT 的枚举与 talk_summary.TALK_TOPICS 逐项同序",
      f"prompt={listed} code={ts.TALK_TOPICS}")
check("其他" in P.TOPIC_PROMPT and "{content}" in P.TOPIC_PROMPT,
      "TOPIC_PROMPT 保留「其他」与 {{content}} 槽位")

wk_src = (ROOT / "mcp" / "weekly" / "server.py").read_text(encoding="utf-8")
wk_instr = ""
for node in ast.walk(ast.parse(wk_src)):
    if isinstance(node, ast.keyword) and node.arg == "instructions":
        wk_instr = ast.unparse(node.value)
check(bool(wk_instr), "从 weekly/server.py 取到工具 instructions")
if wk_instr:
    check("{CATEGORIES}" in wk_instr, "instructions 引用 {{CATEGORIES}} 而不是硬抄清单")
    check("student_name" in wk_instr, "instructions 交代了谈心谈话要带 student_name")
    for kw in ("update_fragment", "delete_fragment", "add_minutes"):
        check(kw in wk_instr, f"instructions 交代了 {kw} 的使用时机")
    check("边界:" in wk_instr, "instructions 有独立的边界段(多条碎片/改删/非记录)")

# ================================================== 5. 外部材料必须套围栏

# 只有"外部文本"才需要围栏;`{category}` 这类由代码从固定枚举里取的值不算外部材料。
MATERIAL_FIELDS = {
    "SUMMARY_PROMPT": {"content"},
    "COMPRESS_PROMPT": {"history"},
    "EXPAND_PROMPT": {"content"},
    "TOPIC_PROMPT": {"content"},
    "MINUTES_PROMPT": {"raw"},
    "WEB_CONTEXT_BLOCK": {"urls"},
}
for name, mat in MATERIAL_FIELDS.items():
    tpl = getattr(P, name)
    guard_at = tpl.find(P.MATERIAL_GUARD)
    slots = {f: tpl.find("{" + f + "}") for f in mat}
    ok = guard_at >= 0 and all(p >= 0 and guard_at < p for p in slots.values())
    check(ok, f"{name} 的外部材料槽位前有围栏",
          f"guard@{guard_at} slots@{slots}")

check(P.MATERIAL_GUARD not in P.INTENT_PROMPT and P.MATERIAL_GUARD not in P.REWRITE_PROMPT,
      "用户自己这一轮的问句不套围栏(它是指令来源,不是被引用材料)")

# ================================================== 6. 正文里不写变更史、不留空话

HIST = re.compile(r"坑 ?\d+|P4[a-f]\b|C[0-9]-②")
for name in list(EXPECTED) + ["_HARD_RULES", "_BASE_STYLE", "_REGEN_HINT"]:
    txt = getattr(P, name)
    check(not HIST.search(txt), f"{name} 正文不含变更史标记(坑号/P4x 属注释)",
          HIST.search(txt).group(0) if HIST.search(txt) else "")

VAGUE = ["写得好一点", "尽量", "适当", "合理一点", "好一点", "简明扼要地", "注意质量"]
for name in list(EXPECTED) + ["_HARD_RULES", "_BASE_STYLE"]:
    txt = getattr(P, name)
    hit = [w for w in VAGUE if w in txt]
    check(not hit, f"{name} 不含不可检查的空话", hit)

# ================================================== 7. 空输入 / 无依据的边界都写了

BOUNDARY = {
    "SUMMARY_PROMPT": ["仅有标题"],
    "COMPRESS_PROMPT": ["无可压缩的历史"],
    "TOPIC_PROMPT": ["不足 10 个字"],
    "REWRITE_PROMPT": ["原样输出"],
    "MINUTES_PROMPT": ["空字符串", "空数组"],
    "EXPAND_PROMPT": ["事务纪要体"],
    "HISTORY_GATE_NOTE": ["均未覆盖"],
}
for name, words in BOUNDARY.items():
    txt = getattr(P, name)
    miss = [w for w in words if w not in txt]
    check(not miss, f"{name} 交代了空输入/无依据的边界", miss)

# ================================================== 8. 组装口径没被搬移动过

ctx = "CTX-示例资料 [1]"
check(agent.build_system_prompt(None, ctx) == agent.legacy_system_prompt(ctx),
      "无 persona 时 build_system_prompt 与 legacy 逐字等价(搬移后仍成立)")
check("【联网补充】" in agent.build_system_prompt({"name": "A"}, "", "【联网补充】\n- http://x"),
      "带 persona 时联网资料段仍拼得进去")

# ================================================== 汇总

fails = [r for r in RESULTS if not r[0]]
print("=" * 78)
print(f"[RESULT] {len(RESULTS) - len(fails)}/{len(RESULTS)} passed")
if fails:
    for _, label, detail in fails:
        print(f"  [FAIL] {label}  → {detail}")
sys.exit(1 if fails else 0)
