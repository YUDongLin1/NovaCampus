#!/usr/bin/env python3
"""NovaAgent 评测引擎 v1 — 对接 /api/* 执行评测集

用例类型:
  qa             检索问答:回答须命中 expect_keywords 且有引用
  refusal        拒答:回答须明示"知识库未覆盖"或无引用
  permission_api API 权限:期待指定 HTTP 状态码(403/404)
  kb_hidden      知识层权限:回答不得引用 hidden_marker 文档

用法:NO_PROXY="127.0.0.1,localhost" python run_evals.py [--base http://127.0.0.1:8900]
前置:NovaAgent 与 weekly-mcp 已启动。语料缺失时自动以 counselor 身份播种 seed_corpus/。
报告:reports/eval_report_<时间戳>.json
"""
from __future__ import annotations

import argparse
import io
import json
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
    missing = [kw for kw in case["expect_keywords"] if kw not in answer]
    if missing:
        return False, f"回答未命中关键词: {missing}(引用 {[s['title'] for s in sources]})"
    return True, f"命中 {case['expect_keywords']},引用 {len(sources)} 条"


def judge_refusal(case: dict, answer: str, sources: list) -> tuple[bool, str]:
    declined = (not sources) or any(m in answer for m in REFUSAL_MARKS)
    if declined:
        return True, "正确拒答" + ("(无引用)" if not sources else "(明示未覆盖)")
    return False, f"不应回答却给出了内容,引用: {[s['title'] for s in sources]}"


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
            try:
                if case["type"] == "permission_api":
                    method = case["method"]
                    body = {"question": "x"} if method == "POST" and "chat" in case["path"] else None
                    r = c.request(method, BASE + case["path"], headers={"Authorization": f"Bearer {tokens[case['role']]}"},
                                  json=body)
                    ok, detail = (r.status_code == case["expect_status"],
                                  f"{method} {case['path']} → {r.status_code}(期待 {case['expect_status']})")
                    answer, sources = "", []
                else:
                    r = c.post(f"{BASE}/api/chat", headers={"Authorization": f"Bearer {tokens[case['role']]}"},
                               json={"question": case["question"]})
                    r.raise_for_status()
                    d = r.json()
                    answer, sources = d.get("answer", ""), d.get("sources", [])
                    if case["type"] == "qa":
                        ok, detail = judge_qa(case, answer, sources)
                    elif case["type"] == "refusal":
                        ok, detail = judge_refusal(case, answer, sources)
                    else:
                        ok, detail = judge_kb_hidden(case, answer, sources)
            except httpx.HTTPStatusError as e:
                ok, detail = False, f"HTTP {e.response.status_code}: {e.response.text[:120]}"
            recall = compute_recall(case, sources) if case["type"] == "qa" else None
            faith, fmethod = (None, "na")
            if case["type"] == "qa":
                faith, fmethod = faithfulness.judge(case.get("question", ""), answer, sources)
            results.append({**case, "pass": ok, "detail": detail,
                            "recall_at_k": recall,
                            "faithfulness": faith, "faithfulness_method": fmethod,
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
             "total_pass": total_pass, "total": total, "results": results},
            ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n[report] {out}")
        return 0 if total_pass == total else 1


if __name__ == "__main__":
    sys.exit(run())
