#!/usr/bin/env python3
"""P4b-0 独立不变量校验(不依赖 split_frontend.py 的自断言)。从仓库根运行:
    python docs/p4b0/verify_invariants.py
基准 = docs/p4b0/evidence/before/index.original.html(拆分前的 index.html 快照)

A 源码等价:CSS 逐行等价;JS 行多重集等价(允许每文件头 1 行注释);顶层可执行语句顺序等价
B 骨架等价:去掉 style/script/link 后 HTML 标记逐行一致
C 内联事件处理器:集合一致(骨架 + 迁移进 js 的模板字符串)+ 每个被调标识符可解析
D API 调用点集合一致(骨架 + 全部 js)
"""
import io
import json
import re
import sys
from collections import Counter

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = r"E:\AILearn\NovaCampus"          # 从仓库根运行
ORIG = ROOT + r"\docs\p4b0\evidence\before\index.original.html"
NEW = ROOT + r"\novaagent\web\index.html"
LOAD_ORDER = ["api", "ui", "chat", "kb", "weekly"]
fails = []


def read(p):
    return io.open(p, encoding="utf-8").read()


def norm(lines):
    return [l.strip() for l in lines if l.strip()]


orig = read(ORIG)
new = read(NEW)
js_txt = {f: read(ROOT + "\\novaagent\\web\\js\\%s.js" % f) for f in LOAD_ORDER}
all_js_only = "\n".join(js_txt.values())
all_js_new = all_js_only + "\n" + new

o_style = re.search(r"<style>\n(.*?)\n</style>", orig, re.S).group(1)
o_script = re.search(r"<script>\n(.*?)\n</script>", orig, re.S).group(1)
n_scripts = re.findall(r"<script>\n(.*?)\n</script>", new, re.S)   # 内联 boot

# ---------- A1 CSS 逐行等价(去掉文件头注释) ----------
css_body = re.sub(r"^/\*.*?\*/\n", "", read(ROOT + r"\novaagent\web\css\theme.css"), count=1, flags=re.S)
a_css = norm(css_body.split("\n")) == norm(o_style.split("\n"))

# ---------- A2 JS 行多重集等价 ----------
def strip_banner(t):
    t = re.sub(r"^/\*.*?\*/\n", "", t, count=1, flags=re.S)
    return re.sub(r"^// .*\n", "", t, count=1)


n_js = "\n".join(strip_banner(js_txt[f]) for f in LOAD_ORDER) + "\n" + "\n".join(n_scripts)
oc, nc = Counter(norm(o_script.split("\n"))), Counter(norm(n_js.split("\n")))
missing, extra = list((oc - nc).elements()), list((nc - oc).elements())
a_js = not missing and not extra

# ---------- A3 顶层可执行语句顺序 ----------
TL = re.compile(r"^(const|let|var)\s|^\(async function")
o_top = norm([l for l in o_script.split("\n") if TL.match(l)])
n_top = norm([l for l in n_js.split("\n") if TL.match(l)])
a_top = o_top == n_top

print("[A] CSS 逐行等价=%s | JS 行多重集等价=%s(缺 %d / 多 %d) | 顶层可执行语句顺序一致=%s(%d 条)"
      % (a_css, a_js, len(missing), len(extra), a_top, len(o_top)))
for l in missing[:5]:
    print("    原文缺:", l[:90])
for l in extra[:5]:
    print("    新增多:", l[:90])
if not (a_css and a_js and a_top):
    fails.append("A")

# ---------- B 骨架等价 ----------
def strip_tags(t):
    t = re.sub(r"<style>.*?</style>", "", t, flags=re.S)
    t = re.sub(r"<script>.*?</script>", "", t, flags=re.S)
    t = re.sub(r"<link rel=\"stylesheet\" href=\"/(css|js)/[^\"]+\">", "", t)
    return re.sub(r"<script src=\"/(css|js)/[^\"]+\"></script>", "", t)


b_ok = norm(strip_tags(orig).split("\n")) == norm(strip_tags(new).split("\n"))
print("[B] 去掉 style/script 后 HTML 标记逐行一致=%s" % b_ok)
if not b_ok:
    ov, nv = norm(strip_tags(orig).split("\n")), norm(strip_tags(new).split("\n"))
    print("    行数 原=%d 新=%d 首个差异:" % (len(ov), len(nv)),
          next(((i, x, y) for i, (x, y) in enumerate(zip(ov, nv)) if x != y), "无(仅长度不同)"))
    fails.append("B")

# ---------- C 内联事件处理器 ----------
H = re.compile(r"\bon[a-z]+\s*=\s*\"([^\"]+)\"", re.I)
CALL = re.compile(r"([A-Za-z_$][\w$]*)\s*\(")
RESERVED = {"if", "for", "while", "switch", "return", "function", "typeof", "event", "Math", "Number",
            "String", "Boolean", "Array", "Object", "JSON", "encodeURIComponent", "decodeURIComponent",
            "confirm", "alert", "setTimeout", "document", "window"}
oh, nh = sorted(H.findall(orig)), sorted(H.findall(all_js_new))
undefined = sorted({n for body in nh for n in CALL.findall(body)
                    if n not in RESERVED
                    and not re.search(r"(function\s+%s\s*\(|(const|let|var)\s+%s\s*[=:])" % (re.escape(n), re.escape(n)), n_js)})
print("[C] 内联处理器 %d→%d 集合一致=%s | 未解析标识符=%s" % (len(oh), len(nh), oh == nh, undefined or "无"))
if oh != nh or undefined:
    if oh != nh:
        print("    仅原:", [x for x in oh if oh.count(x) != nh.count(x)][:4], "仅新:", [x for x in nh if nh.count(x) != oh.count(x)][:4])
    fails.append("C")

# ---------- D API 调用点 ----------
def calls(t):
    return sorted(set(re.findall(r"api\((`[^`]+`|'[^']+')", t)) | set(re.findall(r"fetch\((`[^`]+`|'[^']+')", t)))


oa, na = calls(orig), calls(all_js_new)
print("[D] API 调用点 原=%d 新=%d 集合一致=%s" % (len(oa), len(na), oa == na))
if oa != na:
    print("    仅原:", [x for x in oa if x not in na], "仅新:", [x for x in na if x not in oa])
    fails.append("D")

io.open(ROOT + r"\docs\p4b0\evidence\after\invariants.json", "w", encoding="utf-8").write(json.dumps(
    {"css_line_eq": a_css, "js_multiset_eq": a_js, "js_missing": len(missing), "js_extra": len(extra),
     "toplevel_order_eq": a_top, "toplevel_count": len(o_top), "markup_eq": b_ok,
     "handlers_eq": oh == nh, "handler_count": len(nh), "undefined_idents": undefined, "api_eq": oa == na,
     "fails": fails}, ensure_ascii=False, indent=2) + "\n")
print("\n[SUM] %s" % ("全部不变量通过" if not fails else "失败项: " + ",".join(fails)))
sys.exit(1 if fails else 0)
