#!/usr/bin/env python3
"""P4a-1 Review 独立核验(不采信回执):
1) index_page 判据对 corpus 公开语料零误伤 + 对导航页样本必拒
2) index_page_stats 实测比例与回执/P4A1.md 声称值对账(claim -> 字段)
3) 身份证正则:保单号不得误伤,日期合法的真身份证样式必须仍拦截
注:corpus/clean/affairs/ 属第三方本地语料(红线),本脚本一律不读取不扫描。
"""
import io
import json
import re
import sqlite3
import sys

sys.path.insert(0, ".")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError, OSError):
    pass

from novaagent import main as nm

REPO = r"E:\AILearn\NovaCampus"
REPORT = REPO + r"\.review_p4a1\independent_check.txt"
out = io.open(REPORT, "w", encoding="utf-8")


def w(s):
    out.write(s + "\n")
    print(s)


fn_names = [n for n in dir(nm) if "index" in n.lower() or "gate" in n.lower() or "quality" in n.lower()]
w("[发现的质量门符号] %s" % fn_names)
stats_fn = getattr(nm, "index_page_stats", None)
is_idx = getattr(nm, "is_index_page", None)
assert stats_fn and is_idx, "index_page 判据函数缺失"

# --- 1. 导航页样本必须被拒 ---
sample = io.open(REPO + r"\docs\p4\evidence\sample_index_page.txt", encoding="utf-8").read()
body = sample.split("\n\n", 1)[1] if "# " in sample[:2] else sample
lines = [l for l in body.split("\n") if l.strip() and not l.startswith("#")]
txt = "\n".join(lines)
st = stats_fn(txt)
w("\n[导航页样本] stats=%s -> is_index_page=%s %s"
  % (json.dumps(st, ensure_ascii=False, default=str), is_idx(txt), "PASS(被拒)" if is_idx(txt) else "FAIL(没拒!)"))
w("  回执声称 81 行 短行 61.73pct 长行 9  ->  实测行数=%s 短行占比=%s 长行=%s"
  % (st.get("lines") or st.get("total"), st.get("short_ratio") or st.get("menu_ratio"), st.get("long")))

# --- 2. 公开语料零误伤(排除 affairs) ---
import glob
w("\n[corpus 公开语料逐篇] (affairs 已按红线排除)")
rej = 0
tot = 0
for f in sorted(glob.glob(REPO + r"\corpus\clean\policy\*.md")) + sorted(glob.glob(REPO + r"\corpus\clean\ops\*.md")) + sorted(glob.glob(REPO + r"\corpus\clean\guide\*.md")):
    s = io.open(f, encoding="utf-8").read()
    body2 = s.split("---\n\n", 1)[1] if s.startswith("---") else s
    tot += 1
    r = is_idx(body2)
    if r:
        rej += 1
        stt = stats_fn(body2)
        w("  [误伤!] %s  %s" % (f.split("clean\\")[1], json.dumps(stt, ensure_ascii=False, default=str)))
w("  合计扫描 %d 篇(公开),index_page 误伤 %d 篇 %s" % (tot, rej, "PASS" if rej == 0 else "FAIL"))

# --- 3. KB 内 6 篇新语料(doc_id 110~115)不得被判为索引页 ---
c = sqlite3.connect(REPO + r"\novaagent\data\agent.db")
w("\n[KB 已入库语料 doc_id>=110]")
bad = 0
for did, title in c.execute("select id,title from documents where id>=110 order by id"):
    chunks = "\n".join(r[0] for r in c.execute("select content from chunks where doc_id=? order by idx", (did,)))
    r = is_idx(chunks)
    if r:
        bad += 1
    w("  doc %-4d %-40s is_index_page=%s" % (did, title[:38], r))
w("  被判索引页=%d %s" % (bad, "PASS" if bad == 0 else "FAIL"))

# --- 4. 身份证正则:保单号不误伤 / 真样式仍拦 ---
w("\n[正则对账]")
pat = None
for name in ("RE_IDCARD", "RE_ID", "IDCARD"):
    if hasattr(nm, name):
        pat = getattr(nm, name)
        w("  使用常量 %s" % name)
        break
assert pat, "未找到身份证正则"
cases = [
    ("保单号(须放行)", "PECD201651010000000351", False),
    ("日期合法 18 位(须拦截)", "110101199003070019", True),
    ("出生日期不合法(须放行)", "110101199013070019", False),
    ("学号样式(须放行)", "2025100123456", False),
]
ok_all = True
for label, s, expect_hit in cases:
    hit = bool(re.search(pat, s))
    good = hit == expect_hit
    ok_all &= good
    w("  [%s] %-24s 输入=%s 命中=%s 期望=%s" % ("PASS" if good else "FAIL", label, s, hit, expect_hit))

# --- 5. quality_gate 对三脏 URL 的结构化拒绝(纯函数口径) ---
w("\n[gate 结构体拒绝(离线口径)]")
gate = getattr(nm, "quality_gate_reject", None) or getattr(nm, "quality_gate", None)
w("  函数=%s" % (gate.__name__ if gate else "未找到"))
if gate:
    nav = io.open(REPO + r"\docs\p4\evidence\sample_index_page.txt", encoding="utf-8").read()
    try:
        r = gate("https://infpub.swjtu.edu.cn/gksx/cw_zcjsfxx/sfxm_sfyj_sfbzjtsfs.htm", "收费项目、收费依据、收费标准及投诉方式", txt)
        w("  infpub 导航页 -> %s %s" % (r, "PASS" if r and r.get("code") == "index_page" else "FAIL"))
    except TypeError as e:
        w("  签名不同,跳过离线口径:%s(改由实站验证)" % str(e)[:80])

w("\n[SUM] 误伤=%d 索引页漏检=%d KB错判=%d 正则=%s"
  % (rej, 0 if is_idx(txt) else 1, bad, "PASS" if ok_all else "FAIL"))
out.close()
sys.exit(0 if (rej == 0 and bad == 0 and ok_all and is_idx(txt)) else 2)
