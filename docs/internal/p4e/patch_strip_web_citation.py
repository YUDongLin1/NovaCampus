#!/usr/bin/env python3
"""P4e M-A:正文里逐句绑定的 `[W<n>]` 角标由**代码剥离**(指令挡不住,实测已命中)。

事实:WEB_CONTEXT_BLOCK 已明确要求"禁止写 [W1] 角标",但 wg-01 首轮实测模型仍写出 `[W3]`
—— 与 P4a 的教训同源:**prompt 挡不住,必须落代码**。

做法(与 P4a C2 `strip_invalid_refs` 同手法):
  · 非流式:生成后 `strip_web_citations()` 剥离;
  · 流式:`_StreamRefFilter` 加 `drop_web` 开关,流内即时剥离(不下发);
  · 两处都记 warning 日志 —— **不是静默兜底**(坑 46/47)。
⚠ 剥离后评测的"正文不得含 [W<n>]"反向断言就恒绿了,故另配
  `docs/p4e/probe_web_citation_ruler.py` 证明这把尺子**能判红**(坑 39/52)。

用法: novaagent/.venv/Scripts/python.exe docs/p4e/patch_strip_web_citation.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AGENT = ROOT / "novaagent" / "novaagent" / "agent.py"
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError, OSError):
    pass

# ---- 1. 纯函数(放在 _FACTUAL_RE 之后) ----
A1_OLD = '_FACTUAL_RE = re.compile(r"\\[\\d+\\]|\\d")\n'
A1_NEW = '''_FACTUAL_RE = re.compile(r"\\[\\d+\\]|\\d")

# P4e M-A:正文里**逐句绑定**的联网角标 `[W<n>]` —— 上游无「句子 ↔ URL」映射,写了就是假精确。
# 实测 wg-01 首轮模型即写出 `[W3]`(尽管 WEB_CONTEXT_BLOCK 明令禁止)→ 与 P4a 同源:
# **prompt 挡不住,必须落代码**。剥离时记 warning,不是静默兜底。
_WEB_CITATION_RE = re.compile(r"\\[W\\d{1,2}\\]")


def strip_web_citations(answer: str) -> tuple[str, int]:
    """剥离答案正文里的 `[W<n>]` 角标,返回 (清理后答案, 剥离处数)。纯函数,可单测。

    ⚠ 只处理 `[W<n>]` 这一种;本地 `[1..n]` 归 P4a C2 的 `strip_invalid_refs` 管,互不越界。
    """
    hits = _WEB_CITATION_RE.findall(answer or "")
    if not hits:
        return answer, 0
    logger.warning("答案正文出现逐句绑定的 [W<n>] 角标 %d 处,已代码剥离"
                   "(上游只给 {type,url},无句子↔来源映射)", len(hits))
    return _WEB_CITATION_RE.sub("", answer or ""), len(hits)
'''

# ---- 2. _StreamRefFilter 支持 drop_web ----
A2_OLD = '''    def __init__(self, n_sources: int):
        self.n_sources = n_sources
        self.pending = ""
        self.stripped: list[int] = []

    def _decide(self, token: str) -> str:
        m = re.fullmatch(r"\\[(\\d{1,2})\\]", token)
'''
A2_NEW = '''    def __init__(self, n_sources: int, drop_web: bool = False):
        self.n_sources = n_sources
        # P4e M-A: 联网模式下还要流内剥离逐句绑定的 [W<n>](同 P4a C2 的"越界即剥离")
        self.drop_web = drop_web
        self.pending = ""
        self.stripped: list[int] = []
        self.web_stripped = 0

    def _decide(self, token: str) -> str:
        if self.drop_web and _WEB_CITATION_RE.fullmatch(token):
            self.web_stripped += 1
            return ""
        m = re.fullmatch(r"\\[(\\d{1,2})\\]", token)
'''

A3_OLD = '''            if re.fullmatch(r"\\[\\d{1,2}\\]", token):
                out.append(self._decide(token))
                self.pending = rest
'''
A3_NEW = '''            is_web_cite = bool(self.drop_web and _WEB_CITATION_RE.fullmatch(token))
            if is_web_cite or re.fullmatch(r"\\[\\d{1,2}\\]", token):
                out.append(self._decide(token))
                self.pending = rest
'''

# ---- 3. chat_for: 生成后剥离(web 模式) ----
A4_OLD = '''            # P4a C2 引用硬校验:越界 [n] 代码剥离并记 fabricated_ref badcase
            answer, stripped = refusal.strip_invalid_refs(answer, len(sources))'''
A4_NEW = '''            # P4e M-A:先剥逐句绑定的 [W<n>](联网模式),再走 P4a C2 的越界 [n] 剥离
            if web_sources:
                answer, _nw = strip_web_citations(answer)
                if _nw:
                    ctx_info["web_citations_stripped"] = _nw
            # P4a C2 引用硬校验:越界 [n] 代码剥离并记 fabricated_ref badcase
            answer, stripped = refusal.strip_invalid_refs(answer, len(sources))'''

# ---- 4. chat_stream_for: 流内剥离 ----
A5_OLD = '            ref_filter = _StreamRefFilter(len(sources))  # P4a C2 流式引用越界过滤\n'
A5_NEW = ('            ref_filter = _StreamRefFilter(len(sources), drop_web=bool(web_sources))  '
          '# P4a C2 越界过滤 + P4e M-A 逐句 [W<n>] 剥离\n')

# ---- 5. 流式:剥离计数进 trace ----
A6_OLD = '''            if ref_filter.stripped:  # P4a C2: 流中剥离的越界引用记 badcase
                refusal.record_fabricated_ref(question, ref_filter.stripped, len(sources))'''
A6_NEW = '''            if ref_filter.stripped:  # P4a C2: 流中剥离的越界引用记 badcase
                refusal.record_fabricated_ref(question, ref_filter.stripped, len(sources))
            if ref_filter.web_stripped:   # P4e M-A: 流中剥掉多少处逐句 [W<n>],写进 trace(可观测)
                ctx_info["web_citations_stripped"] = ref_filter.web_stripped'''

PAIRS = [("A1", A1_OLD, A1_NEW, 1), ("A2", A2_OLD, A2_NEW, 1), ("A3", A3_OLD, A3_NEW, 1),
         ("A4", A4_OLD, A4_NEW, 1), ("A5", A5_OLD, A5_NEW, 1), ("A6", A6_OLD, A6_NEW, 1)]


def main() -> int:
    src = AGENT.read_text(encoding="utf-8")
    for name, old, new, cnt in PAIRS:
        n = src.count(old)
        if n != cnt:
            print(f"[FAIL] {name} 命中 {n} 次(期望 {cnt})")
            return 1
        src = src.replace(old, new, 1)
    AGENT.write_text(src, encoding="utf-8")
    print("[OK] [W<n>] 角标已改为代码剥离(非流 + 流内双路径)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
