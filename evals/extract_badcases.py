#!/usr/bin/env python3
"""bad case 提取器(T2)— 从评测报告提取失败用例,维护 evals/badcases.json

用法(每次 run_evals.py 之后执行,可重复执行):
  python evals/extract_badcases.py

行为:
  1. 按时间戳从旧到新扫描 reports/eval_report_*.json;
  2. 抽取 pass=false 用例按用例 id 合并进 badcases.json(累积档案,只增不删);
  3. **幂等**:重复执行,badcases.json 除 updated_at 外零变化——
       - history 按 report 文件名去重,同一报告不重复记录;
       - 状态流转只以「最新一份报告」为唯一依据,重扫历史报告不触发任何状态变化;
       - reopened 仅在「上次为 fixed 且本次最新报告确实失败」时触发;
  4. 状态机:
       open     待迭代(默认;最新报告仍失败)
       fixing   修复中(人工置;最新报告通过时只回填 fixed_in,人工确认后置 fixed)
       fixed    已修复(最新报告通过时由 open 自动翻转并记录 fixed_in;
                已 fixed 的用例在最新报告中再次失败 → 自动重开为 open)
       wontfix  不修复(人工置,提取器不改)
  5. 全部通过时 open 快照为空,并打印说明。note 为人工字段,永不覆盖。
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path

try:  # 不依赖控制台默认编码(Windows GBK 控制台下避免 UnicodeEncodeError)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError, OSError):
    pass

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


def append_history(entry: dict, hist: dict) -> None:
    """幂等追加:同一 report 文件名只记录一次。"""
    if all(h.get("report") != hist["report"] for h in entry.get("history", [])):
        entry.setdefault("history", []).append(hist)


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
    known_ids = set(cases_by_id)  # 用于统计"本次新增"

    # ---- 阶段一(幂等建档):重扫全部报告,只为失败用例建档/补 history ----
    for rep in reports:
        for r in rep["data"].get("results", []):
            if r.get("pass") or not r.get("id"):
                continue  # 只关心失败用例
            cid = r["id"]
            hist = {"report": rep["file"], "detail": r.get("detail", ""), "at": rep["ts"]}
            entry = cases_by_id.get(cid)
            if entry is None:
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
                append_history(entry, hist)
                # 迭代顺序为旧→新,赋值结束即收敛到"最近一次失败"的详情,重跑结果一致
                entry["actual"] = r.get("detail", "")
                entry["last_seen"] = rep["ts"]

    # ---- 阶段二(状态流转):只以最新报告为唯一依据 ----
    latest_report = reports[-1]
    latest = {r["id"]: r for r in latest_report["data"].get("results", []) if r.get("id")}
    prev_status = {cid: e["status"] for cid, e in cases_by_id.items()}  # 阶段一不改状态

    stats = {"new": len(cases_by_id) - len(known_ids), "still_failing": 0, "auto_fixed": 0, "reopened": 0}
    for cid, entry in cases_by_id.items():
        res = latest.get(cid)
        if res is None:
            continue  # 不在最新报告中的历史条目保持原状
        if res.get("pass"):
            if prev_status[cid] == "open":
                entry["status"] = "fixed"
                entry["fixed_in"] = latest_report["file"]
                append_history(entry, {"report": latest_report["file"], "detail": "回归通过", "at": latest_report["ts"]})
                stats["auto_fixed"] += 1
            elif prev_status[cid] == "fixing":
                entry["fixed_in"] = latest_report["file"]  # 只提示,人工确认后置 fixed
        else:
            if prev_status[cid] == "fixed":
                entry["status"] = "open"  # 已修复又失败(以最新报告为准)→ 重开
                stats["reopened"] += 1
            elif prev_status[cid] in ("open", "fixing"):
                stats["still_failing"] += 1

    archive["cases"] = list(cases_by_id.values())
    archive["updated_at"] = datetime.now().isoformat(timespec="seconds")
    OUT_PATH.write_text(json.dumps(archive, ensure_ascii=False, indent=2), encoding="utf-8")

    open_now = [c for c in archive["cases"] if c["status"] == "open"]
    print(f"[extract] 扫描 {len(reports)} 份报告(最新 {latest_report['file']}):")
    print(f"  新增 bad case: {stats['new']} | 仍失败(open): {stats['still_failing']} | "
          f"回归确认自动置 fixed: {stats['auto_fixed']} | 已修复又失败自动重开: {stats['reopened']}")
    if not open_now:
        print("  [OK] 当前无 open 状态的 bad case"
              + ("——现有报告全部用例通过,快照为空:机制正常,一旦出现失败用例,重跑本脚本即可归档跟踪。"
                 if stats == {"new": 0, "still_failing": 0, "auto_fixed": 0, "reopened": 0} else ""))
    else:
        print(f"  当前 open({len(open_now)}):")
        for c in open_now:
            print(f"    - [{c['type']}] {c['id']}: {c['question']} | 期望 {c['expect']} | 实际 {c['actual']}")
    print(f"[extract] {OUT_PATH} 已更新(updated_at={archive['updated_at']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
