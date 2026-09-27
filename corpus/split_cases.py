#!/usr/bin/env python3
"""T1 语料切分:corpus/raw/affairs/*.docx → corpus/clean/affairs/*.md(gitignore,仅本地)

切分规则:
- 萌哥说案例(两季):按「【萌哥说案例】…NO.x」标记每案一篇;内部小节标题归并为
  情景 / 本质 / 做法 / 启示 四段(兼容"案例情景描述/问题本质/解决思路/实施办法/经验启示"
  等变体,剥离"一、二、"编号);无法识别的段落归入「正文」;可识别小节 <2 的案例整篇
  归入「原文」兜底,保证都可导入。全角 ＮＯ/数字 自动归一化。
- 谈心谈话:按「问题N:」切,每题一篇(问题 + 答题要点)。
- frontmatter 对齐 policy 惯例:title / source / origin_file / category=affairs /
  tier=Tier A 训练材料(化名) / sensitivity=low / split_date。

只生成本地文件(corpus/clean/affairs/ 已 gitignore);质量字段(字数/小节数)打印供导入择优。
"""
from __future__ import annotations

import re
import unicodedata
from datetime import date
from pathlib import Path

import docx

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "corpus" / "raw" / "affairs"
OUT_DIR = ROOT / "corpus" / "clean" / "affairs"

SPLIT_DATE = date.today().isoformat()

# 全角 → 半角归一化(仅用于标记识别,正文保留原样)
_TRANS = str.maketrans("ＮＯ０１２３４５６７８９．", "NO0123456789.")


def norm_marker(line: str) -> str:
    return unicodedata.normalize("NFKC", line).translate(_TRANS)


CASE_RE = re.compile(r"^【萌哥说案例】.*?NO[.\s]*?(\d+)[\s—－–—-]*(.*)$")
Q_RE = re.compile(r"^问题\s*(\d+)\s*[：:]?\s*(.*)$")


def strip_numbering(line: str) -> str:
    return re.sub(r"^[一二三四五六七八九十0-9]+\s*[、.．:：]\s*", "", line).strip()


def classify_header(line: str) -> str | None:
    """小节标题归并:情景/本质/做法/启示;None=正文段落。"""
    h = strip_numbering(line)
    if not h or len(h) > 20:
        return None
    if re.fullmatch(r"(案例)?情景(描述|再现)?|情景导入", h):
        return "情景"
    if "本质" in h or "解决思路" in h or h in ("思路", "分析"):
        return "本质"
    if "做法" in h or "实施" in h or "措施" in h or "办法" in h:
        return "做法"
    if "启示" in h or "启发" in h or "经验" in h:
        return "启示"
    if h in ("前言", "引言", "序", "序言"):
        return "@skip"  # 书籍级前言,跳到下一个小节
    return None


def safe_filename(title: str, limit: int = 28) -> str:
    return re.sub(r'[\\/:*?"<>|\s]+', "", title)[:limit] or "untitled"


def split_mengge(docx_path: Path, season: int) -> list[Path]:
    d = docx.Document(str(docx_path))
    paras = [p.text.strip() for p in d.paragraphs if p.text.strip()]
    # 定位案例标记(容忍全角/变体),裸标题行(无 NO.x)视为封面跳过
    marks = [i for i, t in enumerate(paras) if re.match(r"^【萌哥说案例】", norm_marker(t))
             and re.search(r"NO[.\s]*\d+", norm_marker(t))]
    origin = docx_path.name
    written: list[Path] = []
    for k, start in enumerate(marks):
        end = marks[k + 1] if k + 1 < len(marks) else len(paras)
        title_line = norm_marker(paras[start])
        m = CASE_RE.match(title_line)
        no = int(m.group(1))
        title = re.sub(r"^[\s—－–—-]+", "", m.group(2)).strip() or f"案例{no}"
        # 小节归并
        sections: dict[str, list[str]] = {}
        current = "正文"
        for t in paras[start + 1 : end]:
            cls = classify_header(t)
            if cls == "@skip":
                current = "@skip"
                continue
            if cls:
                current = cls
                sections.setdefault(current, [])
                continue
            if current == "@skip":
                continue
            sections.setdefault(current, []).append(t)
        recognized = sum(1 for s in ("情景", "本质", "做法", "启示") if s in sections)
        body_parts = [f"# {title}", ""]
        if recognized >= 2:
            for key in ("情景", "本质", "做法", "启示", "正文"):
                if key in sections and any(x.strip() for x in sections[key]):
                    body_parts += [f"## {key}", "", "\n\n".join(sections[key]).strip(), ""]
        else:  # 兜底:整篇原文
            body_parts += ["## 原文", "", "\n\n".join(t for t in paras[start + 1 : end]).strip(), ""]
        fm_title = f"萌哥说案例S{season}-NO.{no} {title}"
        front = (
            "---\n"
            f"title: {fm_title}\n"
            "source: 萌哥说案例分析(辅导员职业能力培训材料)\n"
            f"origin_file: {origin}\n"
            "category: affairs\n"
            "tier: Tier A 训练材料(化名)\n"
            "sensitivity: low\n"
            f"split_date: {SPLIT_DATE}\n"
            "---\n\n"
        )
        out = OUT_DIR / f"S{season}-NO{no:02d}-{safe_filename(title)}.md"
        out.write_text(front + "\n".join(body_parts), encoding="utf-8")
        written.append(out)
    return written


def split_qa(docx_path: Path) -> list[Path]:
    d = docx.Document(str(docx_path))
    paras = [p.text.strip() for p in d.paragraphs if p.text.strip()]
    qidx = [i for i, t in enumerate(paras) if Q_RE.match(t)]
    origin = docx_path.name
    written: list[Path] = []
    for k, start in enumerate(qidx):
        end = qidx[k + 1] if k + 1 < len(qidx) else len(paras)
        m = Q_RE.match(paras[start])
        no = int(m.group(1))
        question = m.group(2).strip()
        body = "\n\n".join(t for t in paras[start:end]).strip()
        title = re.sub(r"\s+", "", question)[:36] or f"谈心谈话题{no}"
        front = (
            "---\n"
            f"title: 谈心谈话Q{no:02d} {title}\n"
            "source: 谈心谈话训练题(辅导员职业能力培训材料)\n"
            f"origin_file: {origin}\n"
            "category: affairs\n"
            "tier: Tier A 训练材料(化名)\n"
            "sensitivity: low\n"
            f"split_date: {SPLIT_DATE}\n"
            "---\n\n"
        )
        out = OUT_DIR / f"QA-Q{no:02d}-{safe_filename(title)}.md"
        out.write_text(front + f"# 谈心谈话问题{no}\n\n**问题:**{question}\n\n{body}\n", encoding="utf-8")
        written.append(out)
    return written


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    all_files: list[Path] = []
    for f in sorted(RAW_DIR.glob("*.docx")):
        if "案例" in f.name:
            season = 2 if "第二" in f.name or "二季" in f.name else 1
            n = len(split_mengge(f, season))
            print(f"[split] {f.name} → 案例 {n} 篇")
        elif "谈心" in f.name or "问题" in f.name:
            n = len(split_qa(f))
            print(f"[split] {f.name} → 谈心谈话 {n} 篇")
        else:
            print(f"[split] 跳过未识别文件:{f.name}")
            continue
        all_files += []
    total = sorted(OUT_DIR.glob("*.md"))
    print(f"[split] 合计 {len(total)} 篇 → {OUT_DIR}")
    print("[quality] 择优参考(字数/小节,导入时取 TopN):")
    for p in sorted(total, key=lambda x: -x.stat().st_size)[:8]:
        print(f"  {p.stat().st_size:>7}B  {p.name}")
    return 0


if __name__ == "__main__":
    sys_exit = main()
    raise SystemExit(sys_exit)
