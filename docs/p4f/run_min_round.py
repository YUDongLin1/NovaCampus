#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P4f 集中验证**最小档**运行器（负责人 Qoder 用专用测试 key 跑，不改仓库里的评测脚本）。

为什么单独写一个文件而不是给 `evals/run_evals.py` 加 `--only`：
  加参数 = 负责人动手实现产品代码，违反「单一持棒 / 破例要留痕」。这里只做**外部包装**：
  把 `cases.json` 的读取拦下来、过滤成 7 条，其余**全部走真代码路径**
  （分发、判据、报告落盘、隔离断言、退出码都与整轮一致），结果才可与 v2.4/v2.5 对照。

选这 7 条的理由（对应回执 §3.4「本轮没有验证的」四项）：
  pf-01/02/03   —— persona 主判据（来源集合一致）+ **篇幅比 1.2 在真实模型输出下是否成立**
  pf-inject-01  —— 注入攻击在真实生成下是否真被挡住（判据①②③）
  qa-17         —— C0-③ 闸门在**事实轮**上的命中/重生记账（P4e 里它 6 次命中 4 次）
  ss-03         —— 流式路径的闸门与早窗（canonical 档需服务端带 FORCE_UNGROUNDED）
  cc-01         —— C0-③ 的关键：43 轮长上下文里**种植轮的闸门命中是否归零**

跑法（端口自己起，见文件末尾说明）：
  cd novaagent && set -a && . ./.env.test && set +a && \\
    NOVA_GROUNDING_STREAM_FORCE_UNGROUNDED=1 bash ../docs/p4d/run_with_server.sh \\
      8951 ../docs/p4f/run_min_round.py --base http://127.0.0.1:8951
"""
import os
import sys
from pathlib import Path
from pathlib import Path as _P

ROOT = Path(r"E:/AILearn/NovaCampus")
sys.path.insert(0, str(ROOT / "evals"))
sys.path.insert(0, str(ROOT / "novaagent"))

ONLY = [x.strip() for x in os.environ.get("MIN_ROUND_ONLY",
        "pf-01,pf-02,pf-03,pf-inject-01,qa-17,ss-03,cc-01").split(",") if x.strip()]

_orig_read_text = _P.read_text


def _read_text(self, *a, **kw):
    txt = _orig_read_text(self, *a, **kw)
    if self.name == "cases.json":
        import json as _j
        spec = _j.loads(txt)
        total = len(spec["cases"])
        keep = [c for c in spec["cases"] if c.get("id") in ONLY]   # 保持原文件顺序
        spec["cases"] = keep
        print("[min-round] cases.json 过滤: %d/%d 条 -> %s" % (len(keep), total, ONLY))
        txt = _j.dumps(spec, ensure_ascii=False)
    return txt


_P.read_text = _read_text

import run_evals as R  # noqa: E402

if __name__ == "__main__":
    rc = R.run()
    print("[min-round] run_evals.run() 退出码 = %d" % rc)
    sys.exit(rc)
