#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P4f 第 2 回复核后的小幅收口（负责人代做，留痕）：

`9089fe1` 把 `evals/run_evals.py` 的 `--base` 改成**必填**（方向正确，坑 57 的正解），
但全仓 4 处**文档里的复跑命令**还是旧写法，照抄会直接 argparse 报错（实测退出码 2）。
改默认行为必须同步改所有照它办事的命令 —— 否则下一个按文档执行的人第一步就撞墙，
而且会以为是自己的端口错了。

代做理由：这几行是**复核方自己每天要敲的命令**（COLLAB §5 合并闸门第 2 步、EVAL_BASELINE
的 canonical 复跑口径），属负责人领地；且改动纯文档、零额度、不碰任何判据。
"""
import io

log = []


def rep(path, pairs):
    s = io.open(path, encoding="utf-8").read()
    for a, b in pairs:
        n = s.count(a)
        assert n == 1, "%s 锚点命中 %d 次: %r" % (path, n, a[:60])
        s = s.replace(a, b, 1)
    io.open(path, "w", encoding="utf-8", newline="").write(s)
    log.append("patched " + path)


NEW_CMD = ("`PYTHONIOENCODING=utf-8 bash docs/p4d/run_with_server.sh <自己的端口> "
           "../evals/run_evals.py --base http://127.0.0.1:<自己的端口>`")

rep("docs/COLLAB.md", [(
    "2. 跑该任务验收命令 + `python novaagent/tests/smoke_test.py` + `python evals/run_evals.py`。",
    "2. 跑该任务验收命令 + 冒烟与评测（**两者都必须显式 `--base`**，自 `9089fe1` 起"
    "`run_evals.py` 缺 `--base` 直接退出码 2；不要再用 `:8900`，那是他人常驻实例，"
    "会审到旧代码造出假红 —— 坑 57/61）：\n"
    "   `bash docs/p4d/run_with_server.sh <端口> tests/smoke_test.py --base http://127.0.0.1:<端口>`、"
    "`bash docs/p4d/run_with_server.sh <端口> ../evals/run_evals.py --base http://127.0.0.1:<端口>`。",
)])

rep("docs/EVAL_BASELINE.md", [(
    "> 复跑:评测启动 `NO_PROXY=\"127.0.0.1,localhost\" NOVAAGENT_EVAL_TEMPERATURE=0 "
    "uvicorn novaagent.main:app --port 8900`(在 novaagent/ 下;**评测必须带 "
    "NOVAAGENT_EVAL_TEMPERATURE=0**,产品部署不设该变量)→ `PYTHONIOENCODING=gbk "
    "python evals/run_evals.py` → `python evals/extract_badcases.py`",
    "> 复跑(**P4f 第 2 回复核后更新**:`--base` 自 `9089fe1` 起**必填**,且**不要再起 `:8900`**"
    "——那是他人常驻实例,审到旧代码会造出假红,坑 57/61):"
    "`bash docs/p4d/run_with_server.sh <自己的端口> ../evals/run_evals.py "
    "--base http://127.0.0.1:<自己的端口>` → `python evals/extract_badcases.py`。"
    "包装脚本已负责 `NO_PROXY` 与 `NOVAAGENT_EVAL_TEMPERATURE=0`(**评测必须带 temp=0**,产品部署不设该变量)、"
    "按端口属主杀进程并复查端口关闭。",
)])

rep("docs/BADCASES.md", [
    ("每次执行 `python evals/run_evals.py` 产出新报告后,**紧接着跑一次**:",
     "每次执行评测(`--base` **必填**,见坑 57)产出新报告后,**紧接着跑一次**:"),
    ("2. `python evals/run_evals.py` 重跑评测;",
     "2. 重跑评测(`run_evals.py` 的 `--base` **必填**,缺了退出码 2);"),
])

print("\n".join(log))
