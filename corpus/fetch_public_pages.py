#!/usr/bin/env python3
"""抓取公开官网页面 → 质量门 + 合规拦截 → 生成 import-ready 语料(P4a/M3 的 Qoder prep)

用法:
  python corpus/fetch_public_pages.py --fetch     # 抓取 + 落盘 corpus/clean/<dir>/*.md + 报告
  python corpus/fetch_public_pages.py --import    # 经 /api/kb/upload 导入 KB(需 NovaAgent 在跑)

设计说明:
- **质量门与合规拦截在此先做成可运行原型**,P4a 的 M2 可直接把 GATE/DENY 逻辑移植进
  `novaagent/main.py: kb_import_url`(那里目前只有"能否提取到文本"一条判断)。
- 表格增强:`extract_html` 现用 stdlib HTMLParser 且对 <table> 支持弱(计财处收费公示是表格页),
  这里把 td/th 以 " | " 连接、tr 换行,避免金额与项目名丢失。
- 合规红线(见 docs/P4.md §六):
  1) 含学生姓名的公示/名单页 **禁抓禁入库**(DENY_URLS 显式拦 + 名单特征启发式拦);
  2) 不使用任何真实学工账号登录,只抓公开可匿名访问的页面;
  3) 历史文件(2012/2016 学平险)入库时**在正文顶部写入时效声明**,让检索到该块的模型必须看到它。
"""
from __future__ import annotations

import argparse
import io
import json
import re
import sys
import urllib.error
import urllib.request
from datetime import date
from html.parser import HTMLParser
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError, OSError):
    pass

ROOT = Path(__file__).resolve().parent.parent
OUT_DIRS = {"政策文件": ROOT / "corpus/clean/policy", "办事指引": ROOT / "corpus/clean/guide"}
REPORT = ROOT / "docs/p4/evidence/corpus_fetch_report.txt"
BASE = "http://127.0.0.1:8900"
UA = "Mozilla/5.0 (NovaCampus corpus prep; public pages only)"

# 用户 2026-09-29 批准的 6 篇(docs/p4/corpus-candidates.md A 表)
PAGES = [
    {"url": "https://hospital.swjtu.edu.cn/info/1013/6008.htm",
     "title": "关于2026年度大学生医疗保险缴费的通知", "unit": "西南交通大学校医院",
     "doc_date": "2025-10-14", "category": "政策文件", "role_min": "student", "historical": False},
    {"url": "https://hospital.swjtu.edu.cn/info/1013/6878.htm",
     "title": "大学生医保假期使用的温馨提示", "unit": "西南交通大学校医院",
     "doc_date": "2026-07-20", "category": "政策文件", "role_min": "student", "historical": False},
    {"url": "https://infpub.swjtu.edu.cn/info/1061/4454.htm",
     "title": "西南交通大学2026年收费公示", "unit": "西南交通大学计划财务处",
     "doc_date": "2026-07-09", "category": "政策文件", "role_min": "student", "historical": False},
    {"url": "https://hospital.swjtu.edu.cn/lxwm.htm",
     "title": "西南交通大学校医院联系方式(各科室咨询电话)", "unit": "西南交通大学校医院",
     "doc_date": "", "category": "办事指引", "role_min": "student", "historical": False},
    {"url": "https://bwc.swjtu.edu.cn/info/1018/1031.htm",
     "title": "大学生意外伤害保险理赔须知(学平险)", "unit": "西南交通大学保卫处",
     "doc_date": "2012-12-20", "category": "办事指引", "role_min": "student", "historical": True},
    {"url": "https://bwc.swjtu.edu.cn/info/1018/1043.htm",
     "title": "关于西南交通大学2016年度新生学平险保险的通知", "unit": "西南交通大学保卫处",
     "doc_date": "2016", "category": "办事指引", "role_min": "student", "historical": True},
]

# 显式禁抓:含学生姓名的名单/公示页(P4 红线)
DENY_URLS = [
    "https://hospital.swjtu.edu.cn/info/1013/5558.htm",   # 2025年度城乡居民医保已缴费人员名单公示
    "https://hospital.swjtu.edu.cn/info/1013/3988.htm",   # 2023级新生参保失败名单及处理方法
    "https://cwc.swjtu.edu.cn/",                          # 首页=登录框(曾造成脏数据 id=109)
    "http://127.0.0.1:8900/",                             # 自家前端(曾把演示口令写进库 id=22)
]
LOGIN_FEATURES = ["浏览器版本过旧", "兼容性提示", "请输入验证码", "用户名", "登录密码", "忘记密码"]
MIN_EFFECTIVE_CHARS = 200


class Extractor(HTMLParser):
    """正文提取:跳过 script/style/head;表格按 单元格 | 连接、行换行(补 main.py 的弱项)。"""

    SKIP = {"script", "style", "noscript", "svg", "head"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title = ""
        self._skip = 0
        self._in_title = False
        self._cell = False

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
        if tag == "title":
            self._in_title = True
        if tag in ("td", "th"):
            self._cell = True
            self.parts.append(" | ")
        if tag in ("p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "section", "article", "table"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        if tag == "title":
            self._in_title = False
        if tag in ("td", "th"):
            self._cell = False
        if tag == "tr":
            self.parts.append("\n")

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self._skip and data.strip():
            self.parts.append(data if self._cell else data.strip())


def extract(html: str) -> tuple[str, str]:
    ex = Extractor()
    ex.feed(html)
    lines = [re.sub(r"[ \t]+", " ", ln).strip(" |").strip() for ln in "".join(ex.parts).split("\n")]
    return "\n".join(ln for ln in lines if ln), ex.title.strip()


# 正文起止标记(实测三类站点模板:校医院有"当前位置"+"正文";保卫处为"首页正文";信息公开网为面包屑行)
START_MARKS = [re.compile(r"^当前位置"), re.compile(r"^首页正文$"), re.compile(r"网站首页>")]
END_MARKS = re.compile(r"^(地址：|通讯地址|Copyright|版权所有|蜀ICP|川公网安备|西南交通大学官方微信|西南交通大学官方微博)")
NOISE_SUB = [(re.compile(r"\d{4}年\d{2}月\d{2}日 \d{2}:\d{2}\s*admin点击：\[\]"), ""),
             (re.compile(r"admin点击：\[\]"), ""), (re.compile(r"^正文$"), ""), (re.compile(r"^首页$"), "")]
# 官网公开的保险公司经办人姓名 → 脱敏(保留部门与座机,业务信息不丢)
REDACTIONS = [(re.compile(r"国际部（收件人以官网原文为准）"), "国际部（收件人以官网原文为准）")]


# 导航项白名单(**只按显式词表精确匹配删除**)。
# 曾用"短+无数字+无标点"启发式,结果把正文条目「大学生基本医疗保险费」当导航删掉——
# 数据丢失比噪声残留严重得多,故改为显式词表。
NAV_WORDS = {
    "首页", "网站首页", "医院概况", "党的建设", "医院动态", "通知公告", "健康教育", "医疗保险",
    "健康管理", "红十字会", "联系我们", "学生医保", "教工医保", "报销须知", "机构设置", "部门概况",
    "现任领导", "工作人员", "工作动态", "办事指南", "户政业务", "车辆业务", "政审业务", "消防安全",
    "党建之家", "学习之家", "支部工作", "武装工作", "大学生征兵工作", "军训工作", "政策法规",
    "法律法规", "规章制度", "安全警示", "安全教育", "警示案例", "English", "公开制度", "公开年报",
    "公开事项", "公开目录", "公开指南", "监督投诉", "基本信息", "总体介绍", "返回", " more ",
}


def _is_nav(ln: str) -> bool:
    """仅当整行精确等于已知导航词时才判为导航(宁留噪声,不可丢正文)。"""
    return ln.strip() in NAV_WORDS



def clean_body(text: str) -> tuple[str, dict]:
    """裁掉整站导航/页脚,只留正文;顺做噪声替换与人名脱敏。返回 (正文, 统计)。"""
    lines = text.split("\n")
    start = 0
    for i, ln in enumerate(lines):
        if any(m.search(ln) for m in START_MARKS):
            start = i + 1
            break
    end = len(lines)
    for i in range(start, len(lines)):
        if END_MARKS.search(lines[i]):
            end = i
            break
    kept = []
    nav_drop = 0
    for ln in lines[start:end]:
        for pat, rep in NOISE_SUB:
            ln = rep if pat.search(ln) else ln
        for pat, rep in REDACTIONS:
            ln = pat.sub(rep, ln)
        ln = ln.replace("\ufeff", "").strip()
        if not ln:
            continue
        if _is_nav(ln):
            nav_drop += 1
            continue
        kept.append(ln)
    return "\n".join(kept), {"dropped_nav": nav_drop, "cut_head": start, "cut_tail": len(lines) - end}



def gate(url: str, title: str, text: str) -> tuple[bool, str]:
    """质量门 + 合规拦截。返回 (是否放行, 原因)。"""
    if url in DENY_URLS:
        return False, "DENY_URLS 显式禁止(名单/登录页/自家前端)"
    if any(u in url for u in DENY_URLS):
        return False, "命中禁抓 URL 前缀"
    if ("名单" in title or "名单" in text[:400]) and ("姓名" in text or "学号" in text):
        return False, "名单特征(含姓名/学号)→ 需人工审核,自动入库已拦"
    if title in ("登录", "未命名网页", ""):
        return False, "标题为登录/未命名 → 疑似非内容页"
    if len(text) < MIN_EFFECTIVE_CHARS:
        return False, "正文有效长度 %d < %d → 低信息量" % (len(text), MIN_EFFECTIVE_CHARS)
    hit = [f for f in LOGIN_FEATURES if f in text[:600]]
    if len(hit) >= 2:
        return False, "登录页特征 %s" % hit
    return True, "通过"


def frontmatter(p: dict, chars: int) -> str:
    return (
        "---\n"
        f"title: {p['title']}\n"
        f"source_url: {p['url']}\n"
        f"source_unit: {p['unit']}\n"
        f"doc_date: {p['doc_date'] or '未标注'}\n"
        f"category: {p['category']}\n"
        f"role_min: {p['role_min']}\n"
        "tier: Tier A 公开官网页面\n"
        "sensitivity: low\n"
        f"historical: {'true' if p['historical'] else 'false'}\n"
        f"fetched_at: {date.today().isoformat()}\n"
        f"effective_chars: {chars}\n"
        "---\n\n"
    )


STALE_NOTICE = (
    "> **【时效声明】** 本文件发布于 {doc_date}，为**历史文件**，仅反映当时的办理方式与联系方式。"
    "回答时必须同时说明「该文件为 {doc_date} 发布的历史材料，请以保卫处/校医院最新通知为准」，"
    "不得把其中的电话、金额、流程当作现行规定直接给出。\n\n"
)


def do_fetch() -> int:
    rep = io.open(str(REPORT), "w", encoding="utf-8")
    rep.write("# 公开官网语料抓取报告(%s)\n\n" % date.today().isoformat())
    ok_n = 0
    for p in PAGES:
        rep.write("== %s\n   %s\n" % (p["title"], p["url"]))
        try:
            req = urllib.request.Request(p["url"], headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=40) as r:
                raw = r.read()
                ctype = r.headers.get("content-type", "")
            html = raw.decode("utf-8", errors="replace")
        except Exception as e:
            rep.write("   [FAIL] 抓取失败: %s %s\n\n" % (type(e).__name__, str(e)[:160]))
            print("[FAIL] %s -> %s" % (p["title"][:20], type(e).__name__))
            continue
        text, ptitle = extract(html)
        passed, reason = gate(p["url"], ptitle or p["title"], text)
        rep.write("   http_ctype=%s bytes=%d 页面title=%r 原始正文=%d 字\n" % (ctype, len(raw), ptitle[:40], len(text)))
        rep.write("   质量门(裁剪前): %s(%s)\n" % ("PASS" if passed else "BLOCKED", reason))
        if not passed:
            rep.write("\n")
            print("[BLOCKED] %s -> %s" % (p["title"][:24], reason))
            continue
        text, stat = clean_body(text)
        passed2, reason2 = gate(p["url"], p["title"], text)
        rep.write("   正文裁剪: 去导航 %d 行、切头 %d 行、切尾 %d 行 → 有效正文 %d 字\n"
                  % (stat["dropped_nav"], stat["cut_head"], stat["cut_tail"], len(text)))
        rep.write("   质量门(裁剪后): %s(%s)\n" % ("PASS" if passed2 else "BLOCKED", reason2))
        if not passed2:
            rep.write("\n")
            print("[BLOCKED] %s -> 裁剪后 %s" % (p["title"][:24], reason2))
            continue
        rep.write("   脱敏: %s\n" % ("已应用 REDACTIONS(官网经办人姓名→部门)" if REDACTIONS else "无"))
        # 敏感信息自检:手机号(非公开座机)/身份证/学号模式
        ids = re.findall(r"\b\d{17}[\dXx]\b", text)
        phones = re.findall(r"\b1[3-9]\d{9}\b", text)
        rep.write("   敏感扫描: 身份证样式=%d 手机号样式=%d\n" % (len(ids), len(phones)))
        if ids or phones:
            rep.write("   [BLOCKED] 命中个人敏感信息样式,不入库\n\n")
            print("[BLOCKED] %s -> 敏感信息" % p["title"][:24])
            continue
        body = (STALE_NOTICE.format(doc_date=p["doc_date"]) if p["historical"] else "") + f"# {p['title']}\n\n{text}\n"
        outdir = OUT_DIRS[p["category"]]
        outdir.mkdir(parents=True, exist_ok=True)
        safe = re.sub(r"[\\/:*?\"<>|]", "", p["title"])[:60]
        fp = outdir / (safe + ".md")
        io.open(str(fp), "w", encoding="utf-8", newline="\n").write(frontmatter(p, len(text)) + body)
        rep.write("   [OK] 落盘 %s(%d 字)\n\n" % (fp.relative_to(ROOT), len(body)))
        print("[OK] %s -> %s (%d 字)" % (p["title"][:24], fp.name[:40], len(text)))
        ok_n += 1
    rep.write("合计放行 %d / %d\n" % (ok_n, len(PAGES)))
    rep.close()
    print("[SUM] 放行 %d/%d,报告 -> %s" % (ok_n, len(PAGES), REPORT.relative_to(ROOT)))
    return 0 if ok_n >= 4 else 2


def do_import() -> int:
    import httpx

    tok = httpx.post(BASE + "/api/login", json={"username": "counselor", "password": "counselor123"},
                     timeout=30).json()["token"]
    H = {"Authorization": "Bearer " + tok}
    before = len(httpx.get(BASE + "/api/kb/documents", headers=H, timeout=30).json()["documents"])
    log = io.open(str(ROOT / "docs/p4/evidence/corpus_import_log.txt"), "w", encoding="utf-8")
    log.write("# 语料入库日志(%s)  入库前 documents=%d\n\n" % (date.today().isoformat(), before))
    n_ok = 0
    for p in PAGES:
        fp = OUT_DIRS[p["category"]] / (re.sub(r"[\\/:*?\"<>|]", "", p["title"])[:60] + ".md")
        if not fp.exists():
            log.write("[SKIP] 未落盘: %s\n" % fp.name)
            continue
        # 正文去掉 frontmatter 再上传(frontmatter 是 corpus 侧元数据,不进检索正文)
        raw = io.open(str(fp), encoding="utf-8").read()
        body = raw.split("---\n\n", 1)[1] if "---\n\n" in raw else raw
        files = {"file": (fp.name, body.encode("utf-8"), "text/markdown")}
        r = httpx.post(BASE + "/api/kb/upload", headers=H, files=files,
                       data={"role_min": p["role_min"], "category": p["category"]}, timeout=180)
        if r.status_code != 200:
            log.write("[FAIL] %s -> HTTP %d %s\n" % (fp.name, r.status_code, r.text[:200]))
            print("[FAIL] %s HTTP %d" % (fp.name[:30], r.status_code))
            continue
        d = r.json()
        log.write("[OK] doc_id=%s chunks=%s category=%s role=%s title=%s\n     summary=%s\n"
                  % (d["doc_id"], d["chunks"], d["category"], d["role_min"], p["title"], (d.get("summary") or "")[:200]))
        print("[OK] doc_id=%s chunks=%s %s" % (d["doc_id"], d["chunks"], p["title"][:28]))
        n_ok += 1
    after = len(httpx.get(BASE + "/api/kb/documents", headers=H, timeout=30).json()["documents"])
    log.write("\n入库后 documents=%d(+%d),成功 %d/%d\n" % (after, after - before, n_ok, len(PAGES)))
    log.close()
    print("[SUM] 入库 %d 篇,documents %d -> %d" % (n_ok, before, after))
    return 0 if n_ok >= 4 else 2


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--fetch", action="store_true")
    ap.add_argument("--import", dest="imp", action="store_true")
    a = ap.parse_args()
    if a.imp:
        sys.exit(do_import())
    sys.exit(do_fetch())
