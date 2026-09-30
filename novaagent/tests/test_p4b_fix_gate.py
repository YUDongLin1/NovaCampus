#!/usr/bin/env python3
"""P4b-fix ①/⑤ 单元测试:追问轮历史门控 + 消息来源快照与中止回滚(独立运行,零新依赖)

用法:.venv/Scripts/python.exe -X utf8 tests/test_p4b_fix_gate.py
(会用临时 DB,不触碰 novaagent/data/agent.db)
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_TMP = tempfile.mkdtemp(prefix="nova_p4bfix_test_")
os.environ["NOVA_DATA_DIR"] = _TMP  # 必须先于 import novaagent.db

from novaagent import db  # noqa: E402
from novaagent.agent import history_gate_hit  # noqa: E402


def test_gate_hit_and_miss() -> None:
    """标定集:代词/摘要命中;主题切换/空池拒绝(判据见 docs/P4B.md §三.1)。"""
    ans_v1 = ("研究生申请休学需提交以下材料：\n1. 本人书面申请；\n"
              "2. 二级甲等以上医院诊断证明（因病休学）；\n3. 导师意见。\n"
              "上述材料经培养单位审核同意后，报研究生院审批。")
    ans_v2 = ("研究生申请休学应当提交以下材料：本人书面申请、二级甲等以上医院诊断证明"
              "（因病休学）、导师意见 。")  # temp=0 下实测出现过的另一措辞(无"需"字)
    summary = ("此前对话讨论了若干校园事务:1.本科生学费标准为7341元/人;"
               "2.学平险出险报案电话为958823;3.奖学金评审依据文件编号川校发[2026]88号,"
               "特别奖额度为17340元;4.研究生休学需提交导师意见等材料。")
    hits = [
        ("那它需要导师签字吗?", [ans_v1]),
        ("那它需要导师签字吗?", [ans_v2]),  # 回指标记+导师 2-gram,措辞方差下必须稳命中
        ("把此前对话里出现过的报案电话与奖学金评审文件编号原样列出来。", [summary]),
        ("那此前对话里提到的学费金额和特别奖额度分别是多少?", [summary]),
    ]
    misses = [
        ("学校游泳馆办深水证需要什么材料，在哪里办?", [ans_v1]),
        ("学校游泳馆办深水证需要什么材料，在哪里办?", [ans_v2]),
        ("那明天成都天气怎么样?", [ans_v1]),
        ("那我们宿舍的空调费具体怎么交？", [ans_v1]),
        ("那它需要导师签字吗?", []),          # 空池(如仅有拒答模板)必拒
        ("那它需要导师签字吗?", ["", "   "]),
        ("它的英文怎么说?", [ans_v1]),        # 回指但池内零内容重叠 → 仍拒
    ]
    for q, pool in hits:
        assert history_gate_hit(q, pool), f"应命中未命中: {q[:20]}"
    for q, pool in misses:
        assert not history_gate_hit(q, pool), f"应拒绝却命中: {q[:20]}"


def test_sources_snapshot_and_rollback() -> None:
    """sources_json 快照:仅 assistant 带有效 sources 时落库;delete_message 回滚单条。"""
    db.connect()  # 惰性建库+迁移(NOVA_DATA_DIR 已指向临时目录,不触碰真实 agent.db)
    row = db.verify_user("gate_tester", "pw123456") or (
        db.add_user("gate_tester", "pw123456", "student"), db.verify_user("gate_tester", "pw123456"))[1]
    uid = row["id"]
    cid = db.create_conversation(uid, "门控测试")
    u = db.add_message(uid, "user", "用户自述:空调费237元", cid)
    a = db.add_message(uid, "assistant", "知识库中暂无相关内容…", cid)  # 拒答模板,无来源
    a2 = db.add_message(uid, "assistant", "研究生申请休学需导师意见 [1]", cid,
                        sources=[{"ref": 1, "title": "学籍规定", "content": "第三条…", "score": 0.99,
                                  "role_min": "student"}])
    hist = {m["id"]: m for m in db.get_conversation_history(cid)}
    assert hist[u]["sources_json"] is None, "user 消息不得带来源快照"
    assert hist[a]["sources_json"] is None, "无来源回答不得带快照"
    assert hist[a2]["sources_json"] and "学籍规定" in hist[a2]["sources_json"], "有来源回答须落快照"
    # 回滚:只删指定会话内的那一条
    assert db.delete_message(u, cid) is True
    assert db.delete_message(u, cid) is False  # 幂等:已删不存在
    ids = {m["id"] for m in db.get_conversation_history(cid)}
    assert u not in ids and a in ids and a2 in ids


def main() -> int:
    test_gate_hit_and_miss()
    test_sources_snapshot_and_rollback()
    print("P4b-fix gate/rollback tests: ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
