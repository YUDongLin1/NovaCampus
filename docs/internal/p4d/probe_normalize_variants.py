#!/usr/bin/env python3
"""P4d 诊断:确定性"意图归一 + 术语展开"的候选范式对照,选出改写阶梯第 2 档。

范式:
  B  expand_terms        去噪 + 同义术语(现实现)
  C1 core+exp 全部同义词  词典命中词 + 其全部同义词
  C2 core+exp+意图词(命中) 再加问句里出现的意图词
  C3 core+exp+意图词(通用) 再加通用意图词集(办理/参保/投保/缴费/报销/理赔/材料/流程/条件/标准/方式)
判定:grade 口径 top>=0.3 且 n_above>=2 且命中目标>=1。
"""
import asyncio
import re
import sys

sys.path.insert(0, ".")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError, OSError):
    pass

from novaagent import config, db, graph, rag

QUERIES = [
    ("学平险在哪里买", True),
    ("我们学校有学平险吗，我看我们计财处只有医保这项", True),
    ("我看计财处只有医保这一项，那学校还给学平险吗", True),
    ("老师，我想问下咱们学校那个学平险是要单独交钱吗，我没在缴费项目里看到", True),
    ("学生平安保险是否由学校统一办理？", True),
    ("关于学生在校期间的意外与医疗保障，除了城乡居民基本医疗保险之外，学校是否还统一办理学生平安保险？", True),
    ("我们学校有没有量子计算实验室开放日预约", False),
]

INTENT_WORDS = ["办理", "参保", "投保", "缴费", "报销", "理赔", "材料", "流程",
                "条件", "标准", "方式", "时间", "申请"]
GENERIC = ["办理", "参保", "投保", "缴费", "报销", "理赔", "材料", "流程",
           "条件", "标准", "方式", "审批", "规定"]


def dict_hits(base: str) -> list[str]:
    """长词优先命中词典,避免"医保"吃掉"大学生医疗保险"。"""
    keys = sorted(config.TERM_EXPANSION, key=len, reverse=True)
    out: list[str] = []
    for k in keys:
        if k in base and not any(k in o for o in out):
            out.append(k)
    return out


def variant(base: str, mode: str) -> str:
    core = dict_hits(base)
    if not core:
        return base
    parts = list(core)
    for k in core:
        for a in config.TERM_EXPANSION[k]:
            if a not in parts:
                parts.append(a)
    if mode == "C2":
        parts += [w for w in INTENT_WORDS if w in base and w not in parts]
        parts = parts[:len(core) + sum(len(config.TERM_EXPANSION[k]) for k in core)] + \
            [w for w in INTENT_WORDS if w in base and w not in parts]
    if mode == "C3":
        parts = core + [a for k in core for a in config.TERM_EXPANSION[k]] + \
            [w for w in GENERIC if w not in parts]
    return " ".join(dict.fromkeys(parts))


def is_target(s: dict) -> bool:
    return "学平险" in (s.get("title") or "") or "学生平安" in (s.get("content") or "")


async def main() -> None:
    db.connect()
    min_rank = config.ROLE_RANK["student"]
    modes = ["B", "C1", "C2", "C3"]
    print(f"{'问句':26s} {'档':3s} {'top':>7s} {'n_ab':>5s} {'src':>4s} {'命中':>4s} {'grade':>6s}")
    for q, expect in QUERIES:
        base = graph._strip_noise(q)
        forms = [("B", graph.expand_terms(q))]
        for m in ("C1", "C2", "C3"):
            forms.append((m, variant(base, m)))
        for tag, fq in forms:
            src, quality = await rag.search_with_quality(fq, min_rank)
            hits = sum(1 for s in src if is_target(s))
            top = quality.get("top_score") or 0
            grade = "OK" if (top >= config.GRADE_MIN_SCORE
                             and quality.get("n_above_threshold", 0) >= config.GRADE_MIN_ABOVE) else "-"
            print(f"{q[:24]:26s} {tag:3s} {str(quality.get('top_score')):>7s} "
                  f"{quality.get('n_above_threshold'):>5d} {len(src):>4d} {hits:>4d} {grade:>6s}")
        print()


asyncio.run(main())
