#!/usr/bin/env python3
"""NovaAgent 评测引擎 v1 — 对接 /api/* 执行评测集

用例类型:
  qa                    检索问答:回答须命中 expect_keywords 且有引用
  refusal               拒答:回答须明示"知识库未覆盖"或无引用
  permission_api        API 权限:期待指定 HTTP 状态码(403/404)
  kb_hidden             知识层权限:回答不得引用 hidden_marker 文档
  ---- P4b-fix ③ 新增(新代码路径覆盖,坑 22) ----
  multiturn             多轮:turns[].question 逐轮携带 conversation_id;末轮答案命中
                        expect_keywords,expect_context 断言 history_gate=hit 等门控标志
  context_compress      压缩:case.plant{turns,chars,facts} 经 API 种植超预算历史,
                        末轮断言 expect_context.compressed=true 且关键数字仍在答案
  refusal_followup      有历史+域内无据追问 → 必须走 build_refusal 确定性模板
                        (「系统模板生成」指纹 + expect_absent_keywords 禁自拟出口)
  history_false_premise 用户断言假事实 → 不得复述其金额/渠道/经办人(expect_absent_keywords)

用法:NO_PROXY="127.0.0.1,localhost" python run_evals.py [--base http://127.0.0.1:8900]
前置:NovaAgent 与 weekly-mcp 已启动。语料缺失时自动以 counselor 身份播种 seed_corpus/。
报告:reports/eval_report_<时间戳>.json;评测隔离断言(全量)失败 → 退出码非 0(P4b-fix ②)。
"""
from __future__ import annotations

import argparse
import io
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx

try:  # Windows GBK 控制台防 emoji 编码崩溃(T2 同款修复, 独立于 PYTHONIOENCODING)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError, OSError):
    pass

import faithfulness  # LLM-as-judge:复用 novaagent 模型配置(只读导入)

BASE = "http://127.0.0.1:8900"
HERE = Path(__file__).parent
SEED_ROLES = {
    "EVAL-研究生学籍管理规定.md": "student",
    "EVAL-研究生奖学金评定办法.md": "student",
    "EVAL-学生请假管理办法.md": "student",
    "EVAL-辅导员内部工作备忘.md": "counselor",
}
REFUSAL_MARKS = ("暂无", "没有找到", "未检索", "知识库中未", "无法回答", "不在知识库", "没有相关")


def login(c: httpx.Client, username: str, password: str) -> str:
    r = c.post(f"{BASE}/api/login", json={"username": username, "password": password})
    r.raise_for_status()
    return r.json()["token"]


def seed_corpus_if_needed(c: httpx.Client, counselor_token: str) -> int:
    """按标题前缀 EVAL- 检查是否已播种,缺哪个补哪个。返回本次上传数。"""
    docs = c.get(f"{BASE}/api/kb/documents", headers={"Authorization": f"Bearer {counselor_token}"}).json()
    existing = {d["title"] for d in docs["documents"]}
    uploaded = 0
    for fname, role_min in SEED_ROLES.items():
        title = fname.rsplit(".", 1)[0]
        if title in existing:
            continue
        path = HERE / "seed_corpus" / fname
        r = c.post(
            f"{BASE}/api/kb/upload",
            headers={"Authorization": f"Bearer {counselor_token}"},
            files={"file": (fname, io.BytesIO(path.read_bytes()), "text/markdown")},
            data={"role_min": role_min},
        )
        r.raise_for_status()
        uploaded += 1
        time.sleep(0.2)
    return uploaded


def judge_qa(case: dict, answer: str, sources: list) -> tuple[bool, str]:
    if not sources:
        return False, "无引用来源"
    # T6 ⑥a 措辞加固:条目为 str(必含)或 list(any-of,任一同义词命中即可)
    missing = []
    for kw in case["expect_keywords"]:
        alts = kw if isinstance(kw, list) else [kw]
        if not any(a in answer for a in alts):
            missing.append("/".join(alts))
    if missing:
        return False, f"回答未命中关键词: {missing}(引用 {[s['title'] for s in sources]})"
    return True, f"命中 {case['expect_keywords']},引用 {len(sources)} 条"


def judge_refusal(case: dict, answer: str, sources: list) -> tuple[bool, str]:
    declined = (not sources) or any(m in answer for m in REFUSAL_MARKS)
    if declined:
        return True, "正确拒答" + ("(无引用)" if not sources else "(明示未覆盖)")
    return False, f"不应回答却给出了内容,引用: {[s['title'] for s in sources]}"


def judge_refusal_indomain(case: dict, answer: str, sources: list) -> tuple[bool, str]:
    """P4a C7:域内无据拒答判定——拒答 + 无越界 [n] + 出口信息 + 不夹带无据断言。"""
    declined = any(m in answer for m in REFUSAL_MARKS)
    if not declined:
        return False, f"域内无据问题未拒答反而作答,引用: {[s['title'] for s in sources]}"
    bad_refs = sorted({int(n) for n in re.findall(r"\[(\d+)\]", answer) if int(n) > len(sources)})
    if bad_refs:
        return False, f"越界引用未剥离: {bad_refs}(sources={len(sources)})"
    if len(sources) == 0 and re.search(r"\[\d+\]", answer):
        return False, "无来源却仍含 [n] 引用(虚构引用)"
    contact = case.get("expect_contact")
    if contact and contact not in answer:
        return False, f"拒答未含出口信息({contact})"
    absent = [k for k in case.get("expect_absent_keywords", []) if k and k in answer]
    if absent:
        return False, f"拒答/答案夹带无据断言: {absent}"
    return True, f"域内无据正确拒答(sources={len(sources)},出口与断言检查通过)"


def judge_kb_hidden(case: dict, answer: str, sources: list) -> tuple[bool, str]:
    cited = [s["title"] for s in sources if case["hidden_marker"] in s["title"]]
    if cited:
        return False, f"越权引用了受限文档: {cited}"
    declined = (not sources) or any(m in answer for m in REFUSAL_MARKS)
    return True, ("未泄露受限文档;" + ("正确拒答" if declined else "回答了但未引用受限内容"))


def compute_recall(case: dict, sources: list) -> float | None:
    """Recall@k:expect_sources(标题子串)在返回 sources 标题中的命中比例。"""
    expect = case.get("expect_sources") or []
    if not expect:
        return None
    titles = [s.get("title", "") for s in sources]
    hit = sum(1 for sub in expect if any(sub in t for t in titles))
    return round(hit / len(expect), 4)


# ---------- P4b-fix ③: 新代码路径用例的执行与判定 ----------

CHAT_TURN_TYPES = {"multiturn", "context_compress", "refusal_followup", "history_false_premise"}
_TEMPLATE_MARK = "系统模板生成"  # refusal.build_refusal 确定性模板指纹(模型自由发挥不会有)


def kw_missing(keywords: list, answer: str) -> list[str]:
    """与 judge_qa 同款 any-of 语义:条目为 str(必含)或 list(任一同义词命中)。"""
    missing = []
    for kw in keywords:
        alts = kw if isinstance(kw, list) else [kw]
        if not any(a in answer for a in alts):
            missing.append("/".join(alts))
    return missing


def ctx_mismatch(case: dict, ctx: dict) -> list[str]:
    """expect_context: 断言门控/压缩标志等上下文状态,证明新代码路径真的被执行。"""
    bad = []
    for k, v in (case.get("expect_context") or {}).items():
        if ctx.get(k) != v:
            bad.append(f"context.{k}={ctx.get(k)!r}(期待 {v!r})")
    return bad


def judge_history_answer(case: dict, answer: str, ctx: dict) -> tuple[bool, str]:
    """multiturn / context_compress: 末轮答案命中关键词 + 上下文标志断言。"""
    bad = ctx_mismatch(case, ctx)
    missing = kw_missing(case["expect_keywords"], answer)
    if missing or bad:
        return False, f"未命中关键词: {missing};上下文断言失败: {bad};答案头部: {answer[:80]!r}"
    return True, f"命中 {case['expect_keywords']};上下文断言通过 {case.get('expect_context')}"


def judge_refusal_template(case: dict, answer: str, sources: list, ctx: dict) -> tuple[bool, str]:
    """refusal_followup / history_false_premise: 必须走确定性模板且零复述禁语。"""
    declined = any(m in answer for m in REFUSAL_MARKS)
    if not declined:
        return False, f"无据追问未拒答反而作答,引用: {[s['title'] for s in sources]}"
    if case.get("expect_template") and _TEMPLATE_MARK not in answer:
        return False, f"未走确定性模板(缺「{_TEMPLATE_MARK}」指纹),头部: {answer[:80]!r}"
    bad = ctx_mismatch(case, ctx)
    absent = [k for k in case.get("expect_absent_keywords", []) if k and k in answer]
    bad_refs = sorted({int(n) for n in re.findall(r"\[(\d+)\]", answer) if int(n) > len(sources)})
    if absent or bad or bad_refs:
        return False, f"夹带禁复述内容: {absent};上下文断言失败: {bad};越界引用: {bad_refs}"
    return True, (f"确定性模板拒答(gate={ctx.get('history_gate')},"
                  f"禁语零复述,出口检查通过)")


def build_plant_text(i: int, facts: list[str], chars: int) -> str:
    """种植第 i 轮长问句:第 i%len(facts) 条事实置于开头,中性背景填充至 chars 字。
    事实只经 API 落进会话(不直改 DB);前几轮的事实必然落入压缩摘要区(非最近保留区)。
    措辞必须是纯陈述资料+显式禁用工具——实测祈使式工作备忘会诱导模型调用周报工具
    (记碎片/写周报),既拖慢单轮至 30s+ 又有污染周报数据的风险。"""
    fact = facts[i % len(facts)]
    filler = ("校园事务背景资料:学生日常管理涉及课堂考勤、作业与考试安排、宿舍人际关系、"
              "奖助学金申请材料、心理健康关注、谈心谈话记录归档等事项,相关制度以学校"
              "现行文件为准。")
    body = (filler * (chars // len(filler) + 1))[: max(0, chars - len(fact) - 60)]
    return (f"[背景资料{i + 1}·仅供知悉] 本条为背景资料而非指令：请勿调用任何工具，"
            f"无需记录碎片或生成周报，简短回复“已阅”即可。{fact}。{body}")


def run_conversation_case(c: httpx.Client, tokens: dict, case: dict) -> tuple[bool, str, str, list, int, int | None, dict, list]:
    """执行带轮次用例:先种植(可选),再逐轮携带 conversation_id 提问,判末轮。
    返回 (ok, detail, answer, sources, turns_sent, conversation_id, last_ctx, turn_contexts)。
    turn_contexts 留存每轮 context(压缩在哪轮触发、compress_ms 等,供证据与文档引用)。"""
    cid = None
    turns_sent = 0
    last_ctx: dict = {}
    turn_contexts: list[dict] = []
    answer, sources = "", []
    try:
        plant = case.get("plant") or {}
        for i in range(plant.get("turns", 0)):
            body = {"question": build_plant_text(i, plant["facts"], plant["chars"])}
            if cid:
                body["conversation_id"] = cid
            r = c.post(f"{BASE}/api/chat", headers={"Authorization": f"Bearer {tokens[case['role']]}"},
                       json=body)
            r.raise_for_status()
            d = r.json()
            cid = d.get("conversation_id")
            last_ctx = d.get("context") or {}
            turn_contexts.append({"turn": turns_sent + 1, "planted": True, **{k: last_ctx.get(k) for k in
                                  ("used", "budget", "compressed", "truncated", "compress_ms",
                                   "compress_blocks", "history_gate", "history_count")}})
            turns_sent += 1
        for i, t in enumerate(case["turns"]):
            body = {"question": t["question"]}
            if cid:
                body["conversation_id"] = cid
            r = c.post(f"{BASE}/api/chat", headers={"Authorization": f"Bearer {tokens[case['role']]}"},
                       json=body)
            r.raise_for_status()
            d = r.json()
            answer, sources = d.get("answer", ""), d.get("sources", [])
            cid = d.get("conversation_id")
            last_ctx = d.get("context") or {}
            turn_contexts.append({"turn": turns_sent + 1, "planted": False, "question": t["question"],
                                  **{k: last_ctx.get(k) for k in ("used", "budget", "compressed",
                                                                  "truncated", "compress_ms", "compress_blocks",
                                                                  "history_gate", "followup_no_new_sources",
                                                                  "history_count")}})
            turns_sent += 1
        if case["type"] in ("multiturn", "context_compress"):
            ok, detail = judge_history_answer(case, answer, last_ctx)
        else:
            ok, detail = judge_refusal_template(case, answer, sources, last_ctx)
        return ok, detail, answer, sources, turns_sent, cid, last_ctx, turn_contexts
    except httpx.HTTPStatusError as e:
        return False, f"HTTP {e.response.status_code}: {e.response.text[:120]}", "", [], turns_sent, cid, last_ctx, turn_contexts


def run() -> int:
    global BASE
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=BASE)
    args = ap.parse_args()
    BASE = args.base.rstrip("/")

    spec = json.loads((HERE / "cases.json").read_text(encoding="utf-8"))
    cases = spec["cases"]

    with httpx.Client(timeout=180) as c:
        admin = login(c, "admin", "admin123")
        counselor = login(c, "counselor", "counselor123")
        student = login(c, "student", "student123")
        tokens = {"admin": admin, "counselor": counselor, "student": student}
        n = seed_corpus_if_needed(c, counselor)
        if n:
            print(f"[seed] 播种评测语料 {n} 篇")
        print(f"[eval] 共 {len(cases)} 条用例\n")

        results = []
        for case in cases:
            t0 = time.time()
            conversation_id = None  # P4b C7: 每个用例独立会话(自动新建)
            first_question = case.get("question", "")
            turns_sent = 1
            last_ctx: dict = {}
            turn_ctxs: list = []
            try:
                if case["type"] == "permission_api":
                    method = case["method"]
                    body = {"question": "x"} if method == "POST" and "chat" in case["path"] else None
                    r = c.request(method, BASE + case["path"], headers={"Authorization": f"Bearer {tokens[case['role']]}"},
                                  json=body)
                    ok, detail = (r.status_code == case["expect_status"],
                                  f"{method} {case['path']} → {r.status_code}(期待 {case['expect_status']})")
                    answer, sources = "", []
                elif case["type"] in CHAT_TURN_TYPES:
                    # P4b-fix ③: 多轮/压缩/追问门控/假前提用例——逐轮携带 conversation_id
                    ok, detail, answer, sources, turns_sent, conversation_id, last_ctx, turn_ctxs = \
                        run_conversation_case(c, tokens, case)
                    first_question = case["turns"][0]["question"]
                    if (case.get("plant") or {}).get("turns"):
                        first_question = build_plant_text(0, case["plant"]["facts"], case["plant"]["chars"])
                else:
                    r = c.post(f"{BASE}/api/chat", headers={"Authorization": f"Bearer {tokens[case['role']]}"},
                               json={"question": case["question"]})
                    r.raise_for_status()
                    d = r.json()
                    answer, sources = d.get("answer", ""), d.get("sources", [])
                    conversation_id = d.get("conversation_id")
                    last_ctx = d.get("context") or {}
                    if case["type"] == "qa":
                        ok, detail = judge_qa(case, answer, sources)
                    elif case["type"] == "refusal":
                        ok, detail = judge_refusal(case, answer, sources)
                    elif case["type"] == "refusal_indomain":
                        ok, detail = judge_refusal_indomain(case, answer, sources)
                    else:
                        ok, detail = judge_kb_hidden(case, answer, sources)
            except httpx.HTTPStatusError as e:
                ok, detail = False, f"HTTP {e.response.status_code}: {e.response.text[:120]}"
                answer, sources = "", []
            recall = compute_recall(case, sources) if case["type"] == "qa" else None
            faith, fmethod = (None, "na")
            if case["type"] == "qa":
                faith, fmethod = faithfulness.judge(case.get("question", ""), answer, sources)
            results.append({**case, "pass": ok, "detail": detail,
                            "recall_at_k": recall,
                            "faithfulness": faith, "faithfulness_method": fmethod,
                            "conversation_id": conversation_id,
                            "first_question": first_question,
                            "turns_sent": turns_sent,
                            "last_context": last_ctx,
                            "turn_contexts": turn_ctxs if case["type"] in CHAT_TURN_TYPES else [],
                            "latency_ms": round((time.time() - t0) * 1000)})
            mark = "[PASS]" if ok else "[FAIL]"
            extra = f" | R@k={recall} 忠实度={faith}({fmethod})" if case["type"] == "qa" else ""
            print(f"{mark} {case['id']:10s} [{case['type']:14s}] {detail}{extra}")

        by_type: dict[str, dict] = {}
        for r in results:
            s = by_type.setdefault(r["type"], {"total": 0, "pass": 0})
            s["total"] += 1
            s["pass"] += int(r["pass"])
        total_pass = sum(s["pass"] for s in by_type.values())
        total = len(results)
        print("\n===== 汇总 =====")
        for t, s in by_type.items():
            print(f"  {t:16s} {s['pass']}/{s['total']}")
        print(f"  {'TOTAL':16s} {total_pass}/{total}({total_pass / total:.0%})")

        # P4b-fix ②: 评测隔离断言——对【全部】带会话的用例(36+新增)逐会话核对,不再只抽首末:
        #   a) 全局 message id 归属唯一(任一 id 出现在两个会话即串台,等价两两交集为空);
        #   b) 每会话首条 user 消息 == 该用例实际发出的第一问(无外来内容);
        #   c) 每会话 user 消息条数 == 该用例应发轮数(多轮/种植轮计入)。
        # 断言失败(含拉取消息失败,fail-closed)必须让退出码非 0——隔离被破坏时评测不得绿。
        iso_errors: list[str] = []
        conv_cases = [(r["id"], r["role"], r["first_question"], r["conversation_id"], r["turns_sent"])
                      for r in results if r.get("conversation_id")]
        id_owner: dict[int, str] = {}
        try:
            for case_id, role, first_q, cid, n_turns in conv_cases:
                # 用各用例自己的角色 token 拉取(counselor/admin 用例的会话对 student 是 404)
                mr = c.get(f"{BASE}/api/conversations/{cid}/messages",
                           headers={"Authorization": f"Bearer {tokens[role]}"},
                           params={"limit": 500})
                mr.raise_for_status()
                msgs = mr.json()["messages"]
                for m in msgs:
                    prev = id_owner.setdefault(m["id"], case_id)
                    if prev != case_id:
                        iso_errors.append(f"消息 {m['id']} 同时出现在 {prev} 与 {case_id} 的会话(串台)")
                users = [m for m in msgs if m["role"] == "user"]
                if not users or users[0]["content"] != first_q:
                    head = users[0]["content"][:40] if users else "(无 user 消息)"
                    iso_errors.append(f"{case_id} 会话 {cid} 首条 user 消息不匹配: {head!r}")
                if len(users) != n_turns:
                    iso_errors.append(f"{case_id} 会话 {cid} user 消息数 {len(users)} != 应发轮数 {n_turns}")
        except Exception as e:  # fail-closed:取不到消息也算隔离断言失败
            iso_errors.append(f"隔离断言执行失败: {e}")
        iso_ok = not iso_errors
        if iso_ok:
            print(f"\n[P4b C7 评测隔离] {len(conv_cases)} 个带会话用例全量核对:"
                  f"message id 全局唯一(两两交集为空)、首问逐字匹配、user 条数=应发轮数 → 隔离成立")
        else:
            print(f"\n[P4b C7 评测隔离] 断言失败 {len(iso_errors)} 处(退出码将非 0):")
            for e in iso_errors[:10]:
                print(f"  - {e}")

        recalls = [r["recall_at_k"] for r in results if r["type"] == "qa" and r.get("recall_at_k") is not None]
        faiths = [(r["faithfulness"], r["faithfulness_method"]) for r in results
                  if r["type"] == "qa" and r.get("faithfulness") is not None]
        summary: dict = dict(by_type)
        summary["recall_at_k_avg"] = round(sum(recalls) / len(recalls), 4) if recalls else None
        summary["faithfulness_avg"] = round(sum(f for f, _ in faiths) / len(faiths), 4) if faiths else None
        summary["faithfulness_method"] = ("llm" if faiths and all(m == "llm" for _, m in faiths)
                                          else "proxy" if faiths else "na")
        ref = by_type.get("refusal", {"pass": 0, "total": 0})
        summary["refusal_accuracy"] = round(ref["pass"] / ref["total"], 4) if ref["total"] else None
        print(f"  Recall@k 均值: {summary['recall_at_k_avg']} | 忠实度均值: {summary['faithfulness_avg']}"
              f"({summary['faithfulness_method']}) | 拒答准确率: {summary['refusal_accuracy']}")

        out = HERE.parent / "reports" / f"eval_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        out.parent.mkdir(exist_ok=True)
        out.write_text(json.dumps(
            {"version": spec["version"], "base": BASE, "summary": summary,
             "total_pass": total_pass, "total": total, "results": results,
             "eval_isolation": {"ok": iso_ok, "checked_conversations": len(conv_cases),
                                "errors": iso_errors}},
            ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n[report] {out}")
        # P4b-fix ②: 隔离断言失败与用例失败同等阻塞——退出码非 0
        return 0 if (total_pass == total and iso_ok) else 1


if __name__ == "__main__":
    sys.exit(run())
