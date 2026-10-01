#!/usr/bin/env python
"""现算七个自测的断言条数合计，并断言它 == 文档里写的那个数。

【为什么需要这个文件（第 4 回 · Qoder 的顺手一条，同一形状第四次复发）】
   汇总数是**手抄**的：文档里写「七个自测 NNN条 exit 全 0」，
   而 NNN 得手算 33+158+68+66+63+99+20。本轮又栽了一次：
   实现方写 507（test_p4f_c0 记成 63），复核方实测是 64，真值 **508**。
   这是坑 56/59 家族的第四例：「聚合数手抄、没跟着逐条读数重算」。

   **手抄的东西不可能自己判红** —— 只有让「聚合」变成一个可执行断言，
   才可能在下一次某条自测增减时**当场**报红，而不是等复核方来发现。

【★ 为什么必须"真跑"而不是静态数调用点（第一版踩到的坑，留档）】
   第一版用 `ast` 静态数 `chk(` 调用点，结果五个文件数出 **0** ——
   因为七个自测**各用各的断言机制**：`probe_health_keysource` 把 `chk` 定义在
   函数里、`test_p4f_persona.py` 用模块级 `RESULTS` 列表、其余各叫各的名。
   更根本的是**断言在循环里被复用**：`test_p4f_persona_eval.py` 静态数出 86，
   实跑是 92（同一个 `chk` 在循环里执行了多次）。
   → **「静态调用点数」与「运行时断言条数」不是一回事**，前者不能当权威。
     本版改为**逐个真跑、取其`[RESULT] n/`** —— 慢几十秒，但那是唯一真值。
     这条本身就是坑 74 的同族教训：**中间数据结构对了 ≠ 出口对了**。

【零额度】本文件只跑**自测**（各自测内部用假 key 护身符），不发真LLM/embedding 请求；
   与被跑的测试一样受同一纪律约束。需要服务端口的自测若起不来会退化为「读上次落盘
   证据」并标注，但那**不算现算** —— 会单独提示，且默认判红（宁可吵不可静默放过）。

用法：
   novaagent/.venv/Scripts/python.exe novaagent/tests/_sum_selftest_counts.py
   novaagent/.venv/Scripts/python.exe novaagent/tests/_sum_selftest_counts.py --no-run
       # 只读上次落盘的证据文件，不真跑（快；用于离线复核）

退出码：0 = 合计与文档一致；1 = 不一致或某条读不到
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent# E:\AILearn\NovaCampus
TESTS = HERE
EVIDENCE = ROOT / "docs" / "p4f" / "evidence"
PY = HERE.parent / ".venv" / "Scripts" / "python.exe"

# ── 七个自测文件（第 4 回重算后的真实清单）─────────────────────────────
# 每个条目: (文件名, 跑它需要的参数)
SELFTESTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("probe_port_check.py", ("--selftest",)),
    ("test_p4f_persona.py", ()),
    ("test_p4f_persona_eval.py", ()),
    ("test_p4f_persona_eval_wiring.py", ()),
    ("test_p4f_c0.py", ()),
    ("test_p4f_frontend_contract.py", ()),
    ("probe_health_keysource.py", ()),
)

# ── 文档里写的聚合数 ──────────────────────────────────────────────────
# ⚠ **这个数不是手抄的** —— 改任何自测的断言条数后，用下面的现算命令重取：
#     novaagent/.venv/Scripts/python.exe novaagent/tests/_sum_selftest_counts.py
#   改动历史（这个工具自己抓到的第四次同形状错误，留档）：
#     507 → 实现方手抄（把 test_p4f_c0 按63 计）→ Qoder 代改为 508（对，第 3 回真值）
#     508 → **第 4 回本工具首次现算就报红 532**（本轮新增 24 条：噪声闸 22 + 同义豁免 14
#          中与既有节重叠的部分；test_p4f_persona_eval 68 → 92）
EXPECTED_TOTAL = 532

# ── 文档里逐条写的分项数（报错时用于定位「哪一条抄错了」）──────────────
# ⚠ 这份表本身也可能抄错 —— 它存在的意义是**报错时立刻指出是哪一条**，
#   不充当权威（权威是下面现跑出来的数）。
DOCUMENTED_PER_FILE: dict[str, int] = {
    "probe_port_check.py": 33,
    "test_p4f_persona.py": 158,
    "test_p4f_persona_eval.py": 92,       # 第 4 回：68 + 24
    "test_p4f_persona_eval_wiring.py": 66,
    "test_p4f_c0.py": 64,# 第 4 回：63 → 64（复核方实测）
    "test_p4f_frontend_contract.py": 99,
    "probe_health_keysource.py": 20,
}

# 各自测最近一次落盘的证据文件，用于 --no-run 模式
_EVIDENCE_HINT: dict[str, str] = {
    "probe_port_check.py": "port_probe_selftest_output.txt",
    "test_p4f_persona.py": "persona_selftest_output.txt",
    "test_p4f_c0.py": "c0_selftest_output.txt",
    "test_p4f_frontend_contract.py": "frontend_selftest_output.txt",
    "probe_health_keysource.py": "health_keysource_two_states.json",
}

_RESULT_RE = re.compile(r"\[RESULT\]\s+(\d+)/(\d+)\s+passed")


def run_one(name: str, args: tuple[str, ...]) -> tuple[int | None, int | None, int]:
    """真跑一个自测 → (passed, total, exit_code)。"""
    env = dict(os.environ)
    env["NO_PROXY"] = "127.0.0.1,localhost"
    env["PYTHONIOENCODING"] = "gbk"
    # 假 key 护身符：万一某条自测路径真的发出请求，会拿 401 而不是扣费（同既有纪律）
    env.setdefault("LLM_API_KEY", "ZERO-QUOTA-PROTECTOR-LLM")
    env.setdefault("EMBEDDING_API_KEY", "ZERO-QUOTA-PROTECTOR-EMB")
    try:
        p = subprocess.run(
            [str(PY), str(TESTS / name), *args],
            cwd=str(HERE.parent), env=env, capture_output=True,
            text=True, encoding="utf-8", errors="replace", timeout=600,
        )
    except Exception as e:  # noqa: BLE001
        print(f"  [warn] {name} 跑不起来: {type(e).__name__}: {e}")
        return None, None, -1
    hits = _RESULT_RE.findall((p.stdout or "") + (p.stderr or ""))
    if not hits:
        return None, None, p.returncode
    return int(hits[-1][0]), int(hits[-1][1]), p.returncode


def read_evidence_count(name: str) -> int | None:
    """从最近一次落盘的证据文件里读 `[RESULT] n/`（--no-run 模式用）。"""
    hint = _EVIDENCE_HINT.get(name)
    if not hint:
        return None
    p = EVIDENCE / hint
    if not p.exists():
        return None
    try:
        txt = p.read_text(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        return None
    hits = _RESULT_RE.findall(txt)
    return int(hits[-1][0]) if hits else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-run", action="store_true",
                    help="只读上次落盘证据，不真跑（默认真跑，那是唯一真值）")
    args = ap.parse_args()

    rows: list[tuple[str, int | None, int | None, int | None, int | None]] = []
    total = 0
    unreadable: list[str] = []

    # ⚠ `--no-run` 的可用性边界（实测踩到）：七个自测里**只有四个**会落盘 `[RESULT]`
    #   证据文件（`probe_port_check` / `test_p4f_persona` / `test_p4f_c0` /
    #   `test_p4f_frontend_contract`），另三个（`test_p4f_persona_eval` /
    #   `_wiring` / `probe_health_keysource`）**不落盘**。
    #   所以 `--no-run` 会只读到 4 条=354，若照样拿它跟532 比就会**误报**，
    #   而一个"总是退 1"的工具等于没有工具(坑70同族:宁可吵不可静默,反过来也成立——
    #   **总是吵的工具会被当成噪音忽略**)。
    #   故：`--no-run` 下只要有任何一条读不到，就**明确拒绝**并列出缺口，
    #   **不给半截合计**——半截数字最容易被误当成真值引用。
    if args.no_run:
        _probe = {name: read_evidence_count(name) for name, _ in SELFTESTS}
        _miss = [n for n, v in _probe.items() if v is None]
        if _miss:
            print("[REFUSE] --no-run 模式缺少这些自测的落盘证据: "
                  f"{_miss}")
            print("         下列自测不落盘 [RESULT] 证据文件,读不出条数:")
            print("           test_p4f_persona_eval.py / test_p4f_persona_eval_wiring.py")
            print("           probe_health_keysource.py")
            print("         → 请改用真跑模式(去掉 --no-run);那才是唯一真值。")
            print("         ⚠ 本模式**拒绝**给出半截合计:一个只覆盖 4/7 的数字")
            print("           比没有数字更危险(会被当成 508/532 引用)。")
            return 1

    print("=" * 88)
    print("七个自测断言数 —— 现算 vs 落盘证据 vs 文档")
    print("=" * 88)
    print(f"{'文件':<32}{'现算':>7}{'证据':>7}{'文档':>7}{'退出码':>8}  备注")
    print("-" * 88)

    for name, sargs in SELFTESTS:
        if args.no_run:
            live, code = None, None
        else:
            live, _, code = run_one(name, sargs)
        evid = read_evidence_count(name)
        doc = DOCUMENTED_PER_FILE.get(name)
        use = live if live is not None else evid
        if use is None:
            unreadable.append(name)
        else:
            total += use
        rows.append((name, live, evid, doc, code))

        note = ""
        if live is None and not args.no_run:
            note = "★真跑没读到 RESULT（见上方 warn）"
        if doc is not None and use is not None and doc != use:
            note = (note + " " if note else "") + f"★文档 {doc} ≠ 现值 {use}"
        if live is not None and evid is not None and evid != live:
            note = (note + " " if note else "") + f"·落盘证据 {evid}（上次跑的，本轮已改过测试）"
        s = "—" if live is None else str(live)
        e = "—" if evid is None else str(evid)
        d = "—" if doc is None else str(doc)
        c = "—" if code is None else str(code)
        print(f"{name:<32}{s:>7}{e:>7}{d:>7}{c:>8}  {note}")

    print("-" * 88)
    print(f"现算合计 = {total}    文档 EXPECTED_TOTAL = {EXPECTED_TOTAL}")
    print("=" * 88)

    ok = True
    if unreadable:
        ok = False
        print(f"[FAIL] 有文件读不出断言数: {unreadable}")
    for name, live, evid, doc, _ in rows:
        use = live if live is not None else evid
        if doc is not None and use is not None and doc != use:
            ok = False
            print(f"[FAIL] {name}: 文档写 {doc},现值 {use} → 文档分项数已失效")
    if total != EXPECTED_TOTAL:
        ok = False
        print(f"[FAIL] 合计 {total} ≠ 文档写的 {EXPECTED_TOTAL}"
              " → 文档汇总数已失效（手抄的数不会自己判红，这就是本文件存在的理由）")
    if ok:
        print(f"[OK]   合计 {total} == 文档 {EXPECTED_TOTAL}（现跑得出，非手抄）")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())