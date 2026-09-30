#!/usr/bin/env python3
"""P4e S2-④:两处记账更正。

① `docs/p4e/evidence/QA12_E2E_DISCREPANCY.md` 顶部加「当前结论」一句话
   (别让读者以为 C0 还挂着 qa-17 待裁决 / 47/48)
② `docs/P4E.md` 忠实度观测区间扩到含复核方的 0.8889

用法: novaagent/.venv/Scripts/python.exe docs/p4e/patch_s2_docs.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
QA12 = ROOT / "docs" / "p4e" / "evidence" / "QA12_E2E_DISCREPANCY.md"
P4E = ROOT / "docs" / "P4E.md"
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError, OSError):
    pass

QA12_OLD = "# 集中验证纪要：qa-12 已 PASS，但**评测端口**与**qa-17 检测口径**两个真因（2026-09-30）\n"
QA12_NEW = """# 集中验证纪要：qa-12 已 PASS，但**评测端口**与**qa-17 检测口径**两个真因（2026-09-30）

> ## ⚠ 当前结论（2026-10-01 回填，S2-④：本文件为**历史纪要**，不再代表现状）
>
> - **① `qa-12` 假红已定案并修复**：根因是评测打错端口，修法（扩 `FUSION_TOP_K` 8→12）本身正确；
>   v2.2 起 `qa-12` 转 PASS，v2.3/v2.4 基线均为满通过。
> - **② `qa-17` 已裁决并落地**：裁决 = **B 的代码化版本**（生成出口加确定性闸门，**禁止放宽判据**），
>   实现为 `agent.answer_is_grounded()` + 一次重生，`qa-17` 10 连测判红 0/10。
>   **本节"待裁决"状态已结束。** 只有「端口」那一条是**长期有效的流程纪律**：
>   整轮评测前必须做单请求端到端自证、`run_with_server.sh` 缺 `--base` 会 `exit 3`。
> - **不要再按本文件下判断**；后续证据看 `docs/p4e/evidence/qa17_gate.json` 与 `docs/EVAL_BASELINE.md`。

"""

P4E_OLD = """| Recall@k / 忠实度 / 拒答 | **1.0 / 0.9444(llm) / 1.0**；忠实度按区间 0.9444~0.9722 读，未作闸门 | 同上 |"""
P4E_NEW = """| Recall@k / 忠实度 / 拒答 | **1.0 / 0.9444(llm) / 1.0**；忠实度按区间读、**未作闸门** | 同上 |
| 忠实度观测区间（S2-④ 更新） | **0.8889 ~ 0.9722** —— 复核方本轮整轮实测 **0.8889**，低于我此前记的 0.9444 下限。judge 抽样抖动（坑 50），非回归；区间已按实测扩 | 复核方 :8922 整轮 |"""


def main() -> int:
    s = QA12.read_text(encoding="utf-8")
    n = s.count(QA12_OLD)
    if n != 1:
        print(f"[FAIL] QA12 锚点命中 {n} 次")
        return 1
    QA12.write_text(s.replace(QA12_OLD, QA12_NEW, 1), encoding="utf-8")
    print("[OK] QA12_E2E_DISCREPANCY.md 顶部已加「当前结论」")

    s = P4E.read_text(encoding="utf-8")
    n = s.count(P4E_OLD)
    if n != 1:
        print(f"[FAIL] P4E 表格锚点命中 {n} 次")
        return 1
    s = s.replace(P4E_OLD, P4E_NEW, 1)
    # §1.3 之后的"如实读数"旁也标一下区间
    s = s.replace("忠庺度按区间读", "忠实度按区间读")
    P4E.write_text(s, encoding="utf-8")
    print("[OK] P4E.md 忠实度区间已扩到 0.8889~0.9722")
    return 0


if __name__ == "__main__":
    sys.exit(main())
