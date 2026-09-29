# -*- coding: utf-8 -*-
"""P4b-0 机械拆分:index.html → css/theme.css + js/{api,ui,chat,kb,weekly}.js + 骨架

铁律:内容逐字迁移(仅去掉块间空行),拆分前后 JS 拼接必须与原文一致(脚本内断言)。
"""
import io
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

P = "novaagent/web/index.html"
lines = io.open(P, encoding="utf-8").read().split("\n")  # 0-based


def seg(a, b):
    """1-based 闭区间切片"""
    return lines[a - 1 : b]


# 边界断言(防止行号漂移)
assert lines[10].strip() == "<style>", lines[10]
assert lines[363].strip() == "</style>", lines[363]
assert lines[364].strip() == "</head>", lines[364]
assert lines[365].strip() == "<body>", lines[365]
assert lines[506].strip() == "<div id=\"toast\"></div>", lines[506]
assert lines[508].strip() == "<script>", lines[508]
assert lines[878].strip() == "}", lines[878]
assert "boot" in lines[880], lines[880]
assert lines[883].strip() == "})();", lines[883]
assert lines[884].strip() == "</script>", lines[884]
assert lines[885].strip() == "</body>", lines[885]
assert lines[886].strip() == "</html>", lines[886]

css = seg(12, 363)
head = seg(1, 10)
body = seg(365, 507)

# JS 分块(1-based 闭区间;与 grep 的函数起点核对过)
blocks = {
    "api":    (510, 535),
    "ui_a":   (537, 561),
    "kb_a":   (563, 604),
    "weekly_a": (606, 660),
    "ui_b":   (662, 734),
    "chat":   (736, 824),
    "kb_b":   (826, 842),
    "weekly_b": (844, 879),
    "boot":   (881, 884),
}
expect_first = {
    "api": "const $ = id =>",
    "ui_a": "async function enter()",
    "kb_a": "async function loadDocs()",
    "weekly_a": "async function loadRecords()",
    "ui_b": "function openModal(title, html)",
    "chat": "async function send()",
    "kb_b": "async function upload()",
    "weekly_b": "async function expandFragment()",
    "boot": "(async function boot()",
}
for k, (a, b) in blocks.items():
    seg_lines = seg(a, b)
    assert seg_lines[0].startswith(expect_first[k]), (k, seg_lines[0][:60])

# 逐字校验:所有分块(去空行)拼接 == 原 JS 区(510..879,去空行)
orig_js = [l.strip() for l in seg(510, 879) if l.strip()]  # 1-based 510..879 = const $ 至 archiveReport 闭合}
part_js = []
for k, (a, b) in blocks.items():
    if k == "boot":
        continue
    part_js += [l.strip() for l in seg(a, b) if l.strip()]
assert part_js == orig_js, "拆分后 JS 与原文不一致!"

# 写文件
def write(path, text):
    io.open(path, "w", encoding="utf-8", newline="\n").write(text)

BANNER = "/* P4b-0 拆分:本文件内容由 index.html 原样迁移(零修改),行为零变化。 */\n"
write("novaagent/web/css/theme.css", "/* P4b-0 拆分:学术水墨 × 朱砂印 主题样式,由 index.html <style> 原样迁移。 */\n" + "\n".join(css) + "\n")

jmap = {
    "api.js":    [("api", blocks["api"])],
    "ui.js":     [("ui", blocks["ui_a"]), ("ui", blocks["ui_b"])],
    "chat.js":   [("chat", blocks["chat"])],
    "kb.js":     [("kb", blocks["kb_a"]), ("kb", blocks["kb_b"])],
    "weekly.js": [("weekly", blocks["weekly_a"]), ("weekly", blocks["weekly_b"])],
}
NOTE = {
    "api.js": "HTTP 封装与认证状态(TOKEN/ME)+ 登录/退出",
    "ui.js": "应用外壳(enter/switchTab)、弹窗、设置、消息 UI 原语",
    "chat.js": "对话:SSE 流式问答、来源与工具轨迹渲染、历史加载",
    "kb.js": "知识库:列表/筛选/分块查看/删除/上传/网页导入",
    "weekly.js": "周报:工作记录/详情/AI 扩充/生成/归档",
}
for fname, parts in jmap.items():
    js = BANNER + "// " + NOTE[fname] + "\n\n"
    js += "\n\n".join("\n".join(seg(a, b)).strip("\n") for _, (a, b) in parts) + "\n"
    write("novaagent/web/js/" + fname, js)

# 新骨架 index.html
new_html = "\n".join(head) + "\n"
new_html += "<link rel=\"stylesheet\" href=\"/css/theme.css\">\n"
new_html += "\n".join(body) + "\n\n"
for f in ["api", "ui", "chat", "kb", "weekly"]:
    new_html += f"<script src=\"/js/{f}.js\"></script>\n"
new_html += "<script>\n" + "\n".join(seg(*blocks["boot"])) + "\n</script>\n</body>\n</html>\n"
write(P, new_html)

print("[OK] 拆分完成:")
for f in ["css/theme.css", "js/api.js", "js/ui.js", "js/chat.js", "js/kb.js", "js/weekly.js", "index.html"]:
    t = io.open("novaagent/web/" + f, encoding="utf-8").read()
    print(f"  {f}: {len(t.splitlines())} 行 / {len(t.encode('utf-8'))} 字节")
