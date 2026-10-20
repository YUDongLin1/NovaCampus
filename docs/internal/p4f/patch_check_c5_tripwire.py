"""C5 反向验证:把流式炸点拆掉,确认 C5 组当场红(而不是安静地烧额度)。

用法:
    python docs/p4f/patch_check_c5_tripwire.py apply   # 拆掉 chat_stream_for 炸点
    python novaagent/.venv/Scripts/python.exe novaagent/tests/test_p4f_persona.py
    python docs/p4f/patch_check_c5_tripwire.py revert # 复原

判据:apply 之后 test_p4f_persona.py **必须红**,且红项里必须出现 C5 A / C5 B;
若仍全绿,说明这些断言是「走过场」,不能算拦截力证据(坑 52)。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / "novaagent" / "tests" / "test_p4f_persona.py"
MARK = "    # @@C5_TRIPWIRE_PATCH@@\n"

# 真正拆掉炸点:不赋值 = 流式路径不被拦截(退回第一版的形状)
PATCH_FROM = "    main.agent.chat_stream_for = _boom_stream\n"
PATCH_TO = ("    # @@C5_TRIPWIRE_PATCH@@\n"
            "    pass  # 炸点被故意拆掉:流式路径现在完全不被拦截\n")


def revert() -> int:
    """⚠ 复原必须把 PATCH_TO 整段换回 PATCH_FROM —— 只删标记行会留下 `pass`,
    炸点就永远装不上了(第一版 revert 只删标记行,复原后仍 134/136 就是这么来的)。"""
    src = TARGET.read_text(encoding="utf-8")
    if MARK not in src:
        print("[patch] 已是干净态")
        return 0
    if PATCH_TO not in src:
        print("[patch] !! patched 态形状与预期不符,手工处理")
        return 2
    TARGET.write_text(src.replace(PATCH_TO, PATCH_FROM, 1), encoding="utf-8")
    print("[patch] 已复原(炸点重新装上)")
    return 0


def apply() -> int:
    src = TARGET.read_text(encoding="utf-8")
    if MARK in src:
        print("[patch] 已是 patched 态")
        return 0
    if PATCH_FROM not in src:
        print("[patch] !! 找不到锚点,源码形状变了,手工处理")
        return 2
    TARGET.write_text(src.replace(PATCH_FROM, PATCH_TO, 1), encoding="utf-8")
    print("[patch] 已拆掉流式炸点(chat_stream_for 恢复原样)")
    return 0




if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "apply"
    if cmd == "apply":
        sys.exit(apply())
    if cmd == "revert":
        sys.exit(revert())
    print(__doc__)
    sys.exit(2)
