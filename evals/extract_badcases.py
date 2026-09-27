#!/usr/bin/env python3
"""bad case 提取器(T2)— 从评测报告提取失败用例,维护 evals/badcases.json

用法(每次 run_evals.py 之后执行):
  python evals/extract_badcases.py

行为:
  1. 按时间戳从旧到新扫描 reports/eval_report_*.json;
  2. 抽取所有 pass=false 用例,按用例 id 合并进 badcases.json(只增不删);
  3. 状态机(以最新一份报告为准自动流转,人工字段 note 永不覆盖):
       open     待迭代(默认;最新报告仍失败)
       fixing   修复中(人工置,提取器不改)
       fixed    已修复(最新报告通过时由 open/fixing 自动翻转,记录 fixed_in;
                若已 fixed 的用例再次失败 → 自动重开为 open,标记回归)
       wontfix  不修复(人工置,提取器不改)
  4. 全部通过时快照为空,并打印说明。

badcases.json 是累积档案:条目永不删除,保证迭代叙事有完整证据链。
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPORTS_DIR = ROOT / "reports"
OUT_PATH = ROOT / "evals" / "badcases.json"

MANUAL_STATUSES = {"fixing", "wontfix"}  # 人工状态,提取器不覆盖


def load_reports() -> list[dict]:
    """按文件名时间戳从旧到新加载评测报告。"""
    reports = []
    for p in sorted(REPORTS_DIR.glob("eval_report_*.json")):
        m = re.search(r"(\d{8}_\d{6})", p.name)
        ts = m.group(1) if m else "19700101_000000"
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            print(f"[warn] 跳过无法解析的报告 {p.name}: {e}")
            continue
        reports.append({"file": p.name, "ts": ts, "data": data})
    return sorted(reports, key=lambda r: r["ts"])


def describe_expect(case: dict) -> str:
    t = case.get("type")
    if t == "qa":
        return "命中关键词 " + "、".join(case.get("expect_keywords", []))
    if t == "refusal":
        return "明示知识库未覆盖(正确拒答)"
    if t == "permission_api":
        return f"HTTP {case.get('expect_status')}"
    if t == "kb_hidden":
        return f"不得引用《{case.get('hidden_marker')}》"
    return "(未知类型)"


def latest_by_id(reports: list[dict]) -> dict[str, dict]:
    """每个用例 id 在最新报告中的结果。"""
    latest: dict[str, dict] = {}
    for rep in reports:
        for r in rep["data"].get("results", []):
            if r.get("id"):
                latest[r["id"]] = r
    return latest


def main() -> int:
    reports = load_reports()
    if not reports:
        print(f"[extract] {REPORTS_DIR} 下没有 eval_report_*.json,未做任何变更。")
        return 0

    archive: dict = {"version": 1, "updated_at": "", "note": "累积档案:只增不删,废弃用 wontfix 标记", "cases": []}
    if OUT_PATH.exists():
        try:
            archive = json.loads(OUT_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            backup = OUT_PATH.with_suffix(".broken.json")
            backup.write_text(OUT_PATH.read_text(encoding="utf-8"), encoding="utf-8")
            print(f"[warn] 原 badcases.json 损坏,已备份到 {backup.name} 并重建")
    cases_by_id = {c["id"]: c for c in archive.get("cases", [])}

    latest = latest_by_id(reports)
    stats = {"new": 0, "still_failing": 0, "auto_fixed": 0, "reopened": 0}

    for rep in reports:
        for r in rep["data"].get("results", []):
            if r.get("pass"):
                continue  # 只提取失败用例
            cid = r["id"]
            hist = {"report": rep["file"], "detail": r.get("detail", ""), "at": rep["ts"]}
            if cid not in cases_by_id:
                stats["new"] += 1
                cases_by_id[cid] = {
                    "id": cid,
                    "type": r.get("type", ""),
                    "role": r.get("role", ""),
                    "question": r.get("question") or f"{r.get('method', '')} {r.get('path', '')}".strip(),
                    "expect": describe_expect(r),
                    "actual": r.get("detail", ""),
                    "status": "open",
                    "note": r.get("note", ""),
                    "first_seen": rep["ts"],
                    "last_seen": rep["ts"],
                    "fixed_in": "",
                    "history": [hist],
                }
            else:
                entry = cases_by_id[cid]
                entry["last_seen"] = rep["ts"]
                entry["actual"] = r.get("detail", "")
                entry["history"].append(hist)
                if entry["status"] == "fixed":
                    entry["status"] = "open"  # 已修复又失败 → 回归,自动重开
                    stats["reopened"] += 1

    # 以最新报告为准做状态流转
    for cid, entry in cases_by_id.items():
        if cid not in latest:
            continue
        if latest[cid].get("pass"):
            if entry["status"] == "open":
                entry["status"] = "fixed"
                entry["fixed_in"] = reports[-1]["file"]
                stats["auto_fixed"] += 1
            elif entry["status"] == "fixing":
                entry["fixed_in"] = reports[-1]["file"]  # 提示人工确认,不改状态
        else:
            if entry["status"] == "open":
                stats["still_failing"] += 1

    archive["cases"] = list(cases_by_id.values())
    archive["updated_at"] = datetime.now().isoformat(timespec="seconds")
    OUT_PATH.write_text(json.dumps(archive, ensure_ascii=False, indent=2), encoding="utf-8")

    open_now = [c for c in archive["cases"] if c["status"] == "open"]
    print(f"[extract] 扫描 {len(reports)} 份报告(最新 {reports[-1]['file']}):")
    print(f"  新增 bad case: {stats['new']} | 仍失败(open): {stats['still_failing']} | "
          f"回归确认自动置 fixed: {stats['auto_fixed']} | 已修复又失败自动重开: {stats['reopened']}")
    if not open_now:
        print("  ✅ 当前无 open 状态的 bad case"
              + ("——现有报告全部用例通过,快照为空:机制正常,一旦出现失败用例,重跑本脚本即可归档跟踪。"
                 if not stats["new"] and not stats["reopened"] else ""))
    else:
        print(f"  当前 open({len(open_now)}):")
        for c in open_now:
            print(f"    - [{c['type']}] {c['id']}: {c['question']} | 期望 {c['expect']} | 实际 {c['actual']}")
    print(f"[extract] {OUT_PATH} 已更新(updated_at={archive['updated_at']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
