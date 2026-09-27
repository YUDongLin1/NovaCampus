#!/usr/bin/env python3
"""忠实度 LLM-as-judge(T4)— 复用 NovaAgent 模型配置,只读导入、不修改 novaagent/**

judge(question, answer, sources) -> (score 0~1 | None, method)
  - method="llm":  LLM 判"回答的每个事实性陈述是否被上下文(sources[].content 拼接)支持"
  - method="proxy": LLM 不可用时的词面覆盖率兜底(回答 2-gram 在上下文中的命中率)
  - (None, "na"):  回答为空或无上下文(如正确拒答),不计入忠实度均值
"""
from __future__ import annotations

import asyncio
import json
import re
import sys
from pathlib import Path

_NOVA_DIR = Path(__file__).resolve().parent.parent / "novaagent"
sys.path.insert(0, str(_NOVA_DIR))  # 使 `from novaagent import …` 指向 novaagent/novaagent 包

from novaagent import config, llm  # noqa: E402  只读复用(模型名/密钥/调用),不修改

PROMPT = """你是严格的 RAG 忠实度评审。逐句检查"回答"中的事实性陈述是否被"上下文"支持(上下文即回答时的检索依据)。

评分:
- 1.0 所有事实性陈述均被上下文明确支持
- 0.5~0.9 大部分被支持,少量缺乏依据或过度引申
- 0.1~0.4 约一半陈述无依据
- 0.0 回答与上下文矛盾,或主要陈述为编造

只输出一个 JSON 对象,不要其他文字:{{"score": 0.x, "reason": "一句话依据"}}

问题:{question}

上下文:
{context}

回答:
{answer}"""


def _proxy_coverage(answer: str, context: str) -> float:
    """词面覆盖率:回答中的中文/字母数字 2-gram 在上下文中的命中比例。"""
    grams = {answer[i : i + 2] for i in range(len(answer) - 1)
             if re.match(r"[\u4e00-\u9fffA-Za-z0-9]", answer[i]) and re.match(r"[\u4e00-\u9fffA-Za-z0-9]", answer[i + 1])}
    if not grams:
        return 0.0
    return round(sum(1 for g in grams if g in context) / len(grams), 4)


def judge(question: str, answer: str, sources: list[dict]) -> tuple[float | None, str]:
    answer = (answer or "").strip()
    if not answer:
        return None, "na"
    context = "\n".join(f"[{s.get('ref', '')}] {s.get('content', '')}" for s in sources).strip()
    if not context:
        return None, "na"  # 无检索依据(如正确拒答),忠实度不适用
    try:
        msg = asyncio.run(llm.chat(
            [{"role": "user", "content": PROMPT.format(question=question, context=context[:6000], answer=answer)}],
            max_tokens=200,
            temperature=0,
        ))
        raw = (msg.get("content") or "").strip()
        m = re.search(r"\{[^{}]*\}", raw, re.S)
        score = float(json.loads(m.group(0))["score"]) if m else None
        if score is None:
            raise ValueError(f"无法从 LLM 输出解析 score: {raw[:80]}")
        return round(min(max(score, 0.0), 1.0), 4), "llm"
    except Exception:  # LLM 不可用/解析失败 → 词面覆盖率兜底
        return _proxy_coverage(answer, context), "proxy"
