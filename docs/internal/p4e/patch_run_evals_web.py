#!/usr/bin/env python3
"""P4e M-D: 给 `evals/run_evals.py` 注入 `web_grounded` 评测类型(开/关对照 + 反向断言)。

动机(HANDOFF 坑 48):没有对照的差异等于没做。本类型**必须成对出现**——
同一构造问句,开 → 联网分区/URL 可点/整段声明;关 → 走 P4a 确定性拒答模板。
另有**反向断言**:答案正文不得出现逐句绑定的 `[W<n>]` 角标(上游无 index↔句子映射,
自建对应关系是假精确,坑 59 同形状——改进后的断言必须能判红)。

两处精确插入(锚点 count 断言):
  1. `def run()` 之前追加 `run_web_grounded_case()`
  2. 类型分派:stream_sse 分支之后、`else:` 之前插入 web_grounded 分支

用法: novaagent/.venv/Scripts/python.exe docs/p4e/patch_run_evals_web.py
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

BLOCK1_ANCHOR = "\ndef run() -> int:\n    global BASE\n"
BLOCK1_NEW = '''
# P4e M-A/M-D:联网来源分区展示的判据。
# ⚠ 反向断言(坑 39/52):上游 Responses API 每条来源**只给 {type,url}**,
#   正文零 `[n]` 角标、零内联 URL、`annotations` 为空 → **不存在「哪句出自哪条 URL」的映射**。
#   因此规格定稿:index 仅作列表编号,**不得把 [W<n>] 绑定到具体句子**。
#   本正则就是这条红线的可执行形式——它一旦命中即判 FAIL,防止以后有人做成假精确。
_W_CITATION_RE = re.compile(r"\\[W\\d+\\]")


def run_web_grounded_case(c: httpx.Client, tokens: dict, case: dict):
    """P4e M-D:联网搜索**开/关对照**用例(坑 48:没有对照的差异等于没做)。"""
    role = case.get("role", "student")
    hdr = {"Authorization": f"Bearer {tokens[role]}"}
    want_on = bool(case.get("web_search", False))
    r = c.post(f"{BASE}/api/chat", headers=hdr,
               json={"question": case["question"], "web_search": want_on})
    r.raise_for_status()
    d = r.json()
    answer = d.get("answer") or ""
    sources = d.get("sources") or []
    web_sources = d.get("web_sources") or []
    ctx = d.get("context") or {}
    bad: list = []

    # 开关是否真的生效:以服务端 trace 的 web_called 为唯一证据(不看前端/不看答案措辞)
    if bool(ctx.get("web_called")) != want_on:
        bad.append(f"trace web_called={ctx.get('web_called')} != 请求开关 {want_on}(开关没生效)")
    # 分区不混编号:本地 [1..n] 与联网来源不得共用 ref 编号体系
    local_refs = {s.get("ref") for s in sources}
    for ws in web_sources:
        if ws.get("ref") in local_refs:
            bad.append(f"联网来源 ref {ws.get('ref')} 与本地来源编号冲突(分区编号混了)")

    if want_on:
        need = int(case.get("expect_web_sources_min") or 1)
        if len(web_sources) < need:
            bad.append(f"联网来源 {len(web_sources)} 条 < 期望 {need} 条;web_error={ctx.get('web_error')!r}")
        for ws in web_sources:
            url = str(ws.get("url") or "")
            if not url.startswith(("http://", "https://")):
                bad.append(f"联网来源 URL 不可点: {url[:60]!r}")
            if not ws.get("site_name"):
                bad.append(f"联网来源缺 site_name: {url[:60]!r}")
            elif not ws.get("site_name_derived"):
                bad.append(f"站点名未标注为「由 URL 推导」: {ws.get('site_name')!r}")
        for mark in (case.get("expect_web_declaration") or []):
            if mark not in answer:
                bad.append(f"答案缺少整段级声明 {mark!r}(不得改成逐句角标)")
        miss = kw_missing(case.get("expect_keywords") or [], answer)
        if miss:
            bad.append(f"答案未命中: {miss}; 头部: {answer[:100]!r}")
    else:
        if web_sources:
            bad.append(f"开关关闭却返回 {len(web_sources)} 条联网来源")
        if _TEMPLATE_MARK not in answer:
            bad.append(f"开关关闭未走 P4a 确定性拒答模板(缺 {_TEMPLATE_MARK!r});头部: {answer[:100]!r}")
        if ctx.get("web_called"):
            bad.append("开关关闭却发起了联网请求(合规红线)")
        for kw in (case.get("expect_absent_keywords") or []):
            if kw in answer:
                bad.append(f"关闭态答案夹带联网内容痕迹: {kw!r}")

    # 反向断言(两条方向都判):正文不得出现逐句绑定的 [W<n>] 角标
    if case.get("expect_no_w_citation", True):
        hits = sorted(set(_W_CITATION_RE.findall(answer)))
        if hits:
            bad.append(f"答案正文出现逐句绑定的 [W<n>] 角标 {hits} —— 上游无句子↔URL 映射,属假精确")

    detail = ("; ".join(bad) if bad else
              f"web={'on' if want_on else 'off'}: web_called={ctx.get('web_called')}, "
              f"web_ms={ctx.get('web_ms')}, web_n_sources={ctx.get('web_n_sources')}, "
              f"web_error={ctx.get('web_error')!r}, 本地来源 {len(sources)} 条, 联网 {len(web_sources)} 条")
    return (not bad), detail, answer, sources, d.get("conversation_id"), ctx

''' + BLOCK1_ANCHOR

BLOCK2_ANCHOR = '''                elif case["type"] == "stream_sse":
                    # P4e S1-②: 用户真实路径(流式 SSE)的自动化覆盖——坑 60 的直接落地
                    ok, detail, answer, sources, conversation_id, last_ctx = \\
                        run_stream_case(c, tokens, case)
                    turns_sent = 1
                else:
'''
BLOCK2_NEW = '''                elif case["type"] == "stream_sse":
                    # P4e S1-②: 用户真实路径(流式 SSE)的自动化覆盖——坑 60 的直接落地
                    ok, detail, answer, sources, conversation_id, last_ctx = \\
                        run_stream_case(c, tokens, case)
                    turns_sent = 1
                elif case["type"] == "web_grounded":
                    # P4e M-D: 联网开/关对照(坑 48)+ 反向断言(禁 [W<n>] 逐句绑定)
                    ok, detail, answer, sources, conversation_id, last_ctx = \\
                        run_web_grounded_case(c, tokens, case)
                    turns_sent = 1
                else:
'''


def main() -> int:
    src = TARGET.read_text(encoding="utf-8")
    for name, anchor, new in (("BLOCK1", BLOCK1_ANCHOR, BLOCK1_NEW),
                              ("BLOCK2", BLOCK2_ANCHOR, BLOCK2_NEW)):
        n = src.count(anchor)
        if n != 1:
            print(f"[FAIL] {name} 锚点命中 {n} 次(期望 1),未改动文件")
            return 1
        src = src.replace(anchor, new, 1)
    TARGET.write_text(src, encoding="utf-8")
    print(f"[OK] 已注入 web_grounded 评测类型 → {TARGET}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
