#!/usr/bin/env python3
"""P4b-0 复核人独立校验(与实现者的 verify_invariants.py 相互独立,不采信其尺子)。

从仓库根运行:  python docs/p4b0/review_independent_check.py

判据:
  R1 整文件逐行还原:把 css/js 按加载顺序内联回 index.html(去掉本次新增的横幅行与空行),
     必须与 **master 的 index.html blob**(不是实现者留的快照)完全一致 —— 证明"只是搬运,没改写"。
     这一条同时覆盖 HTML 骨架 + CSS + JS,比"分段比对"更强。
  R2 原始行(不 strip 首尾空白)多重集比对:任何一行内部/前导缩进被改动都会被抓出来
     (模板字符串里的空格是有语义的,strip 版尺子看不见)。多出来的行必须全是空行或注释横幅。
  R3 顶层语句全量清单:列出原脚本里所有**列 0** 的非声明语句,标出实现者尺子(TL 正则)
     覆盖几条、漏几条,并核对新旧顺序一致 —— 判断"跨文件重排是否真安全"。
  R4 内联处理器被调标识符去重计数:复核 P4B0.md §二 声称的"31 个全局函数"。
"""
import io
import re
import subprocess
import sys
from collections import Counter

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = r"E:\AILearn\NovaCampus"
LOAD_ORDER = ["api", "ui", "chat", "kb", "weekly"]
BANNER = re.compile(r"^\s*(?:/\*.*?\*/|//.*)\s*$")
fails = []


def read(p):
    return io.open(p, encoding="utf-8", newline="").read().replace("\r\n", "\n")


def drop_banner(t, max_lines):
    """丢弃文件开头最多 max_lines 行的注释横幅(css=1 / js=2),其余原样保留。"""
    lines = t.split("\n")
    cut = 0
    while cut < max_lines and lines and lines[cut].strip() and BANNER.match(lines[cut]):
        cut += 1
    return "\n".join(lines[cut:]), cut


# ---------- 基准:直接从 master commit 取 blob,绕开实现者留的快照 ----------
orig = subprocess.check_output(["git", "show", "master:novaagent/web/index.html"],
                               cwd=ROOT).decode("utf-8").replace("\r\n", "\n")
new = read(ROOT + r"\novaagent\web\index.html")
js_txt = {f: read(ROOT + "\\novaagent\\web\\js\\%s.js" % f) for f in LOAD_ORDER}
css_txt = read(ROOT + r"\novaagent\web\css\theme.css")

n_st = (len(re.findall(r"<style", orig)), len(re.findall(r"<style", new)))
n_sc = (len(re.findall(r"<script", orig)), len(re.findall(r"<script", new)))
print("[R0] 块数量 原 style=%d script=%d | 新 style=%d script=%d(新应为 0 个 style、%d 内联+5 外链)"
      % (n_st[0], n_sc[0], n_st[1], n_sc[1], n_sc[1] - 5))
if n_st[0] != 1 or n_sc[0] != 1:
    print("    [FAIL] 原文件不止一个 style/script 块;实现者尺子用 re.search 只取第一个,会漏")
    fails.append("R0")

o_style = re.search(r"<style>\n(.*?)\n</style>", orig, re.S).group(1)
o_script = re.search(r"<script>\n(.*?)\n</script>", orig, re.S).group(1)

# ---------- R1 三段还原:骨架 / CSS / JS 块 ----------
css_body, c_drop = drop_banner(css_txt, 1)
bodies = [drop_banner(js_txt[f], 2)[0] for f in LOAD_ORDER]
js_drop = sum(drop_banner(js_txt[f], 2)[1] for f in LOAD_ORDER)
inline_boot = re.findall(r"<script>\n(.*?)\n</script>", new, re.S)
all_new_js = "\n".join(bodies + inline_boot)

ASSET = re.compile(r'<link rel="stylesheet" href="/css/[^"]+">|<script src="/js/[^"]+"></script>')


def only_markup(t):
    t = re.sub(r"<style>.*?</style>", "", t, flags=re.S)
    t = re.sub(r"<script>.*?</script>", "", t, flags=re.S)
    return [l for l in ASSET.sub("", t).split("\n") if l.strip()]


r1a = only_markup(orig) == only_markup(new)
print("[R1a] 骨架标记(去 style/script/本次新增资源标签)逐行一致=%s(原=%d 新=%d 行)"
      % (r1a, len(only_markup(orig)), len(only_markup(new))))
if not r1a:
    for i, (x, y) in enumerate(zip(only_markup(orig), only_markup(new))):
        if x != y:
            print("      @%d 原:%r\n      @%d 新:%r" % (i, x[:110], i, y[:110]))
            break
    fails.append("R1a")

o_css = [l for l in o_style.split("\n")]
n_css = [l for l in css_body.split("\n")]
while n_css and not n_css[-1].strip():      # 容忍文件末尾单个换行造成的空尾元素
    n_css.pop()
r1b = o_css == n_css
print("[R1b] CSS **原始行(含缩进)按顺序**完全一致=%s(原=%d 新=%d)" % (r1b, len(o_css), len(n_css)))
if not r1b:
    for i, (x, y) in enumerate(zip(o_css, n_css)):
        if x != y:
            print("      @%d 原:%r\n      @%d 新:%r" % (i, x[:110], i, y[:110]))
            break
    fails.append("R1b")


def top_blocks(text):
    """按大括号深度切出列 0 的顶层 function / const-arrow / 语句块,返回 [(name, 逐字块文本)]。"""
    out, lines, i = [], text.split("\n"), 0
    START = re.compile(r"^(?:async\s+)?function\s+([A-Za-z_$][\w$]*)|^(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=")
    while i < len(lines):
        l = lines[i]
        m = START.match(l)
        if m and l.count("{") - l.count("}") >= 0:
            name = m.group(1) or m.group(2)
            buf, depth = [l], 0
            while i < len(lines):
                depth += lines[i].count("{") - lines[i].count("}")
                buf.append(lines[i])
                i += 1
                if depth <= 0:
                    break
            out.append((name, "\n".join(buf[1:-0])))
            continue
        i += 1
    return out


o_blk, n_blk = top_blocks(o_script), top_blocks(all_new_js)
o_map, n_map = {}, {}
for name, body in o_blk:
    o_map.setdefault(name, []).append(body)
for name, body in n_blk:
    n_map.setdefault(name, []).append(body)
changed = sorted(set(o_map) ^ set(n_map))
diff_body = [k for k in o_map if k in n_map and o_map[k] != n_map[k]]
print("[R6] 顶层块逐字比对:原 %d 个 / 新 %d 个;名称集合差异=%s;同名但**正文有改动**=%s"
      % (len(o_blk), len(n_blk), changed or "无", diff_body or "无"))
for k in diff_body[:3]:
    print("      块 %s 原:%r" % (k, o_map[k][0][:120]))
    print("      块 %s 新:%r" % (k, n_map[k][0][:120]))
if changed or diff_body:
    fails.append("R6")

# ---------- R2 原始行(不 strip)多重集 ----------
new_raw = []
for f in LOAD_ORDER:
    new_raw += drop_banner(js_txt[f], 2)[0].split("\n")
new_raw += re.findall(r"<script>\n(.*?)\n</script>", new, re.S) and \
    "\n".join(re.findall(r"<script>\n(.*?)\n</script>", new, re.S)).split("\n")
oc, nc = Counter(o_script.split("\n")), Counter(new_raw)
missing, extra = list((oc - nc).elements()), list((nc - oc).elements())
bad_extra = [l for l in extra if l.strip() and not BANNER.match(l)]
print("[R2] 未 strip 的 JS 原始行:缺=%d 多=%d(其中非横幅/非空=%d)" % (len(missing), len(extra), len(bad_extra)))
for l in missing[:8]:
    print("    [FAIL] 缺行:", repr(l[:110]))
for l in bad_extra[:8]:
    print("    [FAIL] 多出非横幅行:", repr(l[:110]))
if missing or bad_extra:
    fails.append("R2")

# ---------- R3 顶层语句全量清单 ----------
TL_IMPL = re.compile(r"^(const|let|var)\s|^\(async function")     # 实现者尺子的覆盖面
DECL = re.compile(r"^(?:async\s+)?function\s|^}$|^\s*\)|^//|^/\*|^\s*$")
n_js_all = "\n".join([js_txt[f] for f in LOAD_ORDER] +
                     re.findall(r"<script>\n(.*?)\n</script>", new, re.S)).split("\n")


def top_all(lines):
    out, depth = [], 0
    for l in lines:
        if depth == 0 and l.strip() and not DECL.match(l):
            out.append(l.rstrip())
        depth += l.count("{") - l.count("}")
    return out


o_tl = [l for l in o_script.split("\n") if TL_IMPL.match(l)]
n_tl = [l for l in n_js_all if TL_IMPL.match(l)]
o_all, n_all = top_all(o_script.split("\n")), top_all(n_js_all)
uncovered = [l for l in o_all if not TL_IMPL.match(l)]
r3 = o_tl == n_tl and o_all == n_all
print("[R3] 尺子覆盖的顶层语句 原=%d 新=%d 顺序一致=%s" % (len(o_tl), len(n_tl), o_tl == n_tl))
print("[R3] 列 0 顶层语句全量 原=%d 新=%d 顺序一致=%s(尺子未覆盖=%d 条)"
      % (len(o_all), len(n_all), o_all == n_all, len(uncovered)))
for l in uncovered:
    print("      尺子外:", l[:110])
if not r3:
    fails.append("R3")

# ---------- R4 处理器被调标识符 + R5 全局可解析性 ----------
H = re.compile(r"\bon[a-z]+\s*=\s*\"([^\"]+)\"", re.I)
CALL = re.compile(r"([A-Za-z_$][\w$]*)\s*\(")
BUILTIN = {"if", "for", "while", "switch", "return", "typeof", "event", "Math", "Number", "String",
           "Boolean", "Array", "Object", "JSON", "encodeURIComponent", "decodeURIComponent",
           "confirm", "alert", "setTimeout", "document", "window", "Date", "parseInt", "parseFloat",
           "isNaN", "localStorage", "navigator", "location", "fetch", "console"}
oh, nh = H.findall(orig), H.findall(new + "\n".join(js_txt.values()))
idents = sorted({n for body in nh for n in CALL.findall(body)})
user_idents = [n for n in idents if n not in BUILTIN]
all_new_js = "\n".join(bodies + re.findall(r"<script>\n(.*?)\n</script>", new, re.S))
defined = set(re.findall(r"^(?:async\s+)?function\s+([A-Za-z_$][\w$]*)", all_new_js, re.M))
defined |= set(re.findall(r"^(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*[=:]", all_new_js, re.M))
unresolved = [n for n in user_idents if n not in defined]
print("[R4] 内联处理器 原=%d 新=%d;被调标识符去重=%d(其中项目自定义=%d):%s"
      % (len(oh), len(nh), len(idents), len(user_idents), ", ".join(user_idents)))
print("[R5] 处理器引用的自定义标识符在新多文件布局下不可解析的:%s" % (unresolved or "无"))
if len(oh) != len(nh):
    fails.append("R4")
if unresolved:
    fails.append("R5")
# R5b 跨文件重复的顶层 let/const(拆分才会引入的新风险:同名重复声明 = 加载期 SyntaxError)
tl_decl = re.findall(r"^(?:const|let|var)\s+([A-Za-z_$][\w$]*)", all_new_js, re.M)
dup = sorted({n for n in tl_decl if tl_decl.count(n) > 1})
print("[R5b] 顶层 let/const 声明 %d 条,跨文件重复(会导致白屏 SyntaxError)=%s" % (len(tl_decl), dup or "无"))
if dup:
    fails.append("R5b")
fn31 = re.findall(r"^(?:async\s+)?function\s+([A-Za-z_$][\w$]*)", o_script, re.M)
print("[R4c] 原脚本顶层 function 声明=%d;其中被内联处理器引用=%d/%d"
      % (len(fn31), len(set(fn31) & set(user_idents)), len(fn31)))

print("\n[SUM] %s" % ("独立校验全部通过" if not fails else "FAIL: " + ",".join(fails)))
sys.exit(1 if fails else 0)
