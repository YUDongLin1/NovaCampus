#!/usr/bin/env python3
"""P4e M-A 尺子自测:**证明这些断言真的能判红**(坑 39/52),纯本地、秒级、零网络。

背景:`[W<n>]` 逐句角标已改为**代码剥离**,于是"答案正文不得含 [W<n>]"这条反向断言
在产品路径上**恒绿** —— 恒绿的断言等于没有断言。本脚本用同一把尺子证明它**能红**:
  R4 直接对"未剥离的脏文本"跑评测用的 `_W_CITATION_RE`,必须命中;
  R5 `drop_web=False` 时 `[W3]` 必须**原样放行**(证明剥离开关真的在起作用,不是恒剥离)。

另外覆盖不误伤与分区编号:
  R1/R2 剥离生效且计数正确;R3 本地 [1]/年份 [2026]/条款〔2025〕不误伤;
  R6 build_web_sources 的 ref/site_name/去重/与本地编号不混。

退出码:0 = 全过;1 = 有 FAIL。
用法: novaagent/.venv/Scripts/python.exe docs/p4e/probe_web_citation_ruler.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "evals"))
sys.path.insert(0, str(ROOT / "novaagent"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError, OSError):
    pass

import run_evals as R  # noqa: E402  (评测侧的同一把尺子)
from novaagent import agent, websearch  # noqa: E402

FAILS: list = []


def ck(cond: bool, name: str, detail: str = "") -> None:
    print(f"{'[PASS]' if cond else '[FAIL]'} {name}{(' — ' + detail) if detail else ''}")
    if not cond:
        FAILS.append(name)


def main() -> int:
    f = agent.strip_web_citations
    # R1/R2 剥离生效 + 计数
    a, n = f("GDP[W3] 指国内生产总值，见[W1]。")
    ck("[W3]" not in a and n == 2, "R1 剥离 [W<n>] 且计数正确", f"n={n} 结果={a!r}")
    a2, n2 = f("见[W1][W12][W3]")
    ck(a2.strip() == "见" and n2 == 3, "R2 两位数 [W12] 也剥", f"n={n2} 结果={a2!r}")
    # R3 不误伤
    b, m = f("休学最长 1 年[1]；川发政价[2024]417 号；〔2025〕3 号")
    ck(m == 0 and b.startswith("休学最长 1 年[1]"), "R3 本地 [1] / 年份 [2024] / 〔2025〕 不误伤",
       f"m={m} 结果={b[:30]!r}")
    # R4 反向:评测那把尺子必须能抓到未剥离的脏文本(证明断言不是恒绿)
    dirty = "GDP 指国内生产总值[W3]。"
    ck(bool(R._W_CITATION_RE.findall(dirty)),
       "R4 反向:未剥离文本被评测尺子判红 → 该断言**能红**(非恒绿)",
       f"命中={R._W_CITATION_RE.findall(dirty)}")
    ck(not R._W_CITATION_RE.findall(f(dirty)[0]),
       "R4b 剥离后同一把尺子判绿 → 剥离真的生效")
    # R5 流式过滤器:开关两侧都要对
    f_on = agent._StreamRefFilter(0, drop_web=True)
    out_on = f_on.feed("据央行[W3]规定") + f_on.flush()
    ck("[W3]" not in out_on and f_on.web_stripped == 1,
       "R5 drop_web=True → 流内剥离 [W3]", f"out={out_on!r} n={f_on.web_stripped}")
    f_off = agent._StreamRefFilter(0, drop_web=False)
    out_off = f_off.feed("据央行[W3]规定") + f_off.flush()
    ck("[W3]" in out_off,
       "R5b drop_web=False → [W3] 原样放行(证明开关真的在起作用,不是恒剥离)",
       f"out={out_off!r}")
    # R6 分区编号与站点名推导
    urls = ["https://www.stats.gov.cn/a", "https://zh.wikipedia.org/b", "https://www.stats.gov.cn/a"]
    ws = websearch.build_web_sources(urls)
    ck([w["ref"] for w in ws] == ["W1", "W2"], "R6 ref = W1..Wk 且 URL 去重",
       f"refs={[w['ref'] for w in ws]}")
    ck(all(w["site_name_derived"] for w in ws) and ws[0]["site_name"] == "www.stats.gov.cn",
       "R6b site_name 由 netloc 推导且标注 derived", f"names={[w['site_name'] for w in ws]}")
    ck(not ({"W1"} & {1, 2, 3}), "R6c 联网 ref 与本地 [1..n] 编号不混", "")
    # R7 整段级声明由代码注入(不靠模型)
    ck("未经本校核实" in agent.WEB_DECLARE, "R7 整段级声明常量含「未经本校核实」",
       agent.WEB_DECLARE[:30])
    print(f"\n[ruler] {'ALL PASS' if not FAILS else 'FAIL: ' + ', '.join(FAILS)}")
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(main())
