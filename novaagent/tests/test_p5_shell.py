"""P5 自测:外壳重构(P5-1)+ 辅导员页与头像库(P5-2)。

三条纪律,与其它自测一致:
  1. **零额度** —— 不打任何真实 LLM/embedding 请求;后端用例一律跑在**库副本**上,原库零写入;
  2. **每条断言都要能判红** —— 反向用例在文件内(改坏了当场红,不是跑通就行,坑 52);
  3. **非空前置** —— 断言"取到了东西",防空集假通过(坑 45)。

【为什么这里会用 node 真跑前端函数】
  纯文本/正则只能证明"字符串在那儿",证明不了逻辑对。`shell.js` / `avatars.js` /
  `conversations.js` 里的**纯函数**(visiblePageIds / hashToPage / avatarId /
  groupConversations)都挂了 `module.exports`,本文件用 node **真加载真调用**它们,
  得到的读数是**执行结果**不是源码猜测。
  ⚠ node 缺席时本文件**判红并说明理由**,不静默跳过 —— 「跳过的断言」等于没断言。

运行(项目 venv):
    novaagent/.venv/Scripts/python.exe novaagent/tests/test_p5_shell.py
退出码 0 = 全通过;非 0 = 有断言判红(坑 39:断言必须能影响退出码)。
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import shutil as _shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]          # E:/AILearn/NovaCampus
sys.path.insert(0, str(ROOT / "novaagent"))        # 与其余自测同一姿势(库副本用例要 import novaagent)
WEB = ROOT / "novaagent" / "web"
JS = WEB / "js"
CSS = WEB / "css"
EVIDENCE = ROOT / "docs" / "p5" / "evidence"

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


# ==================== node 实跑(纯函数) ====================
def _node_bin() -> str | None:
    for cand in ("node", "node.exe"):
        p = _shutil.which(cand)
        if p:
            return p
    managed = (Path.home() / ".workbuddy" / "binaries" / "node" / "versions"
               / "22.22.2-3" / "node.exe")
    return str(managed) if managed.exists() else None


NODE = _node_bin()

# 浏览器全局的最小桩:让这些文件在 node 里也能被 require(它们顶层会碰 window/document)
_NODE_STUB = """
global.window = global.window || { addEventListener() {}, _page: null, _serverNowMs: null,
  _personas: [], _personaId: null, _convId: null };
global.document = global.document || { getElementById() { return null; },
  querySelectorAll() { return []; }, createElement() { return { style: {}, classList: { toggle() {} } }; },
  body: { appendChild() {} } };
global.location = global.location || { hash: '' };
"""


def node_json(rel_files: list[str], expr: str) -> tuple[object | None, str]:
    """在 node 里 require 若干前端文件并执行 expr,返回 (结果, 原始输出)。"""
    if not NODE:
        return None, "node 不可用"
    reqs = "\n".join(f"const m{i} = require({(JS / f).as_posix()!r});"
                     for i, f in enumerate(rel_files))
    script = (f"{_NODE_STUB}\n{reqs}\n"
              f"const _out = (function(){{ {expr} }})();\n"
              f"console.log(JSON.stringify({{ok: true, v: _out}}));")
    try:
        p = subprocess.run([NODE, "-e", script], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=60, cwd=str(JS))
    except Exception as e:  # noqa: BLE001
        return None, f"{type(e).__name__}: {e}"
    if p.returncode != 0:
        return None, (p.stderr or p.stdout or "")[:400]
    try:
        return json.loads(p.stdout.strip())["v"], p.stdout.strip()
    except Exception as e:  # noqa: BLE001
        return None, f"解析失败 {type(e).__name__}: {p.stdout[:200]}"


# ==================== ① 壳层接线 ====================
def test_shell_wiring() -> None:
    ids = set(re.findall(r'\bid="([^"]+)"', HTML))
    # ① 左右两栏都在
    for i in ("shell", "conv-sidebar", "stage"):
        check(i in ids, f"P5 壳层容器 #{i} 在 DOM 里", "")
    # ② 六个入口(验收标准第 1 条)
    navs = re.findall(r'<li class="nav-item"[^>]*data-page="([a-z]+)"', HTML)
    check(len(navs) == 7, "P5 左栏是 7 个入口", f"got={navs}")
    for pg in ("chat", "kb", "personas", "weekly", "records", "minutes"):
        check(pg in navs, f"P5 入口 {pg} 存在", f"navs={navs}")
    # ③ 每个入口都指向一个**真实存在**的页面(拼错 = 点了之后主区空白,且不报错)
    pages = set(re.findall(r'<div class="tabpane page" id="pane-([a-z]+)"', HTML))
    check(len(pages) == 6, "P5 主区有 6 个整页", f"got={sorted(pages)}")
    for href in set(re.findall(r'href="#/([a-z]+)"', HTML)):
        check(href in pages, f"P5 hash 入口 #/{href} 指向真实页面(拼错=静默空白)",
              f"pages={sorted(pages)}")
    # ④ hash 路由:链接用 href 而不是 onclick 手改哈希(否则前进/后退不生效)
    check(HTML.count('href="#/') >= 5, "P5 入口走真实 hash 链接(前进/后退原生可用)",
          f"n={HTML.count('href=\"#/')}")
    check("addEventListener('hashchange'" in JS_FILES["shell.js"],
          "P5 hashchange 驱动切换(刷新/前进后退都落到同一处)", "")
    # ⑤ 学生不该看到的三个入口标了 data-staff(不是靠 CSS 藏,是渲染时整条不渲染)
    for pg in ("weekly", "records", "minutes"):
        check(f'data-page="{pg}" data-staff="1"' in HTML,
              f"P5 {pg} 入口标了 data-staff(按角色整条隐藏)", "")
    # ⑥ 账户入口仍在左栏内(P4f 的约定不回退)
    aside = re.search(r'<aside id="conv-sidebar">(.*?)</aside>', HTML, re.S)
    check(bool(aside) and "acct-entry" in (aside.group(1) if aside else ""),
          "P5 账户入口仍在左栏内(不是 body 级浮层)", "")
    # ⑦ 新增样式文件被引用且真实存在(漏引 = 页面裸奔且不报错)
    for c in re.findall(r'<link rel="stylesheet" href="/css/([^"]+)">', HTML):
        check((CSS / c).is_file(), f"P5 样式 /css/{c} 真实存在", f"path={CSS / c}")
    for c in ("shell.css", "persona-page.css"):
        check(f'/css/{c}' in HTML, f"P5 新增样式 {c} 已被引用", "")
    # ⑧ 脚本按依赖顺序加载(avatars 必须在 persona 之前:编辑弹窗要用 AVATAR_IDS)
    srcs = re.findall(r'<script src="/js/([^"]+)"></script>', HTML)
    for s in ("avatars.js", "shell.js", "persona-page.js"):
        check(s in srcs, f"P5 脚本 {s} 已加载", f"srcs={srcs}")
    if "avatars.js" in srcs and "persona.js" in srcs:
        check(srcs.index("avatars.js") < srcs.index("persona.js"),
              "P5 avatars.js 早于 persona.js(头像库先就绪)", f"srcs={srcs}")
    # ⑨ theme.css 的设计令牌**没被改**(P5 §5 硬要求)
    theme = (CSS / "theme.css").read_text(encoding="utf-8")
    check(":root" in theme and "--cinnabar:" in theme.replace(" ", ""),
          "P5 theme.css 设计令牌仍在(本单只新增文件,不改它)", "")
    # ⑩ 旧壳的右侧抽屉已下线(两套布局并存会互相盖住)
    check('id="side"' not in HTML and 'id="tabs"' not in HTML,
          "P5 旧右侧抽屉(#side/#tabs)已下线(两套布局并存会互相盖住)", "")


# ==================== ② 路由纯函数(node 实跑) ====================
def test_routing_pure() -> None:
    if not NODE:
        check(False, "P5 前置:node 可用(否则纯函数无法真跑)", "node 不在 PATH,无法执行前端纯函数")
        return
    v, raw = node_json(["shell.js"], """
      return {
        student: m0.visiblePageIds('student'),
        counselor: m0.visiblePageIds('counselor'),
        admin: m0.visiblePageIds('admin'),
        unknown: m0.visiblePageIds('whoami'),
        h_kb: m0.hashToPage('#/kb'),
        h_personas: m0.hashToPage('#/personas'),
        h_bogus: m0.hashToPage('#/bogus'),
        h_empty: m0.hashToPage(''),
        h_junk: m0.hashToPage('kb'),
        def: m0.DEFAULT_PAGE,
      };
    """)
    if v is None:
        check(False, "P5 node 跑 shell.js 成功", f"stderr={raw}")
        return
    check(v["student"] == ["chat", "kb", "personas"],
          "P5 学生可见入口 = 会话/知识库/辅导员(周报、工作记录与会议纪要**不可见**)",
          f"got={v['student']}")
    for role in ("counselor", "admin"):
        check(v[role] == ["chat", "kb", "personas", "weekly", "records", "minutes"],
              f"P5 {role} 可见全部 6 个入口", f"got={v[role]}")
    check(v["unknown"] == ["chat", "kb", "personas"],
          "P5 未知角色**按最小权限**渲染(不因为拿不到角色就全给)", f"got={v['unknown']}")
    check(v["h_kb"] == "kb" and v["h_personas"] == "personas",
          "P5 hash 解析正确(#/kb → kb)", f"got={v['h_kb']}/{v['h_personas']}")
    check(v["h_bogus"] == v["def"] and v["h_empty"] == v["def"] and v["h_junk"] == v["def"],
          "P5 未知/空 hash 回落到默认页(不留空主区)",
          f"got={v['h_bogus']}/{v['h_empty']}/{v['h_junk']} def={v['def']}")
    check("hashToPage(location.hash)" in JS_FILES["ui.js"],
          "P5 刷新后按 URL hash 复原页面(不是每次都回会话页)", "")
    check("switchPage(hashToPage(location.hash))" in JS_FILES["ui.js"],
          "P5 enter() 里真的用 hash 决定落点", "")


# ==================== ③ 头像库(node 实跑 + 契约) ====================
def test_avatar_library() -> None:
    if not NODE:
        check(False, "P5 前置:node 可用(头像库纯函数无法真跑)", "node 不在 PATH")
        return
    v, raw = node_json(["avatars.js"], """
      return {
        n: m0.AVATAR_IDS.length,
        uniq: new Set(m0.AVATAR_IDS).size,
        ids: m0.AVATAR_IDS,
        def: m0.AVATAR_DEFAULT_ID,
        ok7: m0.avatarId('av-07'),
        bogus: m0.avatarId('av-99'),
        empty: m0.avatarId(''),
        nul: m0.avatarId(null),
        undef: m0.avatarId(undefined),
        dirty: m0.avatarId('<script>'),
        syms: (m0.avatarSpriteMarkup().match(/<symbol /g) || []).length,
        total: m0.avatarSpriteMarkup().length,
        per: m0.AVATAR_SPECS.map(s => m0.avatarSymbol(s).length),
        sprite: m0.avatarSpriteMarkup(),
      };
    """)
    if v is None:
        check(False, "P5 node 跑 avatars.js 成功", f"stderr={raw}")
        return
    # ① 数量与唯一性(验收标准第 4 条:16 个 id 全部可选可存可渲染)
    check(v["n"] == 16, "P5 头像库 16 个", f"n={v['n']}")
    check(v["uniq"] == 16, "P5 头像 id 无重复(重复会让两个选项渲染成同一个)",
          f"uniq={v['uniq']}")
    check(all(re.fullmatch(r"av-\d{2}", i) for i in v["ids"]),
          "P5 头像 id 形如 av-NN(逻辑 id,不含路径/后缀)", f"ids={v['ids'][:3]}…")
    # ② 未知 id 回落**不报错**(前向兼容:将来加第 17 个,老前端照样渲染)
    check(v["ok7"] == "av-07", "P5 已知 id 原样返回", f"got={v['ok7']}")
    for k in ("bogus", "empty", "nul", "undef", "dirty"):
        check(v[k] == v["def"], f"P5 未知/脏 id({k})回落到默认头像且不抛错",
              f"got={v[k]} def={v['def']}")
    # ③ 尺寸红线(P5 §3.5:单个 ≤2KB、总增量 ≤40KB)
    check(max(v["per"]) <= 2048, "P5 单个头像 ≤2KB", f"max={max(v['per'])}")
    check(v["total"] <= 40960, "P5 头像库总增量 ≤40KB", f"total={v['total']}")
    # ④ 零外部依赖:除 XML 命名空间外,不得出现任何 http(s) 地址
    #    (命名空间 `xmlns="http://www.w3.org/2000/svg"` 是**声明**不是取数,不算外链;
    #     第一版把它当成外链判红了 —— 尺子自身的假红,改判据而不是改实现)
    urls = re.findall(r'https?://[^\s"\'<>]+', v["sprite"])
    ns = {"http://www.w3.org/2000/svg", "http://www.w3.org/1999/xlink"}
    bad = [u for u in urls if u not in ns]
    check(not bad, "P5 头像 SVG 内无 http(s) 外链(零外部依赖,命名空间除外)", f"bad={bad}")
    check("<image" not in v["sprite"], "P5 头像不用 <image>(不引外部位图)", "")
    # ⑤ 雪碧图符号数与 id 数一致
    check(v["syms"] == 16, "P5 雪碧图里 16 个 <symbol>", f"syms={v['syms']}")
    for i in v["ids"]:
        check(f'id="{i}"' in v["sprite"], f"P5 符号 {i} 在雪碧图里(缺一个 = <use> 破图)", "")
    # ⑥ 前端渲染走 id → <use>,不拼路径
    check("avatarSvg(" in JS_FILES["persona-page.js"] or "avatarSvg(" in JS_FILES["persona.js"],
          "P5 卡片/编辑都用 avatarSvg() 渲染(不手拼 <img src>)", "")
    check("<use href=\"#${avatarId(id)}\"/>" in JS_FILES["avatars.js"],
          "P5 渲染走 <use href=#id>(换画风不用迁数据)", "")


# ==================== ④ 历史对话分组(node 实跑) ====================
def test_history_grouping() -> None:
    if not NODE:
        check(False, "P5 前置:node 可用(分组纯函数无法真跑)", "node 不在 PATH")
        return
    expr = """
      const D = 86400000;
      const now = Date.parse('2026-10-02T12:00:00+00:00');
      const t0 = Math.floor(now / D) * D;                       // UTC 当日零点
      const iso = ms => new Date(ms).toISOString();
      const mk = (id, ms) => ({ id, title: 't' + id, updated_at: iso(ms) });
      const one = m0.groupConversations([mk(1, t0 + 3600000)], now);
      const week = m0.groupConversations([mk(2, t0 - 6 * D)], now);
      const earlier = m0.groupConversations([mk(3, t0 - 8 * D)], now);
      const edge = m0.groupConversations([mk(4, t0), mk(5, t0 - 1)], now);
      const weekEdge = m0.groupConversations([mk(6, t0 - 7 * D), mk(7, t0 - 7 * D - 1)], now);
      const bad = m0.groupConversations([{ id: 9, title: 'x' }], now);
      const empty = m0.groupConversations([], now);
      const all = m0.groupConversations([mk(1, t0), mk(2, t0 - 3 * D), mk(3, t0 - 30 * D)], now);
      return { one: Object.keys(one).map(k => [k, one[k].length]),
               week, earlier, edge, weekEdge, bad, empty,
               total: all.today.length + all.week.length + all.earlier.length };
    """
    v, raw = node_json(["conversations.js"], expr)
    if v is None:
        check(False, "P5 node 跑 conversations.js 成功", f"stderr={raw}")
        return
    check(v["one"][0][1] == 1 and [x for x in v["one"] if x[1]][0][0] == "today",
          "P5 今天的会话分到「今天」", f"got={v['one']}")
    check(len(v["week"]["week"]) == 1 and len(v["week"]["today"]) == 0,
          "P5 6 天前的会话分到「近 7 天」", f"got={ {k: len(x) for k, x in v['week'].items()} }")
    check(len(v["earlier"]["earlier"]) == 1,
          "P5 8 天前的会话分到「更早」", f"got={ {k: len(x) for k, x in v['earlier'].items()} }")
    # 边界:零点整点归 today,零点前 1ms 归 week(差一天的错误最难发现)
    check(len(v["edge"]["today"]) == 1 and len(v["edge"]["week"]) == 1,
          "P5 边界:当日零点整点归今天、前 1ms 归近 7 天",
          f"today={len(v['edge']['today'])} week={len(v['edge']['week'])}")
    check(len(v["weekEdge"]["week"]) == 1 and len(v["weekEdge"]["earlier"]) == 1,
          "P5 边界:7 天前整点仍在近 7 天、再早 1ms 归更早",
          f"week={len(v['weekEdge']['week'])} earlier={len(v['weekEdge']['earlier'])}")
    # 解析不出的时间**不能丢**(丢了就是列表里少一条,用户以为会话没了)
    check(len(v["bad"]["earlier"]) == 1,
          "P5 时间解析失败的会话归到「更早」而不是被丢掉", f"got={v['bad']}")
    check(v["total"] == 3, "P5 分组不丢项(三组之和 == 入参条数)", f"total={v['total']}")
    check(all(len(x) == 0 for x in v["empty"].values()),
          "P5 空列表 → 三组皆空(不炸、不产生幽灵条目)", f"got={v['empty']}")
    # 判据必须是服务端时间,不是浏览器本地时区
    check("window._serverNowMs" in JS_FILES["api.js"],
          "P5 「现在」取自服务端(Date 响应头),不用浏览器本地时区", "")
    check("function serverNowMs(" in JS_FILES["conversations.js"],
          "P5 分组用 serverNowMs() 而不是 Date.now()", "")


# ==================== ⑤ 后端:avatar 列迁移(库副本,零写入) ====================
def test_avatar_migration() -> None:
    from novaagent import config, db as db_mod

    src = config.DB_PATH
    tmp = Path(tempfile.mkdtemp(prefix="p5_mig_"))
    saved_conn = db_mod._conn
    try:
        # ⚠ **自测自身的假绿**(第一版踩到,留档):
        #   复制的是**当前**库,而它很可能已经被迁移过(开发时跑过一次 connect)。
        #   那样 `avatar` 列本来就在 → 「列存在」恒绿 → **加列逻辑根本没被执行就被判通过**
        #   (坑 45 的镜像:断言绿了,被测的东西没被测到)。
        #   所以每一步都先把列**删掉**,造出一个「旧库」再跑迁移。
        snaps = []
        for i in (1, 2):
            dst = tmp / f"agent{i}.db"
            shutil.copy2(src, dst)
            con = sqlite3.connect(str(dst))
            cols0 = [r[1] for r in con.execute("PRAGMA table_info(personas)")]
            if "avatar" in cols0:
                con.execute("ALTER TABLE personas DROP COLUMN avatar")   # 造旧库
                con.commit()
            con.close()
            config.DB_PATH = dst
            db_mod._conn = None
            db_mod.connect()          # 触发建表 + _migrate()
            con = sqlite3.connect(str(dst))
            cols = [r[1] for r in con.execute("PRAGMA table_info(personas)")]
            docs = con.execute("select count(*) from documents").fetchone()[0]
            chunks = con.execute("select count(*) from chunks").fetchone()[0]
            pers = con.execute("select count(*) from personas").fetchone()[0]
            con.close()
            snaps.append((tuple(cols), docs, chunks, pers))
            check("avatar" in cols, f"P5 迁移第{i}遍:personas.avatar 列存在", f"n_cols={len(cols)}")
        check(snaps[0] == snaps[1],
              "P5 迁移幂等:连跑两遍 schema 与计数完全一致",
              f"1st={snaps[0][1:]} 2nd={snaps[1][1:]}")
        check(snaps[0][1] > 0 and snaps[0][2] > 0,
              "P5 自测非空前置:副本里有真实语料(防空集假通过)",
              f"docs={snaps[0][1]} chunks={snaps[0][2]}")
        # 迁移不得动 personas 已有数据
        check(snaps[0][3] == snaps[1][3],
              "P5 加列不动既有 personas 行数", f"n={snaps[0][3]}")
    finally:
        db_mod._conn = None
        config.DB_PATH = src
        db_mod.connect()
        if saved_conn is not None:
            db_mod._conn = saved_conn
        shutil.rmtree(tmp, ignore_errors=True)


# ==================== ⑥ 后端:avatar 读写 + RBAC(库副本) ====================
def test_avatar_rw_and_rbac() -> None:
    from fastapi import HTTPException

    from novaagent import config, db as db_mod
    from novaagent import main as main_mod

    src = config.DB_PATH
    tmp = Path(tempfile.mkdtemp(prefix="p5_rw_"))
    dst = tmp / "agent.db"
    saved_conn = db_mod._conn
    try:
        shutil.copy2(src, dst)
        config.DB_PATH = dst
        db_mod._conn = None
        db_mod.connect()
        con = sqlite3.connect(str(dst))
        cid = con.execute("select id from users where username='counselor'").fetchone()[0]
        sid = con.execute("select id from users where username='student'").fetchone()[0]
        n0 = con.execute("select count(*) from personas").fetchone()[0]
        con.close()
        counselor = {"id": cid, "username": "counselor", "role": "counselor"}
        student = {"id": sid, "username": "student", "role": "student"}
        check(n0 >= 0, "P5 非空前置:读到 users 与 personas 基线", f"personas={n0}")

        # ---- ① avatar 纯净函数 ----
        cases = [("", ""), (None, ""), ("av-01", "av-01"), ("  av-02  ", "av-02"),
                 ("<script>", "script"), ("../../etc/passwd", "etcpasswd"),
                 ("a" * 40, "a" * 32)]
        for raw, want in cases:
            got = db_mod.normalize_avatar(raw)
            check(got == want, f"P5 normalize_avatar({raw!r}) = {want!r}(清洗,不存脏值)",
                  f"got={got!r}")

        # ---- ② 创建 → 读回 → 改 ----
        pid = db_mod.create_persona(cid, "P5头像自测", college="信息学院", avatar="av-07")
        check(db_mod.get_persona(pid, cid, "counselor")["avatar"] == "av-07",
              "P5 新建人设的 avatar 原样存回(存的是 id 不是路径)", "")
        db_mod.update_persona(pid, cid, "counselor", {"avatar": "av-12"})
        check(db_mod.get_persona(pid, cid, "counselor")["avatar"] == "av-12",
              "P5 改头像生效", "")
        # 前向兼容:未知 id 必须能存进去(前端回落成默认头像,不是 500)
        db_mod.update_persona(pid, cid, "counselor", {"avatar": "av-99-future"})
        check(db_mod.get_persona(pid, cid, "counselor")["avatar"] == "av-99-future",
              "P5 未知 avatar id **存得进**(前向兼容:将来加新头像不用改库)", "")

        # ---- ③ RBAC:绕过 UI **直接打接口**(验收标准第 5 条) ----
        #
        # ⚠ 第一版我图省事直接 `personas_create(body, user=student)` **直调函数**,
        #   那会绕过 FastAPI 的 Depends —— 结果它真的人设建成功了,我却只在断言
        #   「应该 403」:断言绿了,**被测的东西根本没被测到**(坑 45 的镜像形态:
        #   不是「假绿」,是「根本没测」)。
        #   现改用 TestClient 走**真实路由 + 依赖链**(不带 context manager → 不触发
        #   lifespan,也就不会去连 weekly MCP;db 已由本用例连到副本)。
        from fastapi.testclient import TestClient

        stok = db_mod.create_session(sid)
        ctok = db_mod.create_session(cid)
        cli = TestClient(main_mod.app)
        r1 = cli.post("/api/personas", json={"name": "学生偷偷建"},
                      headers={"Authorization": f"Bearer {stok}"})
        check(r1.status_code == 403,
              "P5 学生 token 直接 POST /api/personas → 403(前端隐藏只是体验层)",
              f"got={r1.status_code} body={r1.text[:80]}")
        r1b = cli.post("/api/personas", json={"name": "辅导员正常建"},
                       headers={"Authorization": f"Bearer {ctok}"})
        check(r1b.status_code == 200,
              "P5 对照:辅导员 token 建人设 200(证明上一条的红不是接口整体坏了)",
              f"got={r1b.status_code} body={r1b.text[:80]}")
        created = r1b.json().get("persona", {}).get("id") if r1b.status_code == 200 else None
        check(bool(created) and r1b.json()["persona"].get("avatar") == "",
              "P5 新建人设默认 avatar=''(前端按 id 回落默认头像)",
              f"avatar={r1b.json().get('persona', {}).get('avatar')!r}")
        # 学生**读**得到 public 人设(只读位成立),但写一律 403
        r1c = cli.get("/api/personas", headers={"Authorization": f"Bearer {stok}"})
        check(r1c.status_code == 200, "P5 学生可以**读**人设列表(只读位不是不可见)",
              f"got={r1c.status_code}")
        r1d = cli.delete("/api/personas/1", headers={"Authorization": f"Bearer {stok}"})
        check(r1d.status_code == 403, "P5 学生 DELETE 人设 → 403", f"got={r1d.status_code}")

        # 别人的 public 人设:counselor 改 → 404 且与「不存在」**同文案**(防存在性泄露)
        other = db_mod.create_persona(sid, "学生的人设", visibility="public")
        r2 = cli.patch(f"/api/personas/{other}", json={"name": "x"},
                       headers={"Authorization": f"Bearer {ctok}"})
        r3 = cli.patch("/api/personas/999999", json={"name": "x"},
                       headers={"Authorization": f"Bearer {ctok}"})
        check(r2.status_code == 404,
              "P5 改别人的 public 人设 → 404(不是 200 也不是 403)", f"got={r2.status_code}")
        m2 = r2.json().get("detail") if r2.headers.get("content-type", "").startswith("application/json") else r2.text
        m3 = r3.json().get("detail") if r3.headers.get("content-type", "").startswith("application/json") else r3.text
        check(m2 == m3 and str(m2) != "",
              "P5 「改别人的」与「不存在」**同文案**(不泄露存在性)", f"{m2!r} vs {m3!r}")
        # ---- ④ 投影:非作者拿不到 persona_prompt,但 avatar 要给(卡片要渲染) ----
        proj = db_mod.project_persona_for_response(
            db_mod.get_persona(other, cid, "counselor"), cid, "counselor")
        check("avatar" in proj, "P5 投影后仍带 avatar 键(卡片要渲染头像)", f"keys={sorted(proj)[:6]}…")
        check(proj.get("persona_prompt") == "",
              "P5 非作者的 persona_prompt 仍被投影成空串(P4f 脱敏不退步)", "")

        con = sqlite3.connect(str(dst))
        n1 = con.execute("select count(*) from personas").fetchone()[0]
        d1 = con.execute("select count(*) from documents").fetchone()[0]
        c1 = con.execute("select count(*) from chunks").fetchone()[0]
        con.close()
        check(d1 > 0 and c1 > 0, "P5 自测未破坏语料(写库测试自查,坑 72)",
              f"docs={d1} chunks={c1}")
        # 本用例在副本上建了 3 条:db.create_persona ×2(头像自测 / 学生的人设)
        # + TestClient 里辅导员 POST 的 1 条(对照组)。**多一条少一条都算异常** ——
        # 多出来的说明有路径在偷偷写库,少了说明某条路径其实没真跑。
        check(n1 == n0 + 3, "P5 本用例只增了自造的 3 条 personas(副本上)", f"{n0}→{n1}")
    finally:
        db_mod._conn = None
        config.DB_PATH = src
        db_mod.connect()
        if saved_conn is not None:
            db_mod._conn = saved_conn
        shutil.rmtree(tmp, ignore_errors=True)


# ============ ⑤ 真执行 enter():第 2 回②(本轮阻塞项的守门人) ============
DOM_STUB = Path(__file__).resolve().parent / "p5_dom_stub.js"


def run_enter(role: str, page: str = "") -> tuple[dict | None, str]:
    """用 DOM 桩在 node 里**真调一次 enter()**,返回 (读数, 原始输出)。

    ⚠ 桩的 id 是从 index.html **真解析**的,`getElementById` 找不到就返回 null ——
    与浏览器一致。所以「JS 引用了已删除的元素」在这里会真抛 TypeError。
    桩若什么都返回对象,本文件就成了自欺(坑 71)。
    """
    if not NODE:
        return None, "node 不可用"
    if not DOM_STUB.is_file():
        return None, f"DOM 桩缺失: {DOM_STUB}"
    env = dict(os.environ)
    env["P5_PAGE"] = page          # 页面 id 走 env:Git Bash 会把 `#/kb` 里的 `/kb` 当路径转换(见桩内注释)
    try:
        p = subprocess.run([NODE, str(DOM_STUB), str(WEB), role],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=60, cwd=str(ROOT), env=env)
    except Exception as e:  # noqa: BLE001
        return None, f"{type(e).__name__}: {e}"
    raw = (p.stdout or p.stderr or "").strip()
    if p.returncode != 0:
        return None, f"exit={p.returncode} {raw[:400]}"
    try:
        return json.loads(raw)["v"], raw
    except Exception as e:  # noqa: BLE001
        return None, f"解析失败 {type(e).__name__}: {raw[:300]}"


def test_enter_boots() -> None:
    """开单第 2 回②:109 条全绿而真页面半瘫 —— 因为没有一条真的调 `enter()`。

    这里覆盖开单列的四条(counselor / student 各跑一次),外加两条我自己加的:
    hash 回位(验收标准第 2 条)与学生越权手敲回落。
    """
    if not NODE:
        check(False, "P5 前置:node 可用(否则 enter() 无法真执行)", "node 不在 PATH")
        return

    read = {}
    for role in ("counselor", "student"):
        v, raw = run_enter(role)
        read[role] = v
        check(v is not None, f"P5 enter() 在 role={role} 下真跑成功", raw[:300])
        if v is None:
            continue
        # ① 不抛错(本轮缺陷的原始症状就是这里)
        check(v["threw"] is None, f"P5 enter() role={role} 不抛错", f"threw={v['threw']}")
        check(v["loadErrors"] == [], f"P5 enter() role={role} 加载全部 js 无顶层报错",
              f"loadErrors={v['loadErrors']}")
        # 非空前置:桩真的把 enter() 跑到底了(不是脚本加载完就返回)
        check(v["scripts"] and len(v["scripts"]) >= 10,
              f"P5 桩按 index.html 顺序加载了全部 js(role={role})", f"n={len(v['scripts'])}")
        # ② 历史列表有真实条目,不是占位「—」(开单第 2 条)
        check(v["convListItems"] > 0 and v["convListPlaceholder"] is False,
              f"P5 enter() 后 #conv-list 有真实条目(role={role},非占位)",
              f"items={v['convListItems']} placeholder={v['convListPlaceholder']}")
        check(v["convCount"] == "3",
              f"P5 #conv-count 显示真实条数(role={role})", f"got={v['convCount']!r}")
        # ③ 学生侧周报/工作记录/会议纪要三条入口 hidden
        if role == "student":
            check(v["navHidden"] == ["weekly", "records", "minutes"],
                  "P5 学生侧 #nav-entries 的 weekly/records/minutes 入口被隐藏", f"hidden={v['navHidden']}")
            check("weekly" not in v["navVisible"] and "records" not in v["navVisible"]
                  and "minutes" not in v["navVisible"],
                  "P5 学生侧可见入口不含周报/工作记录/会议纪要", f"visible={v['navVisible']}")
            check(v["personasNewDisplay"] == "none",
                  "P5 学生侧「新建人设」按钮隐藏", f"got={v['personasNewDisplay']!r}")
        else:
            check(v["navHidden"] == [],
                  "P5 辅导员侧 7 个入口全部可见", f"hidden={v['navHidden']}")
            check(v["personasNewDisplay"] == "" and v["uploadRowDisplay"] == "flex",
                  "P5 辅导员侧显示新建人设/上传行", f"{v['personasNewDisplay']!r}/{v['uploadRowDisplay']!r}")
        # ④ 账户卡
        expect_name = "student01" if role == "student" else "counselor01"
        check(v["acctName"] == expect_name,
              f"P5 #acct-name === ME.username(role={role})", f"got={v['acctName']!r}")
        check(v["acctRole"] == ("学生" if role == "student" else "辅导员"),
              f"P5 #acct-role 角色中文化正确(role={role})", f"got={v['acctRole']!r}")
        check(v["maskDisplay"] == "none",
              f"P5 登录遮罩已关闭(role={role})", f"got={v['maskDisplay']!r}")
        check(v["messagesChildren"] >= 1,
              f"P5 欢迎气泡已进消息区(role={role})", f"n={v['messagesChildren']}")
        check("persona-select" in v["personaBarHtml"],
              f"P5 人设选择器已渲染(role={role})", f"len={len(v['personaBarHtml'])}")

    # ⑤ hash 回位(验收标准第 2 条:刷新回同一页)——桩里 hash 是启动时就带上的
    for page in ("kb", "weekly", "personas"):
        v, raw = run_enter("counselor", page)
        check(v is not None, f"P5 enter() 带 hash=#/{page} 真跑成功", raw[:300])
        if v:
            check(v["threw"] is None and v["page"] == page and v["activePane"] is True,
                  f"P5 带 #/{page} 刷新回位到该页且 pane 激活",
                  f"threw={v['threw']} page={v['page']} active={v['activePane']}")
    v, raw = run_enter("counselor", "nope")
    check(v is not None, "P5 enter() 带未知 hash 真跑成功", raw[:300])
    if v:
        check(v["page"] == "chat",
              "P5 未知 hash(#/nope)回落到会话页而不是空白主区", f"page={v['page']}")
    # ⑥ 学生手敲越权 hash → 回落会话页(前端体验层;后端 403 是另一层,P5 真机已验)
    for page in ("weekly", "records"):
        v, raw = run_enter("student", page)
        check(v is not None, f"P5 学生带 hash=#/{page} 真跑成功", raw[:300])
        if v:
            check(v["page"] == "chat",
                  f"P5 学生手敲 #/{page} 被挡回会话页", f"page={v['page']}")


def main() -> int:
    for fn in (test_shell_wiring, test_routing_pure, test_avatar_library,
               test_history_grouping, test_enter_boots, test_avatar_migration,
               test_avatar_rw_and_rbac):
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
        if not name:
            continue
        lines.append(f"[{'PASS' if ok else 'FAIL'}] {name}")
        if not ok and detail:
            lines.append(f"        detail: {detail}")
    lines.append("=" * 78)
    lines.append(f"[RESULT] {npass}/{total} passed")
    body = "\n".join(lines)
    print(body)
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    (EVIDENCE / "p5_selftest_output.txt").write_text(body + "\n", encoding="utf-8")
    print(f"[evidence] {EVIDENCE / 'p5_selftest_output.txt'}")
    return 0 if npass == total else 1


if __name__ == "__main__":
    sys.exit(main())
