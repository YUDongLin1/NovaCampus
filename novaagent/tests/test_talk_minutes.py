#!/usr/bin/env python
"""谈心谈话(姓名/摘要/按月导出) + 会议纪要(整理/防虚构/导出) 的离线自测。

零额度:全程不发 LLM/embedding/ASR 请求 —— 模型输出用**固定样本**喂进纯函数层,
真机联调不在本文件范围内(见各函数 docstring 的「未经真机联调」标注)。

跑法:
    novaagent/.venv/Scripts/python.exe tests/test_talk_minutes.py
退出码:0 = 全过;1 = 有红。
"""
from __future__ import annotations

import ast
import importlib.util
import io
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
NOVA = HERE.parent
ROOT = NOVA.parent
sys.path.insert(0, str(NOVA))

RESULTS: list[tuple[bool, str, str]] = []


def check(cond, label, detail=""):
    RESULTS.append((bool(cond), label, "" if cond else str(detail)))
    print(f"[{'PASS' if cond else 'FAIL'}] {label}" + ("" if cond else f"  → {detail}"))


# ==================================================== 1. talk_summary(纯函数)

from novaagent import talk_summary as ts  # noqa: E402

check(ts.build_summary("职业规划") == "就该学生职业规划情况进行谈心谈话",
      "摘要句式 == 规格例句(职业规划)", ts.build_summary("职业规划"))
check(ts.build_summary("学业") == "就该学生学业情况进行谈心谈话",
      "摘要句式 == 规格例句(学业)", ts.build_summary("学业"))
for topic in ts.TALK_TOPICS:
    s = ts.build_summary(topic)
    check(s.startswith("就该学生") and s.endswith("进行谈心谈话") and "情况情况" not in s,
          f"句式恒等且无「情况情况」: {topic}", s)
check(ts.normalize_topic("学业情况") == "学业", "带尾缀「学业情况」归一到枚举项", ts.normalize_topic("学业情况"))
check(ts.normalize_topic('主题:"心理健康"') == "心理健康", "带前缀与引号仍能归一", ts.normalize_topic('主题:"心理健康"'))
check(ts.normalize_topic("1. 人际关系") == "人际关系", "带编号仍能归一", ts.normalize_topic("1. 人际关系"))
check(ts.normalize_topic("就业规划") == "职业规划", "近义词走显式别名表", ts.normalize_topic("就业规划"))
for junk in ["", None, "   ", "学业与心理", "学业、心理", "考研", "完全不相关的一句话", 123]:
    check(ts.normalize_topic(junk) is None, f"判不清就返回 None(不猜): {junk!r}", ts.normalize_topic(junk))
check(ts.normalize_topic("其他") == "其他" and "综合" in ts.build_summary("其他"),
      "「其他」不回落成别的主题,且句式写作综合情况", ts.build_summary("其他"))
check(ts.summary_or_placeholder("") == ts.PLACEHOLDER_SUMMARY
      and ts.name_or_placeholder("  ") == ts.PLACEHOLDER_NAME, "空值走占位串", "")
check("其他" in ts.TOPIC_PROMPT and "{content}" in ts.TOPIC_PROMPT,
      "提示词含全部枚举与内容占位符", "")

# ==================================================== 2. minutes(解析 + 防虚构 + 渲染)

from novaagent import minutes as mt  # noqa: E402

SRC = ("10月8日下午班委会,参加的人有张三、李四、王老师。讨论了助学金评定材料,需要补一张表。"
       "决定本周内公示名单。另外运动会报名由李四负责,10月15日前交。")

m_ok, u_ok = mt.guard({
    "title": "班委会", "meeting_time": "10月8日下午", "attendees": "张三、李四、王老师",
    "discussion": ["1.讨论助学金评定材料", "- 需补一张表"], "resolutions": ["本周内公示名单"],
    "todos": [{"item": "运动会报名", "owner": "李四", "due": "10月15日前"}],
}, SRC)
check(m_ok["meeting_time"] == "10月8日下午" and m_ok["attendees"] == "张三、李四、王老师",
      "如实整理时守卫不改内容", m_ok)
check(m_ok["discussion"] == ["讨论助学金评定材料", "需补一张表"],
      "条目自带的编号/项目符号被剥掉,不叠加", m_ok["discussion"])
check(m_ok["todos"][0]["owner"] == "李四" and m_ok["todos"][0]["due"] == "10月15日前",
      "原文说过的责任人与截止时间原样保留", m_ok["todos"])
check(u_ok == [], "全部可溯源时 untraced 为空", u_ok)

m_bad, u_bad = mt.guard({
    "title": "班委会", "meeting_time": "2027-12-31 09:00", "attendees": "张三、赵六",
    "discussion": ["讨论了评优"], "resolutions": ["决定发放5000元补助"],
    "todos": [{"item": "公示名单", "owner": "孙同学", "due": "下周五"}],
}, SRC)
check(m_bad["meeting_time"] == mt.MISSING, "守卫① 原文没有的时间 → 占位(不是照抄)", m_bad["meeting_time"])
check("赵六" not in m_bad["attendees"] and "张三" in m_bad["attendees"],
      "守卫② 原文没有的参会人剔除,原文有的保留", m_bad["attendees"])
check(m_bad["todos"][0]["owner"] == mt.MISSING and m_bad["todos"][0]["due"] == mt.MISSING,
      "守卫③ 凭空的责任人/截止时间 → 占位", m_bad["todos"])
check(any("会议时间" in x for x in u_bad) and any("参会人" in x for x in u_bad)
      and any("责任人" in x for x in u_bad), "每一项拦截都写进 untraced 供前端提示核对", u_bad)

m_empty, u_empty = mt.guard({"title": "", "meeting_time": "", "attendees": "",
                             "discussion": [], "resolutions": [], "todos": []}, SRC)
check(all(m_empty[k] == mt.MISSING for k in ("title", "meeting_time", "attendees")),
      "全空输入:三个字段都是占位串,不是空串", m_empty)
# 断言**集合**而不是条数:数一个整数就是手抄,字段增减时它会静默对不上
check({x.split("（")[0] for x in u_empty} == {"会议时间", "参会人员", "讨论要点", "决议事项", "待办任务"},
      "全空输入:五个缺失板块全部登记 untraced", u_empty)

check(mt._digit_runs("08日") == ["8"], "前导零归一(原文「8日」vs 模型「08」不算虚构)", mt._digit_runs("08日"))
check(mt.traceable("10月8日", mt._norm(SRC)) is True, "溯源:原文里有的日期判通过", "")
check(mt.traceable("2026年10月8日", mt._norm(SRC)) is False,
      "溯源:原文没写年份,模型补年份判不通过", "")

parsed = mt.parse_minutes_output('```json\n{"title":"T","discussion":"一行\n两行"}\n```')
check(parsed["title"] == "T" and parsed["discussion"] == ["一行", "两行"],
      "解析:代码围栏 + 换行文本形态都能吃", parsed)
check(mt.parse_minutes_output('{"title":["列表误填"]}')["title"] == "",
      "解析:字段形态不对时留空,不 str() 成 \"['列表误填']\"", mt.parse_minutes_output('{"title":["x"]}')["title"])
for bad in ["没有 JSON", "", "{括号不平衡"]:
    try:
        mt.parse_minutes_output(bad)
        check(False, f"解析:坏输入必须抛 ValueError({bad!r})", "没抛")
    except ValueError:
        check(True, f"解析:坏输入抛 ValueError({bad!r})")

md = mt.render_markdown(m_bad)
check(md.count(mt.MISSING) >= 3 and "待办任务" in md and "决议事项" in md,
      "Markdown 渲染:占位串出现在缺失字段上", md[:120])

docx = mt.render_docx(m_bad)
check(docx[:2] == b"PK" and len(docx) > 2000, "docx 是真 zip 容器且非空", (docx[:4], len(docx)))
zf = zipfile.ZipFile(io.BytesIO(docx))
body = zf.read("word/document.xml").decode("utf-8")
styles = zf.read("word/styles.xml").decode("utf-8")
for probe in ("班委会", mt.MISSING, "公示名单", "待办任务", "讨论要点", "决议事项", "参会人员"):
    check(probe in body, f"docx 正文含「{probe}」", "")
check('w:eastAsia="宋体"' in styles,
      "docx 显式设了中文字体(只设 font.name 时部分 Word 版本中文回退成方框)", "")

# ==================================================== 3. ASR 纯函数

from novaagent import asr  # noqa: E402

check(asr.check_audio("a.mp3", 1024) == ".mp3" and asr.check_audio("x.M4A", 1024) == ".m4a",
      "音频后缀校验大小写不敏感", "")
for name, size, why in (("a.txt", 10, "非音频"), ("a.mp3", 0, "空文件"),
                        ("a.mp3", 10 ** 9, "超上限")):
    try:
        asr.check_audio(name, size)
        check(False, f"音频校验必须拒绝({why}:{name})", "没拒")
    except asr.AsrError:
        check(True, f"音频校验拒绝({why}:{name})")
p1 = asr.parse_transcription({"transcripts": [{"sentences": [
    {"text": "第一句", "speaker_id": 0}, {"text": "第二句", "speaker_id": 1}]}]})
check(p1 == "[说话人1] 第一句\n[说话人2] 第二句", "转写结果按句成行并带说话人标记", repr(p1))
check(asr.parse_transcription({"transcripts": [{"text": "整篇"}]}) == "整篇",
      "没有逐句时回落 transcripts[].text", "")
check(asr.parse_transcription('{"text":"字符串 JSON"}') == "字符串 JSON",
      "响应是 JSON 文本时先解析", "")
for empty in ({}, {"transcripts": []}, [], {"transcripts": [{"sentences": []}]}):
    try:
        asr.parse_transcription(empty)
        check(False, f"取不到文本必须抛错(不返回空串假装成功): {empty!r}", "没抛")
    except asr.AsrError:
        check(True, f"取不到文本抛 AsrError: {empty!r}")
body1 = asr.build_task_body("oss://x/y.mp3")
check(body1["input"]["file_urls"] == ["oss://x/y.mp3"] and body1["parameters"] == {},
      "默认不开说话人分离(开了官方建议 ≤2h 且失败率上升)", body1)
check(asr.task_status({"task_status": "succeeded"}) == "SUCCEEDED", "任务状态大写归一", "")
check("asr_key_source" in asr.describe_config() and "asr_model" in asr.describe_config(),
      "health 读数暴露 ASR 配置但不含 key", asr.describe_config().keys())

# ==================================================== 4. 周报 MCP server(真实库副本上的迁移)

REAL_DB = ROOT / "data" / "weekly" / "weekly.db"
check(REAL_DB.is_file(), "自测前置:真实 weekly.db 存在(迁移守恒要在它上面验)", REAL_DB)


def load_server(data_dir: Path):
    os.environ["WEEKLY_DATA_DIR"] = str(data_dir)
    spec = importlib.util.spec_from_file_location("weekly_server_" + data_dir.name,
                                                  ROOT / "mcp" / "weekly" / "server.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


tmp = Path(tempfile.mkdtemp(prefix="weekly_mig_"))
try:
    shutil.copy(REAL_DB, tmp / "weekly.db")
    c0 = sqlite3.connect(tmp / "weekly.db")
    base_n = c0.execute("SELECT COUNT(*) FROM fragments").fetchone()[0]
    base_rows = list(c0.execute(
        "SELECT id,content,category,occurred_at,created_at,deleted FROM fragments ORDER BY id"))
    base_reports = c0.execute("SELECT COUNT(*) FROM reports").fetchone()[0]
    c0.close()
    check(base_n > 0, "自测前置:副本里有真实历史数据(防空集假通过,坑 33)", base_n)

    srv = load_server(tmp)
    c1 = sqlite3.connect(tmp / "weekly.db")
    n1 = c1.execute("SELECT COUNT(*) FROM fragments").fetchone()[0]
    rows1 = list(c1.execute("SELECT id,content,category,occurred_at,created_at,deleted FROM fragments ORDER BY id"))
    fcols = {r[1] for r in c1.execute("PRAGMA table_info(fragments)")}
    tabs = {r[0] for r in c1.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    backfilled = c1.execute("SELECT COUNT(*) FROM fragments WHERE student_name!='' OR summary!=''").fetchone()[0]
    reports1 = c1.execute("SELECT COUNT(*) FROM reports").fetchone()[0]
    c1.close()
    check(n1 == base_n and rows1 == base_rows,
          f"迁移守恒:碎片 {base_n}→{n1} 行内容逐字节一致", f"{base_n}→{n1}")
    check(reports1 == base_reports, f"归档周报 {base_reports} 篇不受迁移影响", reports1)
    check("student_name" in fcols and "summary" in fcols, "迁移加上了两列", sorted(fcols))
    check(backfilled == 0, "迁移**不回填**任何历史行(与仓库既有迁移纪律同源)", backfilled)
    check("minutes" in tabs, "会议纪要表已建", sorted(tabs))

    # 幂等:同一副本再起一次进程(第二、三遍不重复建、不重复加列)
    srv._conn.close()
    srv2 = load_server(tmp)
    c2 = sqlite3.connect(tmp / "weekly.db")
    check(c2.execute("SELECT COUNT(*) FROM fragments").fetchone()[0] == base_n
          and len(list(c2.execute("PRAGMA table_info(fragments)"))) == len(fcols),
          "迁移幂等:第二遍条数与列数分毫不动", "")
    c2.close()
    srv2._conn.close()

    srv3 = load_server(tmp)
    j = lambda r: json.loads(r)  # noqa: E731

    # 谈心谈话全链路:存 → 导出整句
    a = j(srv3.add_fragment("1.了解复习进度;2.建议定月计划。", "谈心谈话", "2026-10-08",
                            "张三", "就该学生学业情况进行谈心谈话"))
    check(a["ok"], "add_fragment 带姓名与摘要可存", a)
    ex = j(srv3.export_talk_records("2026-10"))
    check(ex["ok"] and ex["rows"] == ["2026年10月8日与张三就该学生学业情况进行谈心谈话"],
          "按月导出:日期汉字化 + 与姓名 + 摘要拼成台账整句", ex["rows"])
    hist = j(srv3.export_talk_records("2026-09"))
    check(hist["ok"] and hist["count"] > 0
          and all(ts.PLACEHOLDER_NAME in r and ts.PLACEHOLDER_SUMMARY in r for r in hist["rows"]),
          "历史月导出:缺姓名/摘要写占位,不跳过该行、不伪造", hist["rows"][:1])
    for bad_month in ("2026-13", "202609", "", "abc-de"):
        check(j(srv3.export_talk_records(bad_month))["ok"] is False,
              f"非法 month 被拒: {bad_month!r}", "")
    check(j(srv3.export_talk_records("2026-09"))["ok"], "合法 YYYY-MM 通过", "")

    # 空串 = 不改(与「清空」区分开)
    b = j(srv3.add_fragment("只谈了就业", "谈心谈话", "2026-10-09"))
    check(j(srv3.update_fragment(b["fragment_id"], "李四"))["ok"], "补录姓名成功", "")
    row = next(r for r in j(srv3.export_talk_records("2026-10"))["rows"] if "10月9日" in r)
    check("李四" in row and ts.PLACEHOLDER_SUMMARY in row,
          "补录生效且摘要仍是占位(空串没被当成要改的值)", row)
    check(j(srv3.update_fragment(b["fragment_id"]))["ok"] is False, "什么都不传 → 拒绝而不是静默成功", "")
    check(j(srv3.update_fragment(999999, "王五"))["ok"] is False, "改不存在的记录被拒", "")

    # 纪要存取
    mid = j(srv3.add_minutes("班委会", "10月8日下午", "张三", "讨论助学金", "公示名单",
                             json.dumps([{"item": "交报名", "owner": "李四", "due": "10月15日"}],
                                        ensure_ascii=False), "原始零碎内容", "audio", "班会.m4a"))["minutes_id"]
    g = j(srv3.get_minutes(mid))
    check(g["ok"] and g["todos"] == [{"item": "交报名", "owner": "李四", "due": "10月15日"}],
          "纪要待办按数组取得出(库里是 JSON 文本)", g["todos"])
    check(g["raw_content"] == "原始零碎内容" and g["source_type"] == "audio",
          "纪要保留原始内容与来源类型(回看对照用)", (g["raw_content"], g["source_type"]))
    j(srv3.update_minutes(mid, "改过的主题", "", "", "A", "B", "[]"))
    g2 = j(srv3.get_minutes(mid))
    check(g2["title"] == "改过的主题" and g2["raw_content"] == "原始零碎内容" and g2["todos"] == [],
          "在线编辑整条覆盖六个字段,但**不动**原始内容", g2)
    check(j(srv3.add_minutes(todos="{不是 json}"))["ok"], "坏 todos 文本落库不炸(兜空数组)", "")
    check(j(srv3.delete_minutes(mid))["ok"] and j(srv3.get_minutes(mid))["ok"] is False,
          "纪要软删后读不到", "")
    check(j(srv3.list_minutes())["count"] >= 1, "纪要列表可列", "")
    check(j(srv3.update_fragment(b["fragment_id"], "x" * 200))["ok"], "超长姓名被截断而不是报错", "")
    srv3._conn.close()
finally:
    shutil.rmtree(tmp, ignore_errors=True)

# ==================================================== 5. 主服务层契约(静态,不起服务)

import novaagent.main as main_mod  # noqa: E402

pairs = [(mm, r.path) for r in main_mod.app.routes
         for mm in (getattr(r, "methods", None) or [])]
dup = sorted({p for p in pairs if pairs.count(p) > 1})
check(not dup, "没有重复注册的 (method, path)——重复会让后一个**静默失效**", dup)

for need in (("POST", "/api/weekly/summarize"), ("PATCH", "/api/weekly/fragments/{fragment_id}"),
             ("GET", "/api/weekly/records/export"), ("POST", "/api/weekly/minutes/transcribe"),
             ("POST", "/api/weekly/minutes/organize"), ("POST", "/api/weekly/minutes"),
             ("GET", "/api/weekly/minutes/{minutes_id}"), ("PUT", "/api/weekly/minutes/{minutes_id}"),
             ("DELETE", "/api/weekly/minutes/{minutes_id}"),
             ("GET", "/api/weekly/minutes/{minutes_id}/export")):
    check(need in pairs, f"路由已注册 {need[0]} {need[1]}", "")

src_main = (NOVA / "novaagent" / "main.py").read_text(encoding="utf-8")
check("﻿" in src_main, "CSV 导出写了 UTF-8 BOM(Excel 无 BOM 打开中文乱码)", "")
check("filename*=UTF-8" in src_main, "中文文件名走 RFC 5987(HTTP 头是 latin-1)", "")
check(src_main.count("async def weekly_add") == 1, "weekly_add 只有一处实现(两处=一个永不生效)", "")

# `_minutes_payload`:HTTP 侧数组 → MCP 侧 JSON 文本(参数声明为 str,传 list 会被协议层拒)
pl = main_mod._minutes_payload({"title": "班委会 ", "meeting_time": "", "attendees": "张三",
                                "discussion": ["甲", "  ", "乙"], "resolutions": [],
                                "todos": [{"item": "报名", "owner": "李四", "due": ""},
                                          {"item": "", "owner": "X", "due": "y"}, "脏数据"]})
check(pl["title"] == "班委会" and json.loads(pl["discussion"]) == ["甲", "乙"],
      "要点:数组去空去空白后存 JSON 文本", pl["discussion"])
check(json.loads(pl["todos"]) == [{"item": "报名", "owner": "李四", "due": ""}],
      "待办:丢掉空 item 与非 dict 项", pl["todos"])
check(json.loads(main_mod._minutes_payload({"discussion": '["甲","乙"]'})["discussion"]) == ["甲", "乙"],
      "调用方把数组发成 JSON 文本时不再把中括号当成一条要点",
      main_mod._minutes_payload({"discussion": '["甲","乙"]'})["discussion"])
check(json.loads(main_mod._minutes_payload({"discussion": "第一行\n第二行"})["discussion"])
      == ["第一行", "第二行"], "换行文本形态也能切成条目", "")
check(json.loads(main_mod._minutes_payload({"discussion": "[坏 JSON"})["discussion"]) == ["[坏 JSON"],
      "看起来像数组但解析失败的字符串按原文保留,不静默丢内容", "")

src_agent = (NOVA / "novaagent" / "agent.py").read_text(encoding="utf-8")
# 用 AST 取 WEEKLY_TOOLS 的源码段,而不是靠"到 EXPAND_PROMPT 为止"这种位置切片 ——
# 提示词已搬进 prompts.py,位置切片会因索引越界而崩(而且它本来也只是个近似)。
_wt_src = ""
for _n in ast.walk(ast.parse(src_agent)):
    if isinstance(_n, ast.Assign) and any(getattr(_t, "id", "") == "WEEKLY_TOOLS" for _t in _n.targets):
        _wt_src = ast.get_source_segment(src_agent, _n) or ""
check(bool(_wt_src), "agent.py 里能找到 WEEKLY_TOOLS 定义(取不到则下面那条会假通过)", _wt_src[:40])
check("student_name" in _wt_src,
      "WEEKLY_TOOLS 的 JSON Schema 带上了 student_name(漏了则对话链路静默丢字段)", "")
check("render_docx" not in src_main or "minutes_lib.render_docx" in src_main,
      "docx 渲染只有一个入口", "")

# 前端 id 不变量(与 test_p4f_frontend_contract 同判据,但覆盖本单新增的文件)
HTML = (NOVA / "web" / "index.html").read_text(encoding="utf-8")
for js in ("minutes.js", "weekly.js"):
    text = (NOVA / "web" / "js" / js).read_text(encoding="utf-8")
    ids = set(re.findall(r"\$\('([A-Za-z0-9_-]+)'\)", text))
    dynamic = {"mt-copy", "fv-name", "fv-summary"}   # 由本文件自己渲染进 modal 的 id
    missing = sorted(i for i in ids if f'id="{i}"' not in HTML and i not in dynamic)
    check(not missing, f"{js} 里每个 $('id') 都有声明", missing)
check('src="/js/minutes.js"' in HTML, "minutes.js 已被 index.html 引用", "")
check(HTML.count('data-page="minutes"') == 1 and 'id="pane-minutes"' in HTML,
      "会议纪要入口与页面都在", "")

# ==================================================== 6. 静态资源缓存 / 前端接线 / 响应式

WEB = NOVA / "web"
JS_DIR = WEB / "js"
ALL_JS = {p.name: p.read_text(encoding="utf-8") for p in sorted(JS_DIR.glob("*.js"))}
SHELL_CSS = (WEB / "css" / "shell.css").read_text(encoding="utf-8")

from fastapi.testclient import TestClient  # noqa: E402

client = TestClient(main_mod.app)          # 不进 lifespan:不连 weekly MCP,不发模型请求

# 【为什么把「缓存头」写进闸门】缺陷 1/2 的代码当时**都是对的**,红在浏览器执行的
# 是改版前的 weekly.js:静态响应没有 Cache-Control,Chrome 就按启发式缓存
# (约 (now − Last-Modified)/10 内不回源)直接复用旧文件。于是出现「HTML 是新的
# (F5 会无条件重取主文档)、JS 是旧的」的混合态:
#   · 旧 addFragment 不传 student_name → 新后端 400「必须填写学生姓名」,姓名明明填了也存不进;
#   · 旧文件里没有 summarizeTalk → 内联 onclick 抛 ReferenceError,**只在 console**,
#     用户看到的是「点了没反应,不转圈也不报错」。
# 这两条症状同根,根因在**服务端头**而不是校验逻辑,所以判据也只能落在头上:
# 每个入口资源必须带 no-cache(配合 FileResponse 自带的 ETag 走 304,不是每次全量下载)。
for p in ("/", "/js/weekly.js", "/js/minutes.js", "/css/theme.css", "/css/shell.css"):
    r = client.get(p)
    check(r.status_code == 200, f"入口资源可访问 {p}", f"status={r.status_code}")
    check("no-cache" in (r.headers.get("cache-control") or ""),
          f"{p} 带 Cache-Control: no-cache(否则浏览器会复用改版前的 JS/CSS)",
          f"cache-control={r.headers.get('cache-control')!r}")

r = client.get("/js/weekly.js")
etag = r.headers.get("etag")
check(bool(etag), "静态资源带 ETag(no-cache 的回源校验靠它,不然每条都全量下载)", "")
r304 = client.get("/js/weekly.js", headers={"If-None-Match": etag or ""})
check(r304.status_code == 304, "带 If-None-Match 回 304(重新部署后拿新代码,未变时不重传)",
      f"status={r304.status_code}")

srcs = re.findall(r'src="/js/([A-Za-z0-9_.-]+)"', HTML)
hrefs = re.findall(r'href="/css/([A-Za-z0-9_.-]+)"', HTML)
check(len(srcs) >= 5 and len(hrefs) >= 2, "确实扫到 index.html 引用的脚本与样式(防空集假通过)",
      f"srcs={srcs} hrefs={hrefs}")
for name in srcs:
    check(client.get("/js/" + name).status_code == 200, f"index.html 引用的 /js/{name} 真存在", "")
for name in hrefs:
    check(client.get("/css/" + name).status_code == 200, f"index.html 引用的 /css/{name} 真存在", "")
check(client.get("/js/%2e%2e%2f%2e%2e%2frequirements.txt").status_code == 404,
      "静态资源路由仍然挡住路径穿越", "")

# 内联 onclick/onchange 指向的函数必须在某个已加载脚本里定义 —— 缺陷 2 的**这一类**:
# 函数不存在时浏览器只往 console 丢一条 ReferenceError,页面表现为「按钮点了没反应」。
js_all = "\n".join(ALL_JS.values())
defined = set(re.findall(r"function\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*\(", js_all))
defined |= set(re.findall(r"(?:const|let|var)\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*=\s*(?:async\s*)?(?:\(|function)", js_all))
defined |= set(re.findall(r"(?:window|globalThis)\.([A-Za-z_$][A-Za-z0-9_$]*)\s*=", js_all))
handlers = set(re.findall(r'on(?:click|change|input|keydown|submit)="([A-Za-z_$][A-Za-z0-9_$]*)\s*\(',
                          HTML + js_all))
check(len(handlers) >= 10, "确实扫到内联事件处理函数(防空集假通过)", f"n={len(handlers)}")
check(not (handlers - defined), "每个内联 onclick/onchange 都有对应函数定义(缺一个=点了静默没反应)",
      sorted(handlers - defined))

sum_fn = re.search(r"async function summarizeTalk\(\).*?\n}", js_all, re.S).group(0)
check("摘要中" in sum_fn, "生成摘要:请求期间有可见的加载态", sum_fn)
check(sum_fn.count("toast(") >= 2, "生成摘要:接口失败与返回为空都有用户可见反馈", sum_fn)
check("finally" in sum_fn, "生成摘要:无论成功失败都恢复按钮(异常路径不能卡在「摘要中…」)", sum_fn)
check('addEventListener("error"' in js_all or "addEventListener('error'" in js_all,
      "未捕获的脚本错误会被显式提示(静默失败是最难归因的用户反馈)", "")

# 工作记录查看页自适应(缺陷 3):列宽不再写死在 HTML 上,窄宽度靠横向滚动而不是压成竖排
pane_records = HTML[HTML.index('id="pane-records"'):HTML.index('id="pane-weekly"')]
check("table-wrap" in pane_records, "工作记录表格外层有滚动容器", pane_records[:200])
check('style="width:' not in pane_records, "表头列宽从 HTML 内联样式搬到 CSS(写死列宽会把内容列挤成竖排)", "")
check(re.search(r"\.table-wrap\b[^}]*overflow-x:\s*auto", SHELL_CSS), "shell.css 给 .table-wrap 开了横向滚动", "")
check(re.search(r"table-wrap\s*>?\s*table[^}]*min-width:\s*\d{3,4}px", SHELL_CSS)
      or re.search(r"\.rec-table[^}]*min-width:\s*\d{3,4}px", SHELL_CSS),
      "表格有最小宽度兜底(窄窗口改成横向滚动,而不是每列挤成几个字)", "")
check("@media (max-width" in SHELL_CSS and SHELL_CSS.count("@media (max-width") >= 4,
      "shell.css 有窄视口断点(左栏收成图标轨,主区不被饿死)", SHELL_CSS.count("@media (max-width"))
check(re.search(r"#w-name\b[^}]*min-width:\s*\d+px", SHELL_CSS),
      "学生姓名输入框有最小宽度(实测 83px 时填了什么看不见,像「没填」)", "")
check('class="clamp"' in js_all, "记录内容单元格做了行数限制(避免一行记录撑满半屏)", "")

print("=" * 78)
failed = [r for r in RESULTS if not r[0]]
print(f"[RESULT] {len(RESULTS) - len(failed)}/{len(RESULTS)} passed")
sys.exit(1 if failed else 0)
