#!/usr/bin/env python3
"""S2-①:把阈值注释改成引用**最终定标数据**(三段式长问句),并记下"为什么改问句"。

用法: novaagent/.venv/Scripts/python.exe docs/p4e/patch_s2_threshold_note.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVALS = ROOT / "evals" / "run_evals.py"
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError, OSError):
    pass

OLD = '''#      【阈值为什么从 300 降到 150】300 是复核方拍的数,实测**压在真流式分布里面**:
#        全缓冲档(M4 旧行为) 逐次 span: 66.5 / 71.7 / 87.8 / 94.3 / 103.2 / 109.4 ms
#                                      (历史另见 70.9 / 71.4 / 118.9 / 73 / 79 / 31 / 48)
#        早窗档(默认)         逐次 span: 212.3 / 244.6 / 252.0 / 274.2 / 567.3 / 626.8 ms
#                                      (复核方另测 208 / 239 / 343 / 574)
#      → 全缓冲观测上界 118.9ms、早窗观测下界 208ms。取 **150ms**:
#        下侧余量 31ms(26%)、上侧余量 58ms(28%),两侧都留有余量。
#        取 300 时早窗档 208~274ms 那几次会**随机 FAIL** —— 等于把刚清掉的随机红又带回来。
#      证据: docs/p4e/evidence/stream_latency_span_{full,early80}.json(两档各连测 6 次)。
#
#      ⚠ 单据原文写的是「之差 > 0」,实测旧实现也有 31~119ms(>0),判不出 → 必须给阈值。
#      ⚠ **未采用**复核方给的备选相对判据 `span >= max(120, 0.10 × E2E)`:本语料 E2E ≈ 3.0~3.5s,
#        0.10×E2E = 300~350ms —— 恰好就是被判定为"压在分布里"的那个值。相对判据要成立,
#        比例需降到 ≈0.04(0.04×3153 ≈ 126ms)。此处取绝对阈值更可解释,故不采用。
STREAM_MIN_SPAN_MS = 150
'''

NEW = '''#      【阈值为什么从 300 降到 150】300 是复核方拍的数,实测**压在真流式分布里面**
#      (复核方自带证据:早窗档 208 / 239 / 343 / 574ms,其中 208/239 都 < 300 → 随机 FAIL)。
#
#      【先修测量,再定阈值】原双段问句答案仅 110~230 字,两档分布**几乎贴在一起**:
#        全缓冲档 span 观测上界 164ms(逐次 68/97/100/133/151/164;另批 66.5~109.4、31/48)
#        早窗档   span 观测下界 208ms(逐次 212.3/244.6/252.0/274.2/567.3/626.8;复核方 208/239)
#        → 无论取 120/150/180,缝隙都只有 20~30%,一个抖动就串档。
#      故把用例问句改成**三段式长问句**(答案 ~500 字、130~170 个 delta),让 span 回到
#      "整段生成耗时"这个它本该度量的量:
#        全缓冲档(6/6 FAIL) span = 82 / 94 / 96 / 97 / 98 / 108 ms        → 上界 108ms
#        早窗档  (6/6 PASS) span = 3044 / 3272 / 3275 / 3309 / 3511 / 4410 → 下界 3044ms
#        → 两档间隔 **~28 倍**,取 150ms 时下侧余量 39%、上侧余量 20 倍。
#      证据: docs/p4e/evidence/stream_sse_s2_{full6,early6}_long.json(两档各连测 6 次);
#            旧问句的分布另存 stream_latency_span_{full,early80}.json,保留不抹。
#
#      ⚠ 单据原文写的是「之差 > 0」,实测旧实现也有 31~119ms(>0),判不出 → 必须给阈值。
#      ⚠ **未采用**复核方给的备选相对判据 `span >= max(120, 0.10 × E2E)`:本语料 E2E ≈ 3.0~6.4s,
#        0.10×E2E = 300~640ms —— 恰好又落回被判定为"压在分布里"的量级;且该比例会随
#        **检索段变慢**而变严(E2E 5.3s 时要求 span≥530ms),对网络抖动不稳健。故取绝对阈值。
STREAM_MIN_SPAN_MS = 150
'''


def main() -> int:
    src = EVALS.read_text(encoding="utf-8")
    n = src.count(OLD)
    if n != 1:
        print(f"[FAIL] 锚点命中 {n} 次(期望 1)")
        return 1
    EVALS.write_text(src.replace(OLD, NEW, 1), encoding="utf-8")
    print("[OK] 阈值注释已改为引用最终定标数据")
    return 0


if __name__ == "__main__":
    sys.exit(main())
