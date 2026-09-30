#!/usr/bin/env python3
"""P4e: cases.json v2.3 → v2.4 —— 新增 3 条 stream_sse + 4 条 web_grounded(48 → 55)。

口径变更必须记账(EVAL_BASELINE §十九 / HANDOFF「评测基线」行),历史 v2.3 = 48 条不改写。

用法: novaagent/.venv/Scripts/python.exe docs/p4e/patch_cases_v24.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / "evals" / "cases.json"
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError, OSError):
    pass

# 流式用例问句:两问合并 → 答案更长,渐进性(span)更容易被客观测到。
Q_STREAM = "研究生申请休学需要提交哪些材料？审批流程又是怎样的？"
# 联网用例问句:一律构造的公开知识题(HANDOFF 红线:不得用真实学工问句)。
Q_ISO = "ISO 4217 标准里人民币的三字母代码是什么？"
Q_CPI = "中国国家统计局公布的居民消费价格指数的英文缩写是什么？"

NEW_CASES = [
    {
        "id": "ss-01",
        "type": "stream_sse",
        "stream_kind": "basic",
        "role": "student",
        "question": Q_STREAM,
        "note": "P4e S1-② ①②③:事件序列 sources→context→delta*→done;delta>1;E2E-TTFB>=300ms"
                "(防 M4 把真流式缓冲成一次下发,坑 60)",
    },
    {
        "id": "ss-02",
        "type": "stream_sse",
        "stream_kind": "abort",
        "role": "student",
        "question": Q_STREAM,
        "note": "P4e S1-② ④:收到首个 delta 立即断开 → 本轮 user 消息必须被回滚(P4b C5 不变量);"
                "该用例不回 conversation_id,不进隔离断言(回滚后 user 条数为 0)",
    },
    {
        "id": "ss-03",
        "type": "stream_sse",
        "stream_kind": "gate",
        "role": "student",
        "question": Q_STREAM,
        "note": "P4e S1-② ⑤:闸门命中 → 出现 grounding_retry、重生文本分多个 delta 下发、"
                "done.answer 与落库答案均为重生后版本。"
                "⚠ 需服务端带 NOVA_GROUNDING_STREAM_FORCE_UNGROUNDED=1 才**必然**命中闸门;"
                "不带该变量时本用例退化为一致性断言(闸门命中 ⇔ retry 出现),不会假红。",
    },
    {
        "id": "wg-01",
        "type": "web_grounded",
        "role": "student",
        "web_search": True,
        "expect_web_called": True,
        "question": Q_ISO,
        "expect_web_sources_min": 1,
        "expect_web_declaration": ["未经本校核实"],
        "expect_keywords": [["CNY", "RMB"], ["人民币"]],
        "expect_no_w_citation": True,
        "note": "P4e M-D 开:库内无据的公开知识题 → 出现联网分区、URL 可点、整段级「未经本校核实」",
    },
    {
        "id": "wg-02",
        "type": "web_grounded",
        "role": "student",
        "web_search": False,
        "expect_web_called": False,
        "question": Q_ISO,
        "expect_absent_keywords": ["未经本校核实", "联网检索"],
        "expect_no_w_citation": True,
        "note": "P4e M-D 关:同一问句必须走 P4a 确定性拒答模板(指纹「系统模板生成」),"
                "且绝不发起联网请求",
    },
    {
        "id": "wg-03",
        "type": "web_grounded",
        "role": "student",
        "web_search": True,
        "expect_web_called": True,
        "question": Q_CPI,
        "expect_web_sources_min": 1,
        "expect_web_declaration": ["未经本校核实"],
        "expect_keywords": [["CPI"], ["居民消费价格指数"]],
        "expect_no_w_citation": True,
        "note": "P4e M-D 开(第二条构造问句,防单例偶然)",
    },
    {
        "id": "wg-04",
        "type": "web_grounded",
        "role": "student",
        "web_search": False,
        "expect_web_called": False,
        "question": Q_CPI,
        "expect_absent_keywords": ["未经本校核实", "联网检索"],
        "expect_no_w_citation": True,
        "note": "P4e M-D 关(第二条构造问句的对照组)",
    },
]


def main() -> int:
    spec = json.loads(TARGET.read_text(encoding="utf-8"))
    if spec.get("version") != "v2.3":
        print(f"[FAIL] 期望 version=v2.3,实为 {spec.get('version')};补丁只适用于该基线")
        return 1
    ids = {c["id"] for c in spec["cases"]}
    for c in NEW_CASES:
        if c["id"] in ids:
            print(f"[FAIL] 用例 id 冲突: {c['id']}")
            return 1
    before = len(spec["cases"])
    spec["cases"].extend(NEW_CASES)
    spec["version"] = "v2.4"
    spec["description"] = (
        spec["description"]
        + "；**P4e v2.4(口径变更,48 → 55 条)**:新增 `stream_sse` 3 条(用户真实路径 /api/chat/stream 的"
          "唯一自动化覆盖,坑 60)与 `web_grounded` 4 条(联网开/关对照 2 组,坑 48;含「正文不得出现"
          "逐句绑定的 [W<n>] 角标」反向断言)。历史 v2.3 = 48 条口径不改写。"
    )
    TARGET.write_text(json.dumps(spec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[OK] cases.json → v2.4,{before} → {len(spec['cases'])} 条")
    return 0


if __name__ == "__main__":
    sys.exit(main())
