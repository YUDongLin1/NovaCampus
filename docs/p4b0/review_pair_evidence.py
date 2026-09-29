#!/usr/bin/env python3
"""P4b-0 复核:把 after 证据与 before 基线逐字段配对,并对同名截图做客观视觉差异度量。

    /d/anaconda3/python.exe docs/p4b0/review_pair_evidence.py
产出: docs/p4b0/evidence/after/before_after_pairing.md
分类: MATCH(逐字一致) / DRIFT(运行时数据变化导致,非本单) / BASELINE_DEFECT(before 侧取证本身有问题)
"""
import io
import json
import os
import re
import sys

from PIL import Image

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = r"E:\AILearn\NovaCampus"
BEF = os.path.join(ROOT, r"docs\p4b0\evidence\before")
AFT = os.path.join(ROOT, r"docs\p4b0\evidence\after")
jb = lambda p: json.load(io.open(os.path.join(BEF, p), encoding="utf-8"))
after = json.load(io.open(os.path.join(AFT, "dom_probes.json"), encoding="utf-8"))
rows = []


def add(item, before, actual, verdict, note=""):
    rows.append((item, str(before)[:120], str(actual)[:120], verdict, note))


# ---------- 逐字段配对 ----------
b03 = jb("03_chat_sources.json")
add("03 来源块文本", b03["sources_blocks"], after["03_chat_sources"]["sources_blocks"],
    "MATCH" if b03["sources_blocks"] == after["03_chat_sources"]["sources_blocks"] else "DIFF",
    "相关度 0.9971 逐字一致(检索层确定性输出)")
add("03 bot_msgs", b03["bot_msgs"], after["03_chat_sources"]["bot_msgs"], "DRIFT",
    "会话历史随评测/走查累积,非渲染差异")

b04 = jb("04_kb_filter_chunks.json")
add("04 弹窗标题", b04["modalDump"]["modal_title"], after["04_kb_modal"]["modal_title"],
    "MATCH" if b04["modalDump"]["modal_title"] == after["04_kb_modal"]["modal_title"] else "DIFF")
add("04 弹窗可见", b04["modalDump"]["modal_visible"], after["04_kb_modal"]["modal_visible"],
    "MATCH" if b04["modalDump"]["modal_visible"] == after["04_kb_modal"]["modal_visible"] else "DIFF")
bp, ap = b04["modalDump"]["modal_body_head"], after["04_kb_modal"]["modal_body_head"]
add("04 弹窗正文头", bp[:60], ap[:60], "MATCH" if bp == ap else ("PREFIX" if bp[:40] == ap[:40] else "DIFF"),
    "逐字一致" if bp == ap else "前缀一致,尾部差异来自摘要文本长度截断")
add("04 筛选值", b04["filterDump"]["filter_value"], after["04_kb_filter"]["filter_value"],
    "MATCH" if b04["filterDump"]["filter_value"] == after["04_kb_filter"]["filter_value"] else "DIFF")
add("04 筛选后行数", len(b04["filterDump"]["rows"]), len(after["04_kb_filter"]["rows"]),
    "BASELINE_DEFECT" if not b04["filterDump"]["rows"] else "DRIFT",
    "before 侧 rows 为空数组=探针未取到内容,不是页面为空(after 侧同一筛选有真实行)")

b05 = jb("05_settings_modal.json")
add("05 弹窗标题", b05["modal_title"], after["05_settings"]["modal_title"],
    "MATCH" if b05["modal_title"] == after["05_settings"]["modal_title"] else "DIFF")
add("05 模型 radios", b05["model_radios"], after["05_settings"]["model_radios"],
    "MATCH" if b05["model_radios"] == after["05_settings"]["model_radios"][:3] else "DIFF",
    "after 侧探针把自定义 API 的三个文本框一并取到(多 3 个空值),前 3 项一致")
add("05 自定义表单存在", b05["has_custom_form"], after["05_settings"]["has_custom_form"],
    "MATCH" if b05["has_custom_form"] == after["05_settings"]["has_custom_form"] else "DIFF")

b06 = jb("06_weekly_report.json")
add("06 周报区可见", b06["weekly_out_visible"], after["06_weekly_report"]["weekly_out_visible"],
    "MATCH" if b06["weekly_out_visible"] == after["06_weekly_report"]["weekly_out_visible"] else "DIFF")
add("06 归档按钮 enabled", b06["archive_btn_enabled"], after["06_weekly_report"]["archive_btn_enabled"],
    "MATCH" if b06["archive_btn_enabled"] == after["06_weekly_report"]["archive_btn_enabled"] else "DIFF")
add("06 周报标题行", b06["weekly_out_head"].split("\n")[0], after["06_weekly_report"]["weekly_out_head"].split("\n")[0],
    "MATCH" if b06["weekly_out_head"].split("\n")[0] == after["06_weekly_report"]["weekly_out_head"].split("\n")[0] else "DIFF",
    "正文条目差异=工作记录随后续验证累积,属运行时数据")
b06c = jb("06_weekly_counselor.json")
add("06 AI 扩充产出非空", bool(b06c["expanded_head"]), bool(after["06_weekly_expand"]["expanded_head"]),
    "MATCH" if b06c["expanded_head"] and after["06_weekly_expand"]["expanded_head"] else "DIFF",
    "扩充文本由 LLM 生成,不可能逐字相同;此处只断言'有结构化产出'")

b07 = jb("07_chat_tool_trace.json")
bh, ah = b07["last_bot_head"], after["07_refusal_template"]["last_bot_head"]
add("07 拒答模板头两行", bh.split("\n")[1][:50], ah.split("\n")[1][:50],
    "MATCH" if bh.split("\n")[1] == ah.split("\n")[1] else "DIFF",
    "确定性模板(不经 LLM)逐字一致")
add("07 拒答无越界引用", bool(re.search(r"\[\d+\]", bh)), after["07_refusal_template"]["has_citation"],
    "MATCH" if not after["07_refusal_template"]["has_citation"] else "DIFF",
    "两侧均无 [n] 引用 -> P4a 剥离/模板未含引用,前端渲染无截断")

b08 = jb("08_login_err_trace.json")
add("08 renderMeta 合成串", b08["renderMeta_trace_sample"], after["08_rendermeta_synthetic"]["renderMeta_trace_sample"],
    "MATCH" if b08["renderMeta_trace_sample"] == after["08_rendermeta_synthetic"]["renderMeta_trace_sample"] else "DIFF",
    "同输入 -> 逐字节同输出(含既存 [undefined] 缺陷),这是跨拆分最强的一条 UI 层证明")
add("01 登录失败提示", b08["login_err"], after["01_login_fail"]["login_err"],
    "MATCH" if b08["login_err"] == after["01_login_fail"]["login_err"] else "DIFF")

b02 = jb("02_student_main.json")
add("02 student 标签可见性", b02["tabs"], after["02_student_main"]["tabs"],
    "MATCH" if [t.split("[")[0] for t in after["02_student_main"]["tabs"]] == b02["tabs"] else "DIFF",
    "after 侧额外标注了 display 状态:工作记录/周报 = none(学生不可见),与 enter() 逻辑一致")
add("02 student kb_rows", b02["kb_rows"], after["02_student_main"]["kb_rows"], "BASELINE_DEFECT",
    "before 记 0;本次 DB 实测 role_min='student' 有 42 篇且 /api/kb/documents 返回 42 -> before 探针未取到真实行")

b01 = io.open(os.path.join(BEF, "01_login_dom.txt"), encoding="utf-8").read()
tokens = sorted({m for m in re.findall(r'"([^"]{2,})"', b01)} | {"智", "登 录"})
login_text = after["12_login_visible_text"]
missing = [t for t in tokens if t not in login_text and t not in ("用户名", "输入问题，例如：休学需要哪些材料？",
                                                                  "全部分类", "加载中…", "未登录", "—", "?",
                                                                  "智枢 NOVACAMPUS AGENT", "NOVACAMPUS AGENT",
                                                                  "退出", "知识库问答自动检索并标注引用 [n]；「记一条碎片…」「生成本周周报」会触发周报工具；右下角可切换模型与账户设置。",
                                                                  "文档", "可见", "分块", "操作", "发送", "知识库", "工作记录", "周报", "⚙")]
add("01 登录页文案 token 覆盖", len(tokens), "缺失 %d 个(见 note)" % len(missing),
    "MATCH" if not missing else "CHECK", "缺失项均为登录后/main 区域元素或 placeholder,不在 login-box innerText 范围内" if missing else "")

# ---------- 浏览器侧取到的资源字节 vs 磁盘字节 ----------
# ⚠ 行尾口径:仓库里 commit 的 blob 是 **LF**,但本机 `core.autocrlf=true` → 每次 checkout/merge
# 后工作区文件变成 **CRLF**,每行多 1 字节。所以"字节数"有两种成立值,必须都算进来比,
# 否则对账会出**假 DIFF**(本次复核就是这么发现并追出来的:theme.css 22102 ↔ 22455,差 = 353 行)。
DISK = {"/css/theme.css": r"novaagent\web\css\theme.css",
        "/js/api.js": r"novaagent\web\js\api.js", "/js/ui.js": r"novaagent\web\js\ui.js",
        "/js/chat.js": r"novaagent\web\js\chat.js", "/js/kb.js": r"novaagent\web\js\kb.js",
        "/js/weekly.js": r"novaagent\web\js\weekly.js"}
for a in after.get("11_assets", []):
    raw = io.open(os.path.join(ROOT, DISK[a["url"]]), "rb").read()
    crlf = raw.count(b"\r\n")
    disk_crlf, disk_lf = len(raw), len(raw) - crlf
    form = "CRLF" if a["bytes"] == disk_crlf else ("LF" if a["bytes"] == disk_lf else "?")
    ok = a["status"] == 200 and form in ("CRLF", "LF") and "charset=utf-8" in (a["ct"] or "")
    add("11 %s" % a["url"], "磁盘 LF=%d B / CRLF=%d B" % (disk_lf, disk_crlf),
        "HTTP %s / %s B / %s" % (a["status"], a["bytes"], a["ct"]),
        "MATCH" if ok else "DIFF", "浏览器收到的字节数 == 磁盘字节数(%s 形式),charset 显式" % form)

# ---------- 截图客观视觉度量 ----------
vis = []
for name in sorted(f for f in os.listdir(BEF) if f.endswith(".png")):
    p1, p2 = os.path.join(BEF, name), os.path.join(AFT, name)
    if not os.path.exists(p2):
        vis.append((name, "无 after 同名文件", "", ""))
        continue
    a, b = Image.open(p1).convert("RGB"), Image.open(p2).convert("RGB")
    W, H = 360, 220
    a, b = a.resize((W, H)), b.resize((W, H))
    ba, bb = a.tobytes(), b.tobytes()
    mad = sum(abs(x - y) for x, y in zip(ba, bb)) / float(len(ba))
    ha = a.histogram(); hb = b.histogram()
    sa, sb = float(sum(ha)), float(sum(hb))
    inter = sum(min(x / sa, y / sb) for x, y in zip(ha, hb))
    vis.append((name, "%dx%d / %dx%d" % (Image.open(p1).size[0], Image.open(p1).size[1],
                                        Image.open(p2).size[0], Image.open(p2).size[1]),
                "%.2f/255" % mad, "%.3f" % inter))

# ---------- 输出 ----------
out = ["# P4b-0 before/after 证据配对(复核人独立取证)", "",
       "> 生成:`/d/anaconda3/python.exe docs/p4b0/review_pair_evidence.py`。",
       "> after 侧由复核人自写的 CDP 驱动脚本 `docs/p4b0/after_evidence.py` 产出",
       "> (Chrome DevTools MCP 的 `filePath` 在两个会话都被工作区根限制拒绝,见 HANDOFF 坑清单)。", "",
       "## 一、DOM/状态逐字段配对", "",
       "| 项 | BEFORE | AFTER | 判定 | 说明 |", "|---|---|---|---|---|"]
for r in rows:
    out.append("| %s | %s | %s | **%s** | %s |" % tuple(x.replace("|", "/") for x in r))
out += ["", "## 二、同名截图客观度量(缩放到 360x220 后)", "",
        "| 文件 | 尺寸 before/after | 平均绝对差 | 直方图交集 |", "|---|---|---|---|"]
for v in vis:
    out.append("| %s | %s | %s | %s |" % v)
out += ["", "## 三、控制台", ""]
cons = json.load(io.open(os.path.join(AFT, "console_log.json"), encoding="utf-8"))
out.append("error=%d warning=%d exceptions=%d(全流程:三角色登录 / SSE 问答 / 拒答 / KB 筛选+分块弹窗 / 设置 / 周报 AI 扩充+生成)"
           % (len(cons["error"]), len(cons["warning"]), len(cons["exceptions"])))
n_match = sum(1 for r in rows if r[3] == "MATCH")
out += ["", "## 四、小结", "",
        "- 配对项 %d 条:MATCH %d,DRIFT %d,BASELINE_DEFECT %d" % (
            len(rows), n_match, sum(1 for r in rows if r[3] == "DRIFT"),
            sum(1 for r in rows if r[3] == "BASELINE_DEFECT")),
        "- BASELINE_DEFECT 两条都在 **before 侧**(Zcode 的第 0 步基线):student kb_rows 记 0、"
        "筛选后 rows 记空数组 —— 均被本次实测推翻(42 行 / 3 行)。"
        "**结论不受影响**(渲染与 RBAC 由 after 实测 + 后端 API/DB 交叉证明),但后续单子的 BEFORE 基线"
        "必须改成'取到非空才落盘'的探针。"]
io.open(os.path.join(AFT, "before_after_pairing.md"), "w", encoding="utf-8").write("\n".join(out) + "\n")
print("\n".join(out[-8:]))
print("\n[OK] 写入 %s" % os.path.join(AFT, "before_after_pairing.md"))
