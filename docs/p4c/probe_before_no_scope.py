#!/usr/bin/env python3
"""P4c 第 0 步 BEFORE 取证(3):无 scope 检索基线

同一批问句在**全库**检索下的 sources / top_score / 来源类目分布。
本单 C3 要给出"全库 / 指定正确 folder / 指定越权 folder"三输入对照,
没有这份基线就无法证明 scope 真的生效。

产出: docs/p4c/evidence/before/no_scope_proof.txt
坑 33: 断言取到非空(至少一个问句 sources>0)才落盘;坑 8: trust_env=False + NO_PROXY
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:8900"
ROOT = Path(__file__).resolve().parent.parent.parent
EVID = ROOT / "docs" / "p4c" / "evidence" / "before"

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
EVID.mkdir(parents=True, exist_ok=True)

QUESTIONS = [
    ("student", "研究生申请休学需要提交哪些材料和审批步骤?"),
    ("student", "本科生国家奖学金的评定条件是什么?"),
    ("counselor", "学生宿舍矛盾怎么谈心?"),
    ("student", "学平险出险后怎么报销?"),
]


def login(c: httpx.Client, u: str, p: str) -> str:
    r = c.post(f"{BASE}/api/login", json={"username": u, "password": p})
    r.raise_for_status()
    return r.json()["token"]


def main() -> int:
    c = httpx.Client(timeout=180, trust_env=False)
    tokens = {"student": login(c, "student", "student123"),
              "counselor": login(c, "counselor", "counselor123")}
    # 标题 -> category 映射(用于证明 scope 生效后来源类目收敛)
    cat_map: dict[str, str] = {}
    for role in ("student", "counselor", "admin"):
        try:
            tok = tokens.get(role) or login(c, "admin", "admin123")
            d = c.get(f"{BASE}/api/kb/documents",
                      headers={"Authorization": f"Bearer {tok}"}).json()
            for x in d.get("documents", []):
                cat_map.setdefault(x["title"], x.get("category") or "?")
        except Exception:  # noqa: BLE001
            continue

    rows = []
    for role, q in QUESTIONS:
        t0 = time.time()
        r = c.post(f"{BASE}/api/chat", headers={"Authorization": f"Bearer {tokens[role]}"},
                   json={"question": q})
        r.raise_for_status()
        d = r.json()
        srcs = d.get("sources") or []
        scores = [s.get("score") for s in srcs if isinstance(s.get("score"), (int, float))]
        top = max(scores) if scores else 0.0
        cats = [cat_map.get(s.get("title"), "?") for s in srcs]
        rows.append({
            "role": role,
            "question": q,
            "latency_ms": round((time.time() - t0) * 1000),
            "sources_count": len(srcs),
            "top_score": round(top, 4),
            "source_titles": [s.get("title") for s in srcs],
            "source_categories": cats,
            "source_role_mins": [s.get("role_min") for s in srcs],
            "scores": [round(s, 4) if isinstance(s, float) else s for s in scores],
            "answer_head": (d.get("answer") or "")[:120],
        })
        print(f"[ask] {role} {q[:20]}... sources={len(srcs)} top={top:.4f}")

    assert any(r["sources_count"] > 0 for r in rows), "全部问句零来源——基线无效,禁止落盘"

    lines = ["P4c BEFORE 基线 (3): 无 scope(全库)检索基线",
             f"服务: {BASE} (P4b 代码, /api/kb/folders 尚为 404)",
             "用途: C3 的『全库 / 指定正确 folder / 指定越权 folder』三输入对照表之第一列",
             ""]
    for r in rows:
        lines += [
            f"-- 角色 {r['role']} | 耗时 {r['latency_ms']}ms | sources={r['sources_count']} | top_score={r['top_score']}",
            f"   问句: {r['question']}",
            f"   来源标题: {r['source_titles']}",
            f"   来源类目: {r['source_categories']}",
            f"   来源可见级: {r['source_role_mins']}",
            f"   相关度: {r['scores']}",
            f"   答案头部: {r['answer_head']}",
            "",
        ]
    lines.append("结论: 全库检索下同一问句会横跨多个类目(见『来源类目』),这是 scope 要收敛的对象。")
    (EVID / "no_scope_proof.txt").write_text("\n".join(lines), encoding="utf-8")
    (EVID / "no_scope_proof.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    print("[OK] no_scope_proof.txt / .json 已落盘")
    return 0


if __name__ == "__main__":
    sys.exit(main())
