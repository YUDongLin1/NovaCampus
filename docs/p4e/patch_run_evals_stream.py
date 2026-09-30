#!/usr/bin/env python3
"""P4e S1-②: 给 `evals/run_evals.py` 注入 `stream_sse` 评测类型(走 /api/chat/stream)。

动机(HANDOFF 坑 60):M4 的 grounding 闸门把 `/api/chat/stream` 改成 delta 全量缓冲,
而 `evals/` 与 `novaagent/tests/` **0 处**走该端点 → 48/48 对用户真实路径零证明力。

本补丁只做三处**精确插入**(每处带 count 断言,失败即报错,不静默改坏):
  1. 常量区追加:STREAM_MIN_SPAN_MS / _sse_events / _check_stream_grammar
  2. `def run()` 之前追加:`run_stream_case()`
  3. 类型分派:`elif case["type"] == "rewrite":` 块之后、`else:` 之前插入 stream_sse 分支

用法: novaagent/.venv/Scripts/python.exe docs/p4e/patch_run_evals_stream.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / "evals" / "run_evals.py"
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError, OSError):
    pass

# ---------------- 片段 1:常量与 SSE 解析 ----------------
BLOCK1_ANCHOR = 'REFUSAL_MARKS = ("暂无", "没有找到", "未检索", "知识库中未", "无法回答", "不在知识库", "没有相关")\n'
BLOCK1_NEW = BLOCK1_ANCHOR + '''
# ---------- P4e S1-②:流式端点(/api/chat/stream)评测 ----------
# 【为什么必须加这个类型】坑 60:M4 闸门把流式改成「delta 全量缓冲、判完再下发」,
# 而既有 48 条用例与冒烟**全部只打 /api/chat**,对该端点 0 覆盖 → 全绿无证明力。
#
# 【三条量化断言分别防什么】
#   ② delta 事件数 > 1 且 非「一条承载全文」 —— 防「整段合成一个 delta 下发」;
#   ③ E2E - TTFB >= STREAM_MIN_SPAN_MS —— 防「12 个 delta 挤在最后 36ms」(真流式被关掉)。
#      ⚠ 单据原文写的是「之差 > 0」,但实测旧实现 E2E-TTFB 也有 36ms(12 个 delta 集中在最后),
#        「>0」判不出旧实现 → 必须给阈值。300ms 的取值理由见 docs/P4E.md §S1。
#   ④ 客户端中途断开 → 本轮 user 消息被回滚(P4b C5 不变量)
#   ⑤ 闸门命中 → 出现 grounding_retry 且落库答案是重生后版本
STREAM_MIN_SPAN_MS = 300
# 事件语法:sources → context → delta* → [grounding_retry → delta*] → done(tools 可插在 delta 之间)
STREAM_HEAD = ("sources", "context")
STREAM_MID_OK = ("delta", "grounding_retry", "tools")


def _sse_events(resp):
    """把 SSE 字节流解析成事件 dict(按 \\n\\n 分帧;忽略 [DONE] 与坏帧)。"""
    buf = ""
    for chunk in resp.iter_bytes():
        buf += chunk.decode("utf-8", "replace")
        while "\\n\\n" in buf:
            raw, _, buf = buf.partition("\\n\\n")
            raw = raw.strip()
            if not raw.startswith("data:"):
                continue
            p = raw[5:].strip()
            if not p or p == "[DONE]":
                continue
            try:
                yield json.loads(p)
            except ValueError:
                continue


def _check_stream_grammar(kinds: list) -> list:
    """① 事件序列语法。返回问题列表(空=通过)。"""
    bad: list = []
    if not kinds:
        return ["空事件流(一条事件都没收到)"]
    if kinds[0] != "sources":
        bad.append(f"首事件应为 sources,实为 {kinds[0]}")
    if len(kinds) < 2 or kinds[1] != "context":
        bad.append(f"次事件应为 context,实为 {kinds[1] if len(kinds) > 1 else '(缺失)'}")
    if kinds[-1] != "done":
        bad.append(f"末事件应为 done,实为 {kinds[-1]}")
    for i, k in enumerate(kinds[2:-1]):
        if k not in STREAM_MID_OK:
            bad.append(f"位置 {i + 2} 出现非预期事件 {k}")
    if "delta" not in kinds:
        bad.append("全程零 delta 事件")
    if "grounding_retry" in kinds:
        gi = kinds.index("grounding_retry")
        if "delta" not in kinds[gi + 1:]:
            bad.append("grounding_retry 之后没有新的 delta(重生结果未下发)")
    return bad
'''

# ---------------- 片段 2:run_stream_case ----------------
BLOCK2_ANCHOR = "\ndef run() -> int:\n    global BASE\n"
BLOCK2_NEW = '''
def run_stream_case(c: httpx.Client, tokens: dict, case: dict):
    """P4e S1-②:走 `/api/chat/stream`(SSE)的用例——用户真实路径的唯一自动化覆盖。

    case 字段:
      stream_kind  'basic'(①②③) | 'abort'(④) | 'gate'(⑤)
    """
    role = case.get("role", "student")
    hdr = {"Authorization": f"Bearer {tokens[role]}"}
    kind = case.get("stream_kind", "basic")
    payload = {"question": case["question"]}
    cid = None
    if kind == "abort":
        cr = c.post(f"{BASE}/api/conversations", headers=hdr, json={"title": "stream-abort-probe"})
        cr.raise_for_status()
        cid = cr.json()["id"]
        payload["conversation_id"] = cid

    bad: list = []
    t0 = time.time()
    kinds: list = []
    deltas: list = []
    delta_t: list = []
    post_retry: list = []
    seen_retry = False
    aborted_in_time = False
    done_ev: dict = {}
    with c.stream("POST", f"{BASE}/api/chat/stream", headers=hdr, json=payload) as r:
        r.raise_for_status()
        for ev in _sse_events(r):
            t_ms = (time.time() - t0) * 1000
            k = ev.get("type")
            kinds.append(k)
            if k == "delta":
                deltas.append(ev.get("content") or "")
                delta_t.append(t_ms)
                if seen_retry:
                    post_retry.append(ev.get("content") or "")
            elif k == "grounding_retry":
                seen_retry = True
            elif k == "done":
                done_ev = ev
            # ④ 收到第 1 个 delta 立即断开(且必须早于 done,否则无法验证回滚)
            if kind == "abort" and k == "delta" and not done_ev:
                aborted_in_time = True
                break
    e2e = (time.time() - t0) * 1000
    ttfb = delta_t[0] if delta_t else None
    span = (e2e - ttfb) if ttfb is not None else None

    if kind == "abort":
        # ④ P4b C5 不变量:客户端断开 → 该轮 user 消息被回滚(中止=该轮未发生)
        if not aborted_in_time:
            bad.append("未在收到 done 之前断开(无法验证回滚,按失败计)")
        time.sleep(1.5)  # 给服务端 CancelledError 回滚留出时间
        mr = c.get(f"{BASE}/api/conversations/{cid}/messages", headers=hdr, params={"limit": 100})
        mr.raise_for_status()
        msgs = mr.json()["messages"]
        users = [m for m in msgs if m["role"] == "user"]
        assts = [m for m in msgs if m["role"] == "assistant"]
        if users:
            bad.append(f"断开后会话 {cid} 仍残留 {len(users)} 条 user 消息"
                       f"(P4b C5 不变量被破坏):{users[0]['content'][:40]!r}")
        if assts:
            bad.append(f"断开后会话 {cid} 残留 {len(assts)} 条 assistant 消息")
        detail = ("; ".join(bad) if bad else
                  f"断开于首个 delta(TTFB={ttfb:.0f}ms),会话 {cid} 消息数 {len(msgs)} → 回滚成立")
        return (not bad), detail, "", [], None, {}

    # ① 事件序列语法
    bad += _check_stream_grammar(kinds)
    # ② delta 事件数 > 1 且 非「一条承载全文」
    n_delta = len(deltas)
    if n_delta <= 1:
        bad.append(f"delta 事件数 {n_delta} <= 1 → 退化成整段下发(真流式被关掉)")
    full = "".join(deltas)
    if n_delta >= 1 and full and max(len(d) for d in deltas) >= len(full) and n_delta <= 1:
        bad.append("单个 delta 承载了全部正文(一次性整段下发)")
    # ③ 渐进性:E2E - TTFB 必须 >= 阈值
    if ttfb is None:
        bad.append("全程未收到 delta(无法测 TTFB)")
    else:
        if span < STREAM_MIN_SPAN_MS:
            bad.append(f"E2E-TTFB = {span:.0f}ms < {STREAM_MIN_SPAN_MS}ms → 渐进性不存在"
                       f"(TTFB={ttfb:.0f}ms, E2E={e2e:.0f}ms, deltas={n_delta})")

    final = done_ev.get("answer") or ""
    ctx = done_ev.get("context") or {}
    gate = ctx.get("grounding_gate") or {}
    # 一致性:闸门命中 ⇔ 出现 grounding_retry(任何一侧缺失都是缺陷)
    if bool(gate.get("hit")) != seen_retry:
        bad.append(f"闸门命中({gate.get('hit')})与 grounding_retry({seen_retry})不一致;gate={gate}")

    if kind == "gate":
        # ⑤ 闸门命中 → 必须有 retry 事件,且最终落库答案是**重生后**的版本
        if not gate.get("hit"):
            bad.append(f"grounding_gate 未命中(gate={gate or '无'}) → 无法验证重生通道")
        if not seen_retry:
            bad.append(f"闸门命中却无 grounding_retry 事件(gate={gate})")
        else:
            after = "".join(post_retry)
            if not after:
                bad.append("grounding_retry 之后没有任何 delta(重生结果未下发)")
            elif after != final:
                bad.append(f"重生后下发文本 != done.answer(len {len(after)} vs {len(final)})"
                           f" → 落库/返回的可能不是重生版")
        conv_id = done_ev.get("conversation_id")
        if conv_id:
            mr = c.get(f"{BASE}/api/conversations/{conv_id}/messages", headers=hdr,
                       params={"limit": 100})
            mr.raise_for_status()
            assts = [m for m in mr.json()["messages"] if m["role"] == "assistant"]
            if not assts:
                bad.append("会话内无 assistant 落库消息")
            elif assts[-1]["content"] != final:
                bad.append(f"落库答案 != done.answer(len {len(assts[-1]['content'])} vs {len(final)})")
        else:
            bad.append("done 事件未回 conversation_id(无法核对落库)")

    detail = ("; ".join(bad) if bad else
              f"TTFB={ttfb:.0f}ms, E2E={e2e:.0f}ms, span={span:.0f}ms, deltas={n_delta}"
              f", retry={seen_retry}, gate={gate.get('hit')}")
    return (not bad), detail, final, done_ev.get("sources") or [], done_ev.get("conversation_id"), ctx

''' + BLOCK2_ANCHOR

# ---------------- 片段 3:类型分派 ----------------
BLOCK3_ANCHOR = '''                elif case["type"] == "rewrite":
                    # P4d C3: 口语化/噪声问句必须发生改写且最终召回达标来源
                    ok, detail, answer, sources, conversation_id, last_ctx = \\
                        run_rewrite_case(c, tokens, case)
                    turns_sent = 1
                else:
'''
BLOCK3_NEW = '''                elif case["type"] == "rewrite":
                    # P4d C3: 口语化/噪声问句必须发生改写且最终召回达标来源
                    ok, detail, answer, sources, conversation_id, last_ctx = \\
                        run_rewrite_case(c, tokens, case)
                    turns_sent = 1
                elif case["type"] == "stream_sse":
                    # P4e S1-②: 用户真实路径(流式 SSE)的自动化覆盖——坑 60 的直接落地
                    ok, detail, answer, sources, conversation_id, last_ctx = \\
                        run_stream_case(c, tokens, case)
                    turns_sent = 1
                else:
'''


def main() -> int:
    src = TARGET.read_text(encoding="utf-8")
    for name, anchor, new in (("BLOCK1", BLOCK1_ANCHOR, BLOCK1_NEW),
                              ("BLOCK2", BLOCK2_ANCHOR, BLOCK2_NEW),
                              ("BLOCK3", BLOCK3_ANCHOR, BLOCK3_NEW)):
        n = src.count(anchor)
        if n != 1:
            print(f"[FAIL] {name} 锚点命中 {n} 次(期望 1),未改动文件")
            return 1
        if name == "BLOCK2":
            src = src.replace(anchor, new, 1)
        else:
            src = src.replace(anchor, new, 1)
    TARGET.write_text(src, encoding="utf-8")
    print(f"[OK] 已注入 stream_sse 评测类型 → {TARGET}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
