#!/usr/bin/env python3
"""P4e S2-②:在 docs/EVAL_BASELINE.md 追加 **§十九**(v2.3 → v2.4 口径变更 + canonical 命令)。

⚠ 该文件**不在本单常设白名单**内;本补丁只在复核方(Qoder)2026-10-01 打回指令 S2-②③
**显式要求**下执行,属一次性授权,不留作先例。

用法: novaagent/.venv/Scripts/python.exe docs/p4e/patch_eval_baseline_19.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "docs" / "EVAL_BASELINE.md"
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError, OSError):
    pass

SEC = """

---

## 十九、v2.3 → v2.4 记账（P4e 主体 + S1 流式收口，2026-10-01，实现方 WorkBuddy / 复核 Qoder）

> ⚠ 本节为 **P4e 打回后（S2-②）补记**。此前 v2.4 的口径变更只写在 `docs/P4E.md` 与
> `docs/TASKS.md`，**未同步进基线文档**（责任在实现方：误判白名单边界未上交裁决）。
> 补记由复核方在打回指令中显式授权。

### 19.1 用例数变更（口径变更，历史 48 条不改写）

| 版本 | 用例数 | 变化 |
|---|---|---|
| v2.3 | 48 | P4e C0 第二回后的对照口径 |
| **v2.4** | **55** | +`stream_sse` **3**（ss-01/02/03）+`web_grounded` **4**（wg-01..04） |

- **旧用例零丢失零改动**（复核方按 id 语义比对确认，纯新增）。
- 新增两类都是**用户可感知路径 / 新能力**的覆盖：`stream_sse` 补的是「改了 `/api/chat/stream`
  却全项目 0 断言走它」这个洞（HANDOFF 坑 60）；`web_grounded` 补的是联网开/关对照（坑 48）。

### 19.2 canonical 命令（**写死，照抄，不要自己改**）

```bash
# ① 整轮评测（canonical —— 55/55 且退出码 0 只在这个命令下成立）
cd E:/AILearn/NovaCampus
NOVA_GROUNDING_STREAM_FORCE_UNGROUNDED=1 \\
  bash docs/p4d/run_with_server.sh <port> ../evals/run_evals.py --base http://127.0.0.1:<port>

# ② 冒烟
bash docs/p4d/run_with_server.sh <port> ../novaagent/tests/smoke_test.py --base http://127.0.0.1:<port>

# ⚠ 取退出码**不要接管道**（坑 55）:
#    正确: cmd > /tmp/x.log 2>&1 ; echo "[EXIT=$?]"
#    错误: cmd | tail -40 ; echo "$?"      ← 拿到的是 tail 的退出码
```

**为什么必须带 `NOVA_GROUNDING_STREAM_FORCE_UNGROUNDED=1`**：`ss-03` 断言「闸门命中 → 出现
`grounding_retry` 且落库为重生后版本」。闸门自然命中率约 20%（qa-17 实测 2/10），
不强制则该断言**空跑/随机红**。该 env 默认关闭、仅作用于流式路径首版判定。

### 19.3 两档都要如实记录（不许藏）

| 档位 | 期望 | 实测（2026-10-01） |
|---|---|---|
| **canonical（带钩子）** | 55/55、exit 0 | ✅ `reports/eval_report_20261001_015708.json`：55/55、exit 0、R@k 1.0、忠实度 0.9722、拒答 1.0、隔离 47 会话 ok |
| **默认（不带钩子）** | 54/55、exit 1 | ✅ `reports/eval_report_20261001_020455.json`：仅 `ss-03` 判红（闸门未命中），FAIL 文案已指明该设哪个变量；`ss-01` span=3075ms **PASS** |

**默认档是 54/55 属设计如此，不是缺陷**：`ss-03` 需要一个测试钩子才能必然命中闸门。
这一档必须照实写进回执 —— 藏起来正是我们要审计的东西。

### 19.4 忠实度观测区间（S2-④ 更新）

**0.8889 ~ 0.9722**（复核方整轮实测 **0.8889**，低于此前记录的 0.9444 下限）。
LLM-as-judge 抽样抖动（坑 50），**非回归**；`evals/faithfulness.py` 零改动。
忠实度**不作合并闸门**，只看是否落在区间内。

### 19.5 已知轮换波动

`qa-08`（「休学期满怎么申请复学?」，期望关键词含「一周」）会在措辞轮换时 FAIL：
2026-10-01 canonical 第 1 轮 FAIL（R@k 仍 1.0、忠实度 1.0、来源全对），
单独连测 5 次 **5/5 PASS**，第 2 轮整轮 **55/55**。属 HANDOFF 坑 16 已有记录的输出方差，
**不是回归，也不许靠改用例改绿**。
"""

ANCHOR = "- 坑 56 已执行：`badcases.json` 按主键比对（新增 `ungrounded`，**证据已先记录**）后\n"


def main() -> int:
    src = BASE.read_text(encoding="utf-8")
    if "## 十九、v2.3 → v2.4 记账" in src:
        print("[skip] §十九 已存在")
        return 0
    # 追加到文件末尾(不破坏既有章节)
    BASE.write_text(src.rstrip("\n") + "\n" + SEC, encoding="utf-8")
    print("[OK] EVAL_BASELINE.md 已追加 §十九(v2.4 口径变更 + canonical 命令)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
