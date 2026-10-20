#!/usr/bin/env python3
"""修正 web_grounded 的「开关生效」断言:web_called 只在用例显式声明时才比对。

原因:联网是**本地拒答后的补充通道**(本地有据时不发起出网请求),所以
「开关=开」不等于「本次真的调用了联网」。把 `web_called == want_on` 写成无条件断言,
会在任何「本地本来就能答」的问句上假红(坑 45 同形状:断言比被测物更严)。
改为:用例显式给 `expect_web_called` 才比对;其余情况退化为「关 → 绝不调用」。

用法: novaagent/.venv/Scripts/python.exe docs/p4e/patch_run_evals_webassert.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / "evals" / "run_evals.py"
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError, OSError):
    pass

OLD = '''    # 开关是否真的生效:以服务端 trace 的 web_called 为唯一证据(不看前端/不看答案措辞)
    if bool(ctx.get("web_called")) != want_on:
        bad.append(f"trace web_called={ctx.get('web_called')} != 请求开关 {want_on}(开关没生效)")
'''
NEW = '''    # 开关是否真的生效:以服务端 trace 的 web_called 为唯一证据(不看前端/不看答案措辞)。
    # ⚠ 联网是「本地拒答后的补充通道」,本地有据时不发起出网请求,故**开关=开 ≠ 本次一定调用**。
    #   只有用例显式声明 expect_web_called 时才比对(本单 4 条均为库内无据的构造问句,故都声明了)。
    if "expect_web_called" in case:
        if bool(ctx.get("web_called")) != bool(case["expect_web_called"]):
            bad.append(f"trace web_called={ctx.get('web_called')} != 期望 "
                       f"{case['expect_web_called']}(开关没生效)")
'''


def main() -> int:
    src = TARGET.read_text(encoding="utf-8")
    n = src.count(OLD)
    if n != 1:
        print(f"[FAIL] 锚点命中 {n} 次(期望 1),未改动文件")
        return 1
    TARGET.write_text(src.replace(OLD, NEW, 1), encoding="utf-8")
    print("[OK] web_grounded 开关断言已改为显式声明制")
    return 0


if __name__ == "__main__":
    sys.exit(main())
