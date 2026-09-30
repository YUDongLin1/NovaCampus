#!/usr/bin/env python3
"""P4d 诊断:候选改写式的实效对照——哪一类改写真的能把 rerank 拉过 0.3。

对每条失败问句,枚举若干"改写式"候选(LLM 风格 / 确定性术语展开 / 混合),
用 rag.search_with_quality 实测 (top_score, n_above_threshold, 命中目标数),
据此决定 graph 的改写阶梯该怎么排(而非凭直觉设定)。
"""
import asyncio
import sys

sys.path.insert(0, ".")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError, OSError):
    pass

from novaagent import config, db, rag


def is_target(s: dict) -> bool:
    return "学平险" in (s.get("title") or "") or "学生平安" in (s.get("content") or "")


CASES = [
    ("真实原句", "我们学校有学平险吗，我看我们计财处只有医保这项", [
        "学生平安保险 参保 投保",
        "学平险 学生平安保险 大学生意外伤害保险 参保 投保",
        "本科生 学生平安保险 是否由学校统一办理 参保",
        "大学生意外伤害保险 学平险 投保 理赔",
        "学生平安保险 办理方式 缴费",
    ]),
    ("背景前置倒装", "我看计财处只有医保这一项，那学校还给学平险吗", [
        "学平险 学生平安保险 大学生意外伤害保险 参保",
        "本科生 学平险 是否办理 投保",
        "学生平安保险 办理 参保 通知",
    ]),
    ("口语加称呼情境", "老师，我想问下咱们学校那个学平险是要单独交钱吗，我没在缴费项目里看到", [
        "学平险 单独缴费 参保",
        "学生平安保险 缴费方式 参保 通知",
        "本科生 学平险 学生平安保险 大学生意外伤害保险 缴费 办理",
        "学平险 是否需要缴费 投保 通知",
    ]),
    ("书面正式名", "学生平安保险是否由学校统一办理？", [
        "学生平安保险 统一办理 办理方式 通知",
        "学平险 学生平安保险 大学生意外伤害保险 统一办理",
        "本科生 学生平安保险 办理 参保",
    ]),
    ("[对照]域外", "我们学校有没有量子计算实验室开放日预约", [
        "量子计算 实验室 开放日 预约",
        "学生平安保险 参保",
    ]),
]


async def main() -> None:
    db.connect()
    min_rank = config.ROLE_RANK["student"]
    for label, orig, cands in CASES:
        print("=" * 96)
        print(f"[{label}] 原句: {orig}")
        for q in cands:
            src, quality = await rag.search_with_quality(q, min_rank)
            hits = sum(1 for s in src if is_target(s))
            print(f"   {q[:44]:46s} top={str(quality.get('top_score')):7s} "
                  f"n_above={quality.get('n_above_threshold'):2d} src={len(src)} 命中目标={hits}")


asyncio.run(main())
