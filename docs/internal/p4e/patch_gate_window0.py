#!/usr/bin/env python3
"""修正 _StreamGate:`window_chars<=0` 必须**完整退回** M4 的全量缓冲。

Bug(自检发现):原实现把「出现首个可核查事实 → 放行」写在 N 的判断之外,于是
`NOVA_GROUNDING_EARLY_WINDOW_CHARS=0` 时仍会在首个事实处放行 —— "全缓冲"档退化成
与"早窗"档几乎同值(实测 span 518ms vs 492ms),**对照档失效**。
N=0 的语义是「退回 M4 旧行为」,应当**整段生成完才判定并下发**。

用法: novaagent/.venv/Scripts/python.exe docs/p4e/patch_gate_window0.py
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

OLD = '''        self.pending.append(chunk)
        # ① 出现首个可核查事实([n] 引用或数字) → 这一版算有据,立即放行
        if (not self.force) and bool(_FACTUAL_RE.search(self.text)):
            return self._release()
        # ② 早窗用尽(满 N 字) → 照常放行,不再继续憋着(N=0 表示退回全缓冲)
        if self.window_chars > 0 and len(self.text) >= self.window_chars:
            return self._release()
        return []
'''
NEW = '''        self.pending.append(chunk)
        # ⚠ N<=0 的完整语义 = **退回 M4 全量缓冲**(整段生成完才判定、才下发),
        #   不能只关掉"满 N 字"这一条——否则 N=0 档会在首个事实处放行,与早窗档同值,
        #   对照档失效(自检实测:未修时 N=0 档 span 518ms ≈ 早窗档 492ms)。
        if self.window_chars <= 0:
            return []
        # ① 出现首个可核查事实([n] 引用或数字) → 这一版算有据,立即放行
        if (not self.force) and bool(_FACTUAL_RE.search(self.text)):
            return self._release()
        # ② 早窗用尽(满 N 字) → 照常放行,不再继续憋着
        if len(self.text) >= self.window_chars:
            return self._release()
        return []
'''


def main() -> int:
    src = AGENT.read_text(encoding="utf-8")
    n = src.count(OLD)
    if n != 1:
        print(f"[FAIL] 锚点命中 {n} 次(期望 1)")
        return 1
    AGENT.write_text(src.replace(OLD, NEW, 1), encoding="utf-8")
    print("[OK] N<=0 已改为完整退回全量缓冲")
    return 0


if __name__ == "__main__":
    sys.exit(main())
