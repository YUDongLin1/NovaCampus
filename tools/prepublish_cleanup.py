#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""开源前脱敏与精简清理脚本（NovaCampus）

用法：
    python tools/prepublish_cleanup.py            # 预演（默认，不改任何文件）
    python tools/prepublish_cleanup.py --apply    # 真正执行

执行前请务必：
    1. 先跑一次预演，逐条看完将要修改的内容；
    2. 确认工作区干净（git status 为空），或先提交；
    3. 脚本会尝试打一个备份 tag：prepublish-backup-<时间戳>

设计原则：
    · 默认只读，必须显式 --apply 才写盘；
    · 只处理文本文件，绝不碰 corpus/ 原始语料、二进制、依赖目录；
    · 每一处替换都可打印、可回滚（靠 git）；
    · 无法自动判断的项目**不猜**，只列出来交给人工。

详见 PRIVACY-AUDIT.local.md（该文件不会被提交）。
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# 只在这些后缀里做文本替换
TEXT_SUFFIXES = {".md", ".py", ".json", ".txt", ".yml", ".yaml", ".js", ".html",
                 ".css", ".toml", ".ini", ".cfg", ".sh", ".ps1", ".sql", ".csv"}

# 永不进入处理范围的路径片段
SKIP_PARTS = {".git", ".venv", "node_modules", "__pycache__", "weknora",
              "raw_docs", "corpus/raw", "corpus/clean/affairs", ".pytest_cache"}


# ---------------------------------------------------------------------------
# 规则一：全局文本替换（正则 → 替换）
# 每条规则都要写清"防的是什么"，便于日后审阅
# ---------------------------------------------------------------------------
REDACTIONS: list[tuple[str, str, str, str]] = [
    # (编号, 匹配正则, 替换为, 说明)
    ("R1", r"C:\\\\Users\\\\<user>", r"C:\\\\Users\\\\<user>",
     "JSON 转义形式的 Windows 用户目录"),
    ("R2", r"C:\\Users\\<user>", r"C:\\Users\\<user>",
     "Windows 用户目录，泄露本机账户名"),
    ("R3", r"C:/Users/<user>", r"C:/Users/<user>",
     "正斜杠形式的 Windows 用户目录"),
    ("R4", r"/c/Users/<user>", r"/c/Users/<user>",
     "Git Bash 形式的用户目录"),
    ("R5", r"E:\\<internal-affairs-dir>\\", r"<内部学工数据目录>\\",
     "真实学工数据目录路径（其内容清单亦属隐私）"),
    ("R6", r"E:/<internal-affairs-dir>/", r"<内部学工数据目录>/",
     "同上，正斜杠形式"),
    ("R7", r"用户=某高校辅导员，个人项目",
     "某高校辅导员，个人项目",
     "真实单位+岗位+求职意图，等同实名去匿名化"),
    ("R8", r"用户\(某高校辅导员，个人项目\)",
     "某高校辅导员（个人项目）",
     "同上，全角标点版本"),
    ("R9", r"国际部（收件人以官网原文为准）", "国际部（收件人以官网原文为准）",
     "把官网公开经办人姓名写进了受控代码"),
    # 真实学生原话（仅匿城市）→ 同长度同语义的合成改写句
    ("R10",
     r"导员你好，我想咨询一下医保的事情。我目前的参保地还显示为本科学校所在地某市，"
     r"我后续该如何把这个改为现在这个地方呢。本学期的医保我是交了的",
     "老师您好，想咨询一下医保的事。我的参保地目前还挂在原来学校所在的某市，"
     "想问下要怎么办才能转到现在这边？这学期的医保我已经交了",
     "真实学生原话逐字引用，改为合成改写句（评测效果不变）"),
]

# ---------------------------------------------------------------------------
# 规则二：第三方版权材料的案例标题 → 编号
# corpus/*/affairs/ 已被 gitignore，但标题扩散进了受控的证据与报告
# ---------------------------------------------------------------------------
TITLE_REDACTIONS: list[tuple[str, str]] = [
    ("QA-Q02-学生小静来自独生子女家庭，经常与宿舍同学产生口角，这天她", "AFF-Q02"),
    ("S1-NO47-学生因恋爱问题遭遇死亡威胁,辅导员应该如何应对", "AFF-S1-NO47"),
    ("S1-NO47-学生因恋爱问题遭遇死亡威胁，辅导员应该如何应对", "AFF-S1-NO47"),
]

# ---------------------------------------------------------------------------
# 规则三：需人工判断的项目（脚本只报告，不自动改）
# ---------------------------------------------------------------------------
MANUAL_ITEMS = [
    ("docs/p4e/probe_web_compliance.py:52",
     "埋点用的合成个人信息（埋点-姓名1同学 等）。已是明显假数据，通常无需处理；"
     "如要极简，可改成 test-name-1 / test-phone-1。"),
    ("docs/M0-setup.md:6",
     "泄露了密钥的格式与长度（sk-sp- 开头 116 位）。建议删掉括号里的格式描述。"),
    ("docs/p4/corpus-candidates.md:26,27",
     "明确标注了哪两个公开页面含学生姓名。建议保留 DENY_URLS 机制，"
     "删掉对页面内容的文字描述。"),
    ("docs/p4b0/evidence/before/05_settings_modal.png",
     "设置弹窗截图里 API Key 输入框显示未打码的 sk-... 占位符。"
     "建议删除该截图或重拍。"),
    ("docs/p4b/evidence/before/01_login_page.png 等 3 张登录页截图",
     "登录页渲染了演示口令。演示口令本身可公开，但截图会同时成为『默认账号+口令』的说明书，建议按需保留。"),
    ("docs/p5/evidence/shots/1280x800_counselor_records.png 等 2 张",
     "工作记录页截图含日期化的违纪、助学金认定、心理转介记录。"
     "**若这些记录是真实工作经历（经占位符脱敏）→ 必须删除；若纯属合成造数 → 可保留。** "
     "这一步脚本无法替你判断。"),
    ("docs/CASE_STUDY.md 第 8 节",
     "『简历与面试表述候选』整节属个人求职内容，建议移出公开仓库。"),
    ("docs/PLAN.md 第五节",
     "『叙事主线（面试用）』属个人求职内容，建议移出公开仓库。"),
]

# ---------------------------------------------------------------------------
# 规则四：文档精简（移入 docs/internal/，保留工程结论）
# ---------------------------------------------------------------------------
INTERNAL_MOVES = [
    "HANDOFF.md",
    "docs/TASKS.md",
    "docs/NEXT_SESSION_PROMPT.md",
    "docs/EVAL_BASELINE.md",
    "docs/COLLAB.md",
]
INTERNAL_GLOBS = [
    "docs/p*/zcode-order*.md",
    "docs/p*/workbuddy-order*.md",
    "docs/p*/workbuddy-reject*.md",
    "docs/p*/review_*.md",
    "docs/p*/patch_*.py",
    "docs/p*/probe_*.py",
]

# ---------------------------------------------------------------------------
# 规则五：直接删除的文件
# ---------------------------------------------------------------------------
DELETE_FILES = [
    ("reports/_port_owner.txt",
     "本机进程属主转储（真实 PID + 解释器绝对路径），不是验收证据"),
]

# 需要剥掉 content 字段的 JSON（版权材料正文）
FAITH_JSON = "docs/p4d/evidence/after/faithfulness_inputs.json"
FAITH_STRIP_KEYWORDS = ["谈心谈话", "萌哥", "小静", "小C"]


def is_skipped(p: Path) -> bool:
    rel = p.relative_to(REPO).as_posix()
    # 本脚本自身含全部匹配模式，必须排除，否则会「自己命中自己」
    if p.resolve() == Path(__file__).resolve():
        return True
    return any(part in rel.split("/") or part in rel for part in SKIP_PARTS)


def iter_text_files():
    for p in REPO.rglob("*"):
        if not p.is_file():
            continue
        if p.suffix.lower() not in TEXT_SUFFIXES:
            continue
        if is_skipped(p):
            continue
        yield p


def git(*args: str) -> tuple[int, str]:
    r = subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def plan_text_redactions(apply: bool) -> int:
    print("\n" + "=" * 78)
    print("【规则一/二】全局文本脱敏")
    print("=" * 78)
    hits = 0
    for p in iter_text_files():
        try:
            original = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        text = original
        rel = p.relative_to(REPO).as_posix()
        for rid, pat, repl, why in REDACTIONS:
            new_text, n = re.subn(pat, repl, text)
            if n:
                hits += n
                print(f"  [{rid}] {rel}  ×{n}  —— {why}")
                text = new_text
        for old, new in TITLE_REDACTIONS:
            if old in text:
                n = text.count(old)
                hits += n
                print(f"  [T]  {rel}  ×{n}  第三方版权案例标题 → {new}")
                text = text.replace(old, new)
        if text != original and apply:
            p.write_text(text, encoding="utf-8")
    if hits == 0:
        print("  未发现需要替换的内容（可能已清理过）")
    else:
        print(f"  命中合计：{hits} 处" + ("（已写入）" if apply else "（预演，未写入）"))
    return hits


def plan_faith_json(apply: bool) -> int:
    print("\n" + "=" * 78)
    print("【规则三】剥离证据 JSON 中的第三方版权正文")
    print("=" * 78)
    p = REPO / FAITH_JSON
    if not p.exists():
        print(f"  跳过：{FAITH_JSON} 不存在")
        return 0
    data = json.loads(p.read_text(encoding="utf-8"))
    stripped = 0

    def walk(node):
        nonlocal stripped
        if isinstance(node, dict):
            blob = json.dumps(node, ensure_ascii=False)
            if "content" in node and isinstance(node["content"], str) and len(node["content"]) > 200:
                if any(k in blob for k in FAITH_STRIP_KEYWORDS):
                    c = node["content"]
                    node["content"] = (f"[第三方版权材料正文已移除] "
                                       f"字符数={len(c)} sha256前16位="
                                       f"{__import__('hashlib').sha256(c.encode('utf-8')).hexdigest()[:16]}")
                    stripped += 1
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(data)
    print(f"  将剥离 {stripped} 个 content 字段（替换为『字符数 + 哈希前 16 位』，保留可核验性）")
    if stripped and apply:
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print("  已写入")
    return stripped


def plan_deletes(apply: bool) -> int:
    print("\n" + "=" * 78)
    print("【规则五】删除不应公开的文件")
    print("=" * 78)
    n = 0
    for rel, why in DELETE_FILES:
        p = REPO / rel
        if not p.exists():
            print(f"  跳过（不存在）：{rel}")
            continue
        n += 1
        print(f"  删除 {rel} —— {why}")
        if apply:
            code, _ = git("rm", "-f", "--quiet", rel)
            if code != 0:
                p.unlink(missing_ok=True)
                print("    （非 git 跟踪文件，已直接删除）")
    if not n:
        print("  无可删除项")
    return n


def plan_moves(apply: bool) -> int:
    print("\n" + "=" * 78)
    print("【规则四】文档精简：内部协作台账 → docs/internal/")
    print("=" * 78)
    targets: list[Path] = []
    for rel in INTERNAL_MOVES:
        p = REPO / rel
        if p.exists():
            targets.append(p)
    for g in INTERNAL_GLOBS:
        targets.extend(sorted(REPO.glob(g)))
    seen, uniq = set(), []
    for p in targets:
        if p.is_file() and p not in seen:
            seen.add(p)
            uniq.append(p)
    if not uniq:
        print("  无可移动项（可能已移动过）")
        return 0
    print(f"  共 {len(uniq)} 个文件将移动到 docs/internal/（保留工程结论，移出协作过程）")
    for p in uniq[:10]:
        print(f"    {p.relative_to(REPO).as_posix()}")
    if len(uniq) > 10:
        print(f"    ...（其余 {len(uniq) - 10} 个）")
    if apply:
        dest = REPO / "docs" / "internal"
        dest.mkdir(parents=True, exist_ok=True)
        for p in uniq:
            rel = p.relative_to(REPO)
            new = dest / rel.name if rel.parent.name != "internal" else None
            # 保持子目录结构，避免同名文件互相覆盖
            new = dest / rel.as_posix().replace("docs/", "", 1)
            new.parent.mkdir(parents=True, exist_ok=True)
            code, out = git("mv", rel.as_posix(), new.relative_to(REPO).as_posix())
            if code != 0:
                p.rename(new)
        print(f"  已移动 {len(uniq)} 个文件到 docs/internal/")
    return len(uniq)


def report_manual() -> None:
    print("\n" + "=" * 78)
    print("【需人工判断】脚本不自动处理，请逐条确认")
    print("=" * 78)
    for loc, why in MANUAL_ITEMS:
        print(f"  · {loc}\n      {why}")


def backup_tag(apply: bool) -> None:
    if not apply:
        return
    tag = f"prepublish-backup-{datetime.now():%Y%m%d-%H%M%S}"
    code, out = git("tag", tag)
    print(f"\n备份 tag：{tag}" + ("（已创建）" if code == 0 else f"（创建失败：{out.strip()}）"))


def verify(apply: bool) -> None:
    print("\n" + "=" * 78)
    print("【复核】")
    print("=" * 78)
    code, out = git("ls-files", "-i", "-c", "--exclude-standard")
    bad = [l for l in out.splitlines() if l.strip()]
    print(f"  被忽略的已跟踪文件（应为 0）：{len(bad)}")
    for l in bad[:10]:
        print(f"    ⚠ {l}")

    # 脱敏目标复查
    remaining = 0
    for p in iter_text_files():
        try:
            text = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for rid, pat, _repl, _why in REDACTIONS:
            if re.search(pat, text):
                remaining += 1
                print(f"    残留 [{rid}] {p.relative_to(REPO).as_posix()}")
    print(f"  脱敏目标残留（执行模式下应为 0）：{remaining}"
          + ("　← 预演模式未写盘，此数字＝待处理处数，属正常" if not apply else ""))

    code, out = git("status", "--short")
    changed = [l for l in out.splitlines() if l.strip()]
    print(f"  git status 变更条目：{len(changed)}" + ("（未执行，属预演）" if not apply else ""))
    for l in changed[:15]:
        print(f"    {l}")
    if len(changed) > 15:
        print(f"    ...（其余 {len(changed) - 15} 条）")

    print("\n  后续人工步骤：")
    print("    1) 复查 docs/CASE_STUDY.md 第 8 节、docs/PLAN.md 第五节是否已移出")
    print("    2) 复查登录页与工作记录类截图（见上方清单）")
    print("    3) 确认 novaagent/.env 与 .env.test 未被提交")
    print("    4) git add -A && git commit -m 'chore: 开源前脱敏与文档精简'")
    print("    5) 推送前最后一道闸：git status --ignored，除 !! 行外必须为空")


def main() -> int:
    ap = argparse.ArgumentParser(description="开源前脱敏与精简清理（默认预演）")
    ap.add_argument("--apply", action="store_true", help="真正写盘；不加则只预演")
    args = ap.parse_args()
    apply = args.apply

    print("=" * 78)
    print(f"NovaCampus 开源前清理 —— {'【执行模式】' if apply else '【预演模式，不会修改任何文件】'}")
    print(f"仓库：{REPO}")
    print("=" * 78)

    if apply:
        code, out = git("status", "--porcelain")
        if out.strip():
            print("\n⚠ 工作区不干净，建议先提交或 stash 再执行。当前变更：")
            for l in out.splitlines()[:20]:
                print("   ", l)
            print("继续执行将把这些改动一起卷入。5 秒后继续（Ctrl+C 中止）……")
            import time
            time.sleep(5)

    total = 0
    total += plan_text_redactions(apply)
    total += plan_faith_json(apply)
    total += plan_deletes(apply)
    total += plan_moves(apply)
    report_manual()
    backup_tag(apply)
    verify(apply)

    print("\n" + "=" * 78)
    if not apply:
        print(f"预演结束：共 {total} 处将被处理。确认无误后加 --apply 执行。")
    else:
        print(f"执行结束：共处理 {total} 处。请按上方『后续人工步骤』收尾。")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
