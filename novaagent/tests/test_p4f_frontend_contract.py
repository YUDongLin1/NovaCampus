"""P4f 前端契约自测:**零额度、零浏览器**(纯文本 + 正则 + DOM 桩)。

为什么需要它:前端没有 pytest 生态,评审方也无法在浏览器里逐条复算。
本文件把「P4b-0 行为零变化不变量」与「P4f 接线是否完整」变成**可离线复算的断言**。

不覆盖什么(如实标注):
  · 不做真实渲染/布局验证 —— 那要浏览器,本单零依赖。
  · 不验证交互时序(点一下会怎样)—— 只验证**接线存在且指向存在的 id/端点**。
  · ⚠ 「id 存在」只保证不会静默 null,保证不了 CSS 好看 —— 视觉部分需人工过一眼。

运行:
    novaagent/.venv/Scripts/python.exe novaagent/tests/test_p4f_frontend_contract.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "novaagent" / "web"
JS = WEB / "js"
CSS = WEB / "css"

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError, OSError):
    pass

RESULTS: list[tuple[bool, str, str]] = []


def check(ok: bool, name: str, detail: str = "") -> None:
    RESULTS.append((bool(ok), name, detail))


HTML = (WEB / "index.html").read_text(encoding="utf-8")
JS_FILES = {p.name: p.read_text(encoding="utf-8") for p in sorted(JS.glob("*.js"))}
ALL_JS = "\n".join(JS_FILES.values())
MAIN_PY = (ROOT / "novaagent" / "novaagent" / "main.py").read_text(encoding="utf-8")


def html_ids() -> set[str]:
    return set(re.findall(r'\bid="([^"]+)"', HTML))


# ==================== ① 静态资源加载顺序与路由 ====================
def test_asset_routes() -> None:
    """api.js 必须**最先**加载:其余文件在顶层就引用 TOKEN/$/isStaff()。"""
    srcs = re.findall(r'<script src="/js/([^"]+)"></script>', HTML)
    check(bool(srcs), "F 前置:index.html 用 /js/{name} 路由加载脚本(非内联)", f"srcs={srcs}")
    check(len(srcs) == len(set(srcs)), "F 没有重复加载同一个脚本", f"srcs={srcs}")
    if srcs:
        check(srcs[0] == "api.js", "F api.js 最先加载(其余文件顶层依赖它的 TOKEN/$/esc)", f"first={srcs[0]}")
    # 每个引用的文件都必须真实存在 —— 拼错路径是 404 且**不报错**,页面静默半瘫
    for s in srcs:
        check((JS / s).is_file(), f"F 引用的 {s} 真实存在(404 会静默半瘫)", f"path={JS / s}")
    # css 同理
    for c in re.findall(r'<link rel="stylesheet" href="/css/([^"]+)">', HTML):
        check((CSS / c).is_file(), f"F 引用的 {c} 真实存在", f"path={CSS / c}")
    # 后端路由存在(通用路由,新增文件无需改 main.py)
    check('@app.get("/js/{name}")' in MAIN_PY, "F 后端 /js/{name} 路由在(新增 js 无需改 main.py)", "")
    check('@app.get("/css/{name}")' in MAIN_PY, "F 后端 /css/{name} 路由在(新增 css 无需改 main.py)", "")
    check("_serve_web_asset" in MAIN_PY and "startswith(str(root))" in MAIN_PY,
          "F 静态路由有目录穿越防护(root 前缀校验)", "")


# ==================== ② P4b-0「行为零变化」不变量 ====================
def test_p4b0_invariants() -> None:
    """P4b-0 拆分的承诺是「拆分本身零行为变化」。本单必须证明没顺手改掉那些行为。"""
    # ① 会话栏的既有交互入口一个都不能少
    for fn in ("loadConversations", "newConversation", "switchConversation",
               "renameConversation", "archiveConversation", "deleteConversation",
               "abortInflight", "updateCtxBar"):
        check(f"function {fn}(" in ALL_JS, f"F 不变量:会话栏函数 {fn}() 仍在", "")
    # ② send 的中止与回填语义(P4b C5 / P4b-fix ⑤)
    check("window._convAbort = new AbortController()" in JS_FILES["chat.js"],
          "F 不变量:send 仍挂 AbortController(切会话中止)", "")
    check("e.name === 'AbortError'" in JS_FILES["chat.js"],
          "F 不变量:AbortError 分支仍在(不留残影)", "")
    check("if (ev.conversation_id) window._convId = ev.conversation_id" in JS_FILES["chat.js"],
          "F 不变量:首问后回填自动建的会话 id", "")
    # ③ P4c @ 选择器:问句永不含 @xxx
    check("question: q" in JS_FILES["chat.js"] and "p.scope = scope" in JS_FILES["chat.js"],
          "F 不变量:@ 选择器仍把范围与问句分离传参", "")
    check("input.value.replace(/@/g, '')" in JS_FILES["chat.js"],
          "F 不变量:@ 仍只作唤起符号(从问句里移除)", "")
    # ④ P4e 联网开关:默认关 + 显式覆盖
    check("window._webSearch = false;" in JS_FILES["chat.js"], "F 不变量:联网默认关闭", "")
    check("p.web_search = !!window._webSearch" in JS_FILES["chat.js"],
          "F 不变量:联网开关单次请求显式覆盖", "")
    # ⑤ P4b-0 拆分时未加的全局:ui.js 的 enter/switchTab 与周报/知识库页
    for fn in ("enter", "switchTab", "openSettings", "addMsg", "renderMeta", "loadDocs"):
        check(f"function {fn}(" in ALL_JS, f"F 不变量:应用外壳函数 {fn}() 仍在", "")
    # ⑥ P4e 联网来源单独分区(不与本地编号混)
    check("sources-web" in JS_FILES["chat.js"], "F 不变量:联网来源仍单独分区渲染", "")
    # ⑦ 周报/工作记录 tab 仍在
    for t in ("pane-kb", "pane-records", "pane-weekly"):
        check(f'id="{t}"' in HTML, f"F 不变量:{t} 面板仍在", "")


# ==================== ③ P4f 接线完整性 ====================
def test_persona_wiring() -> None:
    ids = html_ids()
    P = JS_FILES["persona.js"]

    # ① 会话栏里有选择器容器与提示位
    for i in ("persona-bar", "persona-hint"):
        check(i in ids, f"F persona 容器 #{i} 在 DOM 里", "")
    check('<script src="/js/persona.js"></script>' in HTML, "F persona.js 已加载", "")

    # ② 选择器渲染出的 id 必须真的被 onPersonaPick 之外的代码引用得到
    check("$('persona-select')" in ALL_JS, "F 渲染出的 #persona-select 有被消费", "")
    check("function onPersonaPick(" in P, "F onPersonaPick 存在", "")
    check("onPersonaPick(this.value)" in P, "F 下拉 onchange 接到 onPersonaPick", "")

    # ③ 请求体必须带 persona_id(否则「首问前先选人设」会静默丢失)
    check("p.persona_id = window._personaId" in JS_FILES["chat.js"],
          "F 每轮请求显式带 persona_id(首问前选人设也生效)", "")
    check("if (window._personaId) p.persona_id" in JS_FILES["chat.js"],
          "F 未选人设时不带该字段(而不是带 null 覆盖后端解析)", "")

    # ④ 切会话必须对齐选择器(否则界面显示的人设 ≠ 实际发送的人设)
    check("syncPersonaFromConversation(cid)" in JS_FILES["conversations.js"],
          "F 切会话时对齐 persona 选择器", "")
    check("async function syncPersonaFromConversation(" in P, "F syncPersonaFromConversation 已实现", "")

    # ⑤ 会话列表带人设徽标
    check("c.persona_name" in JS_FILES["conversations.js"], "F 会话列表渲染人设徽标", "")

    # ⑥ 账户入口在会话栏内(不是 body 下的 fixed 浮层)
    aside = re.search(r'<aside id="conv-sidebar">(.*?)</aside>', HTML, re.S)
    check(bool(aside), "F 会话栏 <aside> 存在", "")
    if aside:
        inner = aside.group(1)
        check("acct-entry" in inner, "F 账户入口已移入会话栏内", f"inner_head={inner[:80]!r}")
        check("account-card" not in HTML, "F 旧的 body 级 #account-card 浮层已移除(两套 position 会打架)", "")
    # theme.css 里那条 fixed 规则也必须跟着失效,否则残留样式仍会把它钉在右下角
    theme = (CSS / "theme.css").read_text(encoding="utf-8")
    check("#acct-entry" in (CSS / "persona.css").read_text(encoding="utf-8"),
          "F #acct-entry 有自己的样式定义", "")
    check("margin-top: auto" in (CSS / "persona.css").read_text(encoding="utf-8")
          or "flex: 0 0 auto" in (CSS / "persona.css").read_text(encoding="utf-8"),
          "F 账户入口不参与滚动(长列表不会把它挤走)", "")

    # ⑦ 前端**不得**有权限判断(P4b C2 延续:同一判据只应有一处)
    bad = re.findall(r"role\s*===?\s*['\"](student|counselor|admin)['\"]", P)
    check(not bad, "F persona.js 不做角色可见性判断(判据只在后端)", f"found={bad}")
    check("isStaff()" in P, "F 只用 isStaff() 决定**是否提供管理入口**,不判断谁能看到谁", "")


# ==================== ④ persona.js 引用的 id/端点必须真实存在 ====================
def test_persona_ids_and_endpoints() -> None:
    """**最容易静默失效的一类**:JS 里 `$('pf-xxx')` 拼错 → null → 弹窗提交时抛异常。
    这里做「凡是 openPersonaEditor 模板里出现的 id,savePersona/removePersona 都得能取到」的对账。"""
    P = JS_FILES["persona.js"]
    # 模板是 openModal(title, `...`) 里的反引号块;结尾是 </p>` + 换行 + 4 空格 + `);`
    tpl = re.search(r"openModal\(p \?.*?`\s*\);", P, re.S)
    check(bool(tpl), "F 前置:找得到 openPersonaEditor 的模板", "")
    if tpl:
        declared = set(re.findall(r'id="(pf-[a-z]+)"', tpl.group(0)))
        check(bool(declared), "F 模板里确实声明了表单 id(防空集假通过)", f"ids={sorted(declared)}")
        for i in sorted(declared):
            check(f"$('{i}')" in P, f"F 模板声明的 #{i} 在 JS 里有对应的读取(拼错=静默 null)", "")
        # 这几个是「读不到就崩」的硬依赖
        for i in ("pf-name", "pf-style", "pf-vis", "pf-err"):
            check(f"$('{i}')" in P, f"F 必填字段 #{i} 被读取", "")

    # 端点对账:前端打的每条 persona 路径,后端都得有
    for m in re.findall(r"api\((?:'([^']*?)'|`([^`]*?)`)", P):
        raw = (m[0] or m[1]).split("?")[0]
        if "persona" not in raw:
            continue
        # 模板串里的 ${...} 归一化成 FastAPI 的 {param} 写法
        norm = re.sub(r"\$\{[^}]+\}", "{}", raw)
        pat = re.escape(norm).replace(re.escape("{}"), r"\{[^}]+\}")
        check(re.search(r'@app\.\w+\("' + pat + r'"', MAIN_PY) is not None,
              f"F persona 端点 {norm} 在后端存在(拼错=404)", "")

    # 反向:后端的 persona 路由都该被前端用到?——不必(管理面可以有未暴露的端点),
    # 但 /api/personas 的 GET 必须在(选择器的数据源)
    check("'/api/personas'" in P, "F 选择器数据源是 GET /api/personas", "")
    # 分页/上限:列表接口带了 limit 吗?会话列表默认 200,人设列表没分页
    check("api('/api/personas')" in P, "F 拉人设列表未带多余参数(后端无分页,加了会被忽略)", "")


# ==================== ⑤ 与后端字段名对账 ====================
def test_field_contracts() -> None:
    """前后端字段名对账:前端读 `p.bound_folder_ids`,后端就得真返回这个键。
    字段名对不上是**静默**失效(得到 undefined,界面上"绑定 0 个文件夹")。"""
    P = JS_FILES["persona.js"]
    db_py = (ROOT / "novaagent" / "novaagent" / "db.py").read_text(encoding="utf-8")
    for f in ("id", "name", "college", "style", "persona_prompt",
              "bound_folder_ids", "bound_categories", "visibility", "is_default"):
        check(f in P, f"F 前端用到了 persona 字段 {f}", "")
    # 关键:bound_* 必须是 JSON 数组(前端直接 .length / .join)
    check('json.loads(d.get(k) or "[]")' in db_py,
          "F bound_* 在后端被解析成数组(否则前端 .length 会炸或恒为 undefined)", "")
    # 会话列表的 persona_name 由 list_conversations 的 LEFT JOIN 给出
    check("p.name AS persona_name" in db_py, "F list_conversations 带出 persona_name(LEFT JOIN)", "")
    check("LEFT JOIN personas" in db_py, "F 用 LEFT JOIN(软删除后仍要带出会话)", "")

    # 枚举值对账:风格档位。前端是对象字面量的**裸键**(concise: '简洁'),
    # 后端是元组里的引号串 —— 两种写法都要认,否则这条尺子自己先假红。
    styles = set(re.findall(r'["\']?(concise|balanced|detailed|warm|formal)["\']?\s*:',
                            P)) | set(re.findall(r'value="(concise|balanced|detailed|warm|formal)"', P))
    m = re.search(r"_STYLE_VALUES = \(([^)]*)\)", db_py)
    db_style_set = set(re.findall(r"[\"']([a-z]+)[\"']", m.group(1))) if m else set()
    check(bool(db_style_set), "F 前置:解析到了后端 _STYLE_VALUES(防空集假通过)", f"got={db_style_set}")
    check(styles == db_style_set,
          "F 风格枚举前后端一致(不一致=某些风格静默回落 balanced)",
          f"前端={sorted(styles)} 后端={sorted(db_style_set)}")
    # 可见性档位:后端已改名为 private/public
    check("'public'" in P, "F 前端用规格档位名 public", "")
    check("_PERSONA_VISIBILITY_VALUES = (\"private\", \"public\")" in db_py,
          "F 后端可见性档位是 private/public(规格原文)", "")


# ==================== ⑥ 注入文案不得在前端被当成指令 ====================
def test_injection_surface() -> None:
    """人设文本是**用户输入**,前端必须走 esc(),否则 personae 名/提示词本身就是 XSS 面。
    ⚠ esc() 当前只转义 & 与 <(api.js 既有实现,不是本单引入)。
    这里只断言「persona 相关渲染都经过 esc 或 textContent」。"""
    P = JS_FILES["persona.js"]
    for fld in ("p.name", "p.college"):
        check(f"esc({fld})" in P, f"F {fld} 渲染前经 esc()", "")
    check("esc(p ? p.persona_prompt : '')" in P, "F persona_prompt 回填经 esc()", "")
    check("esc(p ? p.name : '')" in P, "F name 回填经 esc()", "")
    check("esc(c.persona_name)" in JS_FILES["conversations.js"],
          "F 会话列表人设徽标经 esc()", "")
    # textarea 用 innerHTML 回填 → 必须转义,否则 </textarea> 可截断
    check("<textarea id=\"pf-prompt\"" in P and "esc(p ? p.persona_prompt : '')" in P,
          "F textarea 回填已转义(</textarea> 截断攻击)", "")


def main() -> int:
    for fn in (test_asset_routes, test_p4b0_invariants, test_persona_wiring,
               test_persona_ids_and_endpoints, test_field_contracts,
               test_injection_surface):
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            import traceback
            check(False, f"{fn.__name__} 抛异常", f"{type(e).__name__}: {e}")
            traceback.print_exc()
    npass = sum(1 for ok, _, _ in RESULTS if ok)
    total = len(RESULTS)
    lines = ["=" * 78]
    for ok, name, detail in RESULTS:
        lines.append(f"[{'PASS' if ok else 'FAIL'}] {name}")
        if not ok and detail:
            lines.append(f"        detail: {detail}")
    lines.append("=" * 78)
    lines.append(f"[RESULT] {npass}/{total} passed")
    body = "\n".join(lines)
    print(body)
    out = ROOT / "docs" / "p4f" / "evidence"
    out.mkdir(parents=True, exist_ok=True)
    (out / "frontend_selftest_output.txt").write_text(body + "\n", encoding="utf-8")
    print(f"[evidence] {out / 'frontend_selftest_output.txt'}")
    return 0 if npass == total else 1


if __name__ == "__main__":
    sys.exit(main())
