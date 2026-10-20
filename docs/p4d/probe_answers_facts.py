#!/usr/bin/env python3
"""P4d-fix 事实探针:实测 qa-12 / rind-02 / qa-13 三个问句在 graph 编排下的真实答案。

用途(先量后判,不做猜测):
  1. ① rind-02 迁移为 qa 型时,断言必须写在**实测答案**上——先看它到底给不给
     学平险归口/历史文件时效声明、复不复读 95585;
  2. ④ judge_qa 非答案检测——先看 qa-12 的"非答案"长什么样(命中哪些免责措辞、
     去掉措辞后还剩多少实质内容),据此定阈值而不是拍脑袋;
  3. 基线对照——同问句在 8902(温度 0)上的稳定表现。

用法:NO_PROXY="127.0.0.1,localhost" novaagent/.venv/Scripts/python.exe docs/p4d/probe_answers_facts.py
"""
from __future__ import annotations

import os
import json
import re
import sys
from pathlib import Path

import httpx


# ---- 演示口令:一律从环境变量读,源码内不落明文(开源前脱敏要求) ----
def _demo_pw(role: str) -> str:
    r = role.upper()
    pwd = os.environ.get(f"NOVA_SEED_{r}_PASSWORD") or os.environ.get("NOVA_DEMO_PASSWORD", "")
    if not pwd:
        raise RuntimeError(
            f"未设置演示口令:请在 novaagent/.env 中写入 NOVA_DEMO_PASSWORD"
            f"(或 NOVA_SEED_{r}_PASSWORD)。")
    return pwd


ADMIN_PW = _demo_pw("admin")
COUNSELOR_PW = _demo_pw("counselor")
STUDENT_PW = _demo_pw("student")


sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = "http://127.0.0.1:8902"
HERE = Path(__file__).parent
QUESTIONS = [
    # (标签, 角色, 问句, 关注点)
    ("qa-12", "student", "研究生奖助学金评审是怎么规定的?",
     "④ 非答案检测靶点:检索到本科生文档、问的是研究生"),
    ("rind-02", "student", "我们学校有学平险吗，我看我们计财处只有医保这项",
     "① 迁移为 qa 的断言依据:归口/时效声明/95585 是否复读"),
    ("qa-13", "counselor", "学生在宿舍使用违章电器该怎么处理?", "③ 忠实度另一条低分项"),
]

# ④ 候选免责/未覆盖措辞(与 run_evals.REFUSAL_MARKS 有交集但更针对"自认没答")
NON_ANSWER_MARKS = (
    "未在知识库", "未检索到", "没有检索到", "未覆盖", "没有覆盖", "未收录",
    "未包含", "知识库中未", "暂无", "没有找到", "无法回答", "不在知识库", "没有相关",
    "请以", "以学校", "以学校现行", "建议咨询", "请咨询", "无法提供",
)


def substantive_len(answer: str) -> tuple[int, str]:
    """粗剥离免责措辞后的"实质内容"长度(用于非答案检测)。

    只做可解释的删除:逐行删掉**整行**都是免责措辞的行,不做语义猜测;
    返回 (剥离后长度, 剥离掉的行数)。阈值为 0 视为无非答案。
    """
    kept = []
    dropped = 0
    for line in answer.splitlines():
        s = line.strip().lstrip(">*-—·• ").strip()
        if not s:
            continue
        if any(m in s for m in NON_ANSWER_MARKS) and len(s) <= 120:
            dropped += 1
            continue
        kept.append(s)
    return len("".join(kept)), dropped


def main() -> int:
    out: list[dict] = []
    with httpx.Client(timeout=180, trust_env=False) as c:
        toks = {}
        for u, p in (("student", STUDENT_PW), ("counselor", COUNSELOR_PW), ("admin", ADMIN_PW)):
            toks[u] = c.post(f"{BASE}/api/login", json={"username": u, "password": p}).json()["token"]
        for cid, role, q, why in QUESTIONS:
            r = c.post(f"{BASE}/api/chat",
                       headers={"Authorization": f"Bearer {toks[role]}"}, json={"question": q})
            r.raise_for_status()
            d = r.json()
            answer = d.get("answer", "")
            ctx = d.get("context") or {}
            sub_len, dropped = substantive_len(answer)
            rec = {
                "id": cid, "role": role, "question": q, "why": why,
                "sources": [s.get("title") for s in d.get("sources") or []],
                "intent": ctx.get("intent"), "attempts": ctx.get("attempts"),
                "rewritten": ctx.get("rewritten"),
                "answer_len": len(answer),
                "marks_hit": [m for m in NON_ANSWER_MARKS if m in answer],
                "substantive_len": sub_len, "dropped_lines": dropped,
                "has_95585": "95585" in answer,
                "has_87600392": "87600392" in answer,
                "answer": answer,
            }
            out.append(rec)
            print("=" * 72)
            print(f"{cid} [{role}] {q}")
            print(f"  关注点: {why}")
            print(f"  sources({len(rec['sources'])}): {rec['sources']}")
            print(f"  intent={rec['intent']} attempts={rec['attempts']} rewritten={rec['rewritten']}")
            print(f"  answer_len={rec['answer_len']} marks_hit={rec['marks_hit']}")
            print(f"  substantive_len={sub_len} dropped_lines={dropped}")
            print(f"  95585={rec['has_95585']} 87600392={rec['has_87600392']}")
            print("  --- answer ---")
            print("  " + answer[:1800].replace("\n", "\n  "))
    dest = HERE / "evidence" / "after" / "answers_facts.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[evidence] {dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
