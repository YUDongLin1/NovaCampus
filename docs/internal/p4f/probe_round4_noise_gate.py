#!/usr/bin/env python
"""第 4 回反向闭环：把噪声闸改成「不过滤」→ 三条新断言必须红 → 改回 → 绿。

订单交回要求第 3 条：
  「把过滤函数临时改成『不过滤』→ 三条新断言必须红；改回 → 绿。」

做法：不改源码文件（避免动工作树），而是**在子进程里注入一个「不过滤」的
`_acceptable_no_evidence_frag` 后真跑 `test_p4f_persona_eval.py`**，看它的
`[RESULT]` 是否真的掉下去。这样：
  ① 源码零改动 —— 不用 git checkout来回切，天然没有残留风险；
  ② 判据的**运行时行为**被真实改坏（而不是我假装它坏了）；
  ③ 退出码可取（不用接管道，坑 55）。

三档依次跑并打印：
  A. 修后（不过滤被替换成「≥3 字」→等价于修前口径）→ 须红
  B. 复原（正常闸）→ 须绿
  C. 二次确认：换个更宽的不过滤口径（全部收）→ 须红
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent          # docs/p4f
ROOT = HERE.parent.parent                        # 仓库根
TESTS = ROOT / "novaagent" / "tests"
PY = ROOT / "novaagent" / ".venv" / "Scripts" / "python.exe"
TARGET = TESTS / "test_p4f_persona_eval.py"

# ⚠⚠ **注入必须用与被测文件完全相同的导入方式**（第一版栽在这）。
#   被测 `test_p4f_persona_eval.py` 第 39 行是 `import run_evals as R`
#   ——它绑的是**顶层模块** `run_evals`。
#   我第一版写 `from evals import run_evals as R` ——那是**包属性路径**，
#   Python 为它建了**另一个模块对象**（`evals.run_evals` ≠ `run_evals`）。
#   于是「注入改坏的」与「测试读的」是两个对象：注入无声无息失效，
#   坏闸根本没进到测试里，自测照样 92/92 全绿 → **闭环看起来通过，其实什么都没验**。
#   这与坑 45「两份权威实现互相冒充」同族：同一份代码经**两条路径**得到两个实例，
#   改动落在A、校验落在 B,谁也发现不了。
#   → 铁律：**要改一个模块的行为,必须经它自己被导入的那条路径改**。
#     拿不准就先 `print(id(R))` 两边对一下。
_BREAK_GATE = """
import sys
for _p in ({evals!r}, {nova!r}, {root!r}):
    if _p not in sys.path:
        sys.path.insert(0, _p)
# ★ 与被测文件同路径:顶层 `run_evals`,不是 `evals.run_evals`
import run_evals as R
# ↓↓ 注入:噪声闸改回修前口径(不过滤,纯>=3 字)↓↓
R._acceptable_no_evidence_frag = lambda frag: len(frag) >= 3
R.NO_EVIDENCE_MARKS = R._derive_no_evidence_marks()
assert any(("0.3" in m or "https" in m) for m in R.NO_EVIDENCE_MARKS), \\
    "注入失败:坏闸没生效(检查导入路径是否与被测一致)"
import runpy
runpy.run_path({target!r}, run_name="__main__")
"""

# C 档:更宽的不过滤(连 3 字门槛都没有,什么都收)—— 更狠的破坏
_BREAK_GATE_WIDE = _BREAK_GATE.replace(
    "lambda frag: len(frag) >= 3",
    "lambda frag: bool(frag)",
)

_RESULT_RE = re.compile(r"\[RESULT\]\s+(\d+)/(\d+)\s+passed")


def run(python_code: str, label: str) -> tuple[int, int, int]:
    env = dict(os.environ)
    env["NO_PROXY"] = "127.0.0.1,localhost"
    env["PYTHONIOENCODING"] = "gbk"
    env.setdefault("LLM_API_KEY", "ZERO-QUOTA-PROTECTOR-LLM")
    env.setdefault("EMBEDDING_API_KEY", "ZERO-QUOTA-PROTECTOR-EMB")
    p = subprocess.run(
        [str(PY), "-c", python_code],
        cwd=str(ROOT / "novaagent"), env=env,
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=600,
    )
    out = (p.stdout or "") + (p.stderr or "")
    hits = _RESULT_RE.findall(out)
    passed = int(hits[-1][0]) if hits else -1
    total = int(hits[-1][1]) if hits else -1
    mark = "OK " if hits else "??"
    print(f"[{mark}] {label:<52} {passed}/{total}  退出码={p.returncode}")
    # 把失败的断言名打出来（这就是"哪三条红了"的原文）
    fails = re.findall(r"\[FAIL\]\s*(.+)", out)
    for f in fails:
        print(f"        红: {f[:110]}")
    return passed, total, p.returncode


def main() -> int:
    print("=" * 88)
    print("第 4 回 ⑥ 反向闭环：噪声闸改成『不过滤』→ 自测必须红 → 改回 → 绿")
    print("（不碰源码：靠子进程注入改坏，天然无残留）")
    print("=" * 88)

    ctx = dict(
        evals=str(ROOT / "evals"),
        nova=str(ROOT / "novaagent"),
        root=str(ROOT),
        target=str(TARGET),
    )

    print("\n--- A档:注入『不过滤』(>=3字) —— 期望 RED ---")
    a_pass, a_total, a_code = run(_BREAK_GATE.format(**ctx), "A注入不过滤")

    print("\n--- B档:不注入(修后正常闸) —— 期望 GREEN ---")
    b_pass, b_total, b_code = run(
        f"import runpy; runpy.run_path({str(TARGET)!r}, run_name='__main__')",
        "B 修后（正常闸）",
    )

    print("\n--- C档:注入『更宽的不过滤』(连3字门槛都没有) —— 期望 RED ---")
    c_pass, c_total, c_code = run(_BREAK_GATE_WIDE.format(**ctx), "C 注入更宽不过滤")

    print("\n" + "=" * 88)
    ok = True
    # A 档必须红：比起跑绿，红了才证明闸确实在挡
    if not (a_total > 0 and a_pass < a_total):
        ok = False
        print(f"[FAIL] A档应红但未红: {a_pass}/{a_total}（噪声闸坏了却没被抓到）")
    else:
        print(f"[OK] A档按预期变红:{a_pass}/{a_total}（闸被拆后,判据漏放行被抓到）")
    # B 档必须绿且等于 A 的满额
    if not (b_total > 0 and b_pass == b_total):
        ok = False
        print(f"[FAIL] B档应全绿但未全绿: {b_pass}/{b_total}")
    else:
        print(f"[OK] B档全绿:{b_pass}/{b_total}（闸恢复）")
    if a_total != b_total:
        ok = False
        print(f"[FAIL] A/B 满分不一致 {a_total} vs {b_total}（可疑，注入是否漏掉了别的）")
    # C 档必须红
    if not (c_total > 0 and c_pass < c_total):
        ok = False
        print(f"[FAIL] C档应红但未红: {c_pass}/{c_total}")
    else:
        print(f"[OK] C档按预期变红:{c_pass}/{c_total}（更狠的破坏也被抓到）")
    # 退出码：红档非0、绿档0
    if a_code == 0 or c_code == 0:
        ok = False
        print(f"[FAIL] 红档退出码应为非0（A={a_code} C={c_code}）")
    if b_code != 0:
        ok = False
        print(f"[FAIL] 绿档退出码应为0（实得{b_code}）")

    print("=" * 88)
    print("反向闭环判定:", "通过（拆闸红、复原绿）" if ok else "★未通过")
    print("=" * 88)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())