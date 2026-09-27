#!/usr/bin/env python3
"""语料脱敏脚本 — 入库知识库前的强制步骤(PLAN.md P1)

用法:
  python anonymize.py <文件或目录> -o <输出目录> [--names names.txt] [--check]

规则:
  1. 内置正则:手机号 / 邮箱 / 身份证号 / QQ号;学号默认开启(以 20 开头的 10~12 位数字)
  2. 姓名脱敏:names.txt 一行一个真实姓名,按首次出现顺序替换为【学生1】【学生2】...
     同一姓名在整批语料中保持同一占位符,保证跨文档指代一致
  3. --check 只统计不写盘,用于发布前自查(README 数据合规范)

编码:优先 UTF-8,失败回退 GBK。输出为 UTF-8。
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

PATTERNS: list[tuple[str, re.Pattern[str], str | None]] = [
    # (标签, 正则, 替换模板;None 表示整体替换为【标签】,模板用 \1 保留前缀)
    ("身份证号", re.compile(r"(?<!\d)[1-9]\d{5}(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:[0-2]\d|3[01])\d{3}[\dXx](?!\d)"), None),
    ("手机号", re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"), None),
    ("学号", re.compile(r"(?<!\d)20\d{8,10}(?!\d)"), None),
    ("邮箱", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), None),
    # QQ 号要求显式前缀,避免误伤长数字(学号/单号等)
    ("QQ号", re.compile(r"((?:[Qq][Qq]|扣扣)\s*[:：]?\s*)([1-9]\d{4,10})(?!\d)"), r"\1【QQ号】"),
]

NAME_TAG = "姓名{}"


def read_text(path: Path) -> str:
    for enc in ("utf-8", "utf-8-sig", "gbk"):
        try:
            return path.read_text(encoding=enc)
        except UnicodeDecodeError:
            continue
    raise UnicodeDecodeError("all", b"", 0, 1, f"无法解码: {path}")


def build_name_replacer(names: list[str]) -> tuple[re.Pattern[str], dict[str, str]]:
    mapping: dict[str, str] = {}

    def repl(m: re.Match) -> str:
        name = m.group(0)
        if name not in mapping:
            mapping[name] = NAME_TAG.format(len(mapping) + 1)
        return mapping[name]

    if not names:
        return re.compile(r"(?!x)x"), mapping  # 永不匹配
    pattern = re.compile("|".join(re.escape(n) for n in sorted(names, key=len, reverse=True)))
    return pattern, mapping


def sanitize(text: str, name_pattern: re.Pattern[str]) -> tuple[str, dict[str, int]]:
    counts: dict[str, int] = {}
    for label, pat, repl in PATTERNS:
        template = repl if repl is not None else f"【{label}】"
        text, n = pat.subn(template, text)
        if n:
            counts[label] = counts.get(label, 0) + n
    seen: dict[str, str] = {}
    seen: dict[str, str] = {}

    def _repl(m: re.Match) -> str:
        name = m.group(0)
        if name not in seen:
            seen[name] = NAME_TAG.format(len(seen) + 1)
        return seen[name]

    text, n = name_pattern.subn(_repl, text)
    if n:
        counts["姓名"] = counts.get("姓名", 0) + n
    return text, counts


def main() -> int:
    ap = argparse.ArgumentParser(description="语料脱敏(入库前必跑)")
    ap.add_argument("input", type=Path, help="文件或目录(.txt/.md)")
    ap.add_argument("-o", "--output", type=Path, default=Path("sanitized"), help="输出目录")
    ap.add_argument("--names", type=Path, default=Path(__file__).parent / "names.txt", help="姓名清单,一行一个")
    ap.add_argument("--check", action="store_true", help="只检测不写盘(发布前自查)")
    args = ap.parse_args()

    names = []
    if args.names.exists():
        names = [ln.strip() for ln in args.names.read_text(encoding="utf-8").splitlines() if ln.strip()]
    name_pattern, _ = build_name_replacer(names)

    files = [args.input] if args.input.is_file() else sorted(
        p for p in args.input.rglob("*") if p.suffix.lower() in {".txt", ".md"} and p.is_file()
    )
    if not files:
        print(f"未找到 .txt/.md 文件: {args.input}")
        return 1

    total = 0
    for f in files:
        text = read_text(f)
        cleaned, counts = sanitize(text, name_pattern)
        n = sum(counts.values())
        total += n
        rel = f.name
        flag = "、".join(f"{k}×{v}" for k, v in counts.items()) or "未发现敏感信息"
        if args.check:
            print(f"[check] {rel}: {flag}")
        else:
            out = args.output / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(cleaned, encoding="utf-8")
            print(f"[脱敏] {rel} -> {out} ({flag})")

    print(f"\n共处理 {len(files)} 个文件,命中 {total} 处。{'(check 模式未写盘)' if args.check else ''}")
    if args.check and total:
        print("存在未脱敏内容,禁止直接入库/发布。请在 names.txt 补充姓名后重新执行。")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
