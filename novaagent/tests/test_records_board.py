#!/usr/bin/env python
"""工作记录「日/月/年看板」+ 周报「按周生成」的离线自测。

零额度:不发 LLM 请求、不起服务。前端纯函数用 **node 真跑**(与 test_p5_shell.py
同一套路),其余是静态契约检查 —— 两条路都不依赖浏览器。

跑法:
    novaagent/.venv/Scripts/python.exe tests/test_records_board.py
退出码:0 = 全过;1 = 有红。
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
NOVA = HERE.parent
ROOT = NOVA.parent
sys.path.insert(0, str(NOVA))

RESULTS: list[tuple[bool, str, str]] = []


def check(cond, label, detail=""):
    RESULTS.append((bool(cond), label, "" if cond else str(detail)))
    print(f"[{'PASS' if cond else 'FAIL'}] {label}" + ("" if cond else f"  → {detail}"))


HTML = (NOVA / "web" / "index.html").read_text(encoding="utf-8")
JS = NOVA / "web" / "js"
CSS = NOVA / "web" / "css"
SRC_WEEKLY = (JS / "weekly.js").read_text(encoding="utf-8")
SRC_SHELLJS = (JS / "shell.js").read_text(encoding="utf-8")
SRC_CSS = (CSS / "shell.css").read_text(encoding="utf-8")


# ==================================================== 1. node 真跑前端纯函数
def _node_bin() -> str | None:
    for cand in ("node", "node.exe"):
        p = shutil.which(cand)
        if p:
            return p
    managed = (Path.home() / ".workbuddy" / "binaries" / "node" / "versions"
               / "22.22.2-3" / "node.exe")
    return str(managed) if managed.exists() else None


NODE = _node_bin()

# 在 node 里用 vm 加载 api.js + weekly.js(它们没有 module.exports,require 拿不到函数),
# 配一套最小 DOM 桩后执行用例,把每条结果打成 JSON 交回 Python 断言。
NODE_SCRIPT = r"""
const fs = require('fs'), vm = require('vm');
const JS = process.argv[1];
const els = {};
const mkEl = id => (els[id] = {
  id, type: '', value: '', textContent: '', innerHTML: '', style: { display: '' },
  _cls: new Set(), options: { length: 0 }, disabled: false,
  classList: { toggle(c, on) { on ? els[id]._cls.add(c) : els[id]._cls.delete(c); },
               contains(c) { return els[id]._cls.has(c); } },
  appendChild() { this.options.length++; },
});
const calls = [];
const ctx = {
  console,
  localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
  document: {
    getElementById: id => els[id] || mkEl(id),
    querySelectorAll: () => [],
    createElement: () => ({ value: '', style: {}, classList: { toggle() {} } }),
    body: { appendChild() {} },
  },
  location: { hash: '' },
  // api.js 顶层会 window.addEventListener('error', …) 挂全局错误提示
  addEventListener() {}, removeEventListener() {},
  // toast 靠 setTimeout 收起提示;定时器在 vm 里不存在,补空实现即可
  setTimeout: () => 0, clearTimeout() {}, setInterval: () => 0, clearInterval() {},
  toast: m => calls.push(['toast', m]),
  /* ⚠ 桩要打在 fetch 上而不是 api 上:api.js 自己就定义了 `async function api`,
     在 vm 里它会覆盖同名桩 —— 打在 api 上等于没打,请求根本走不到桩里(实测表现是
     断言拿到 undefined)。打在 fetch 上还能顺带验到**真实请求体**。 */
  fetch: async (path, opts) => {
    let body = null;
    try { body = JSON.parse(opts && opts.body); } catch (e) { /* 非 JSON 请求体 */ }
    calls.push(['api', path, body]);
    return { ok: true, status: 200, headers: { get: () => null },
             json: async () => ({ ok: true, fragments: [], stats: {},
                                  report_markdown: '', start_date: '', end_date: '' }) };
  },
  URLSearchParams,
};
ctx.window = ctx;
// 冻结「今天」为 2026-10-08(ISO 第 41 周的周四):initWeek / switchBoard 的
// 「默认本周 / 本月 / 本年」类断言只依赖今天落在哪一周,不该随运行日期漂移。
// 不冻结就会每周过期一次 —— 曾出现 41/47,6 条红全是这个原因。
const _RealDate = Date;
const _FIXED_NOW = _RealDate.UTC(2026, 9, 8, 4, 0, 0); // = 北京时间 12:00,常见时区里都是 10-05~10-11 这一周
class FrozenDate extends _RealDate {
  constructor(...args) { super(...(args.length ? args : [_FIXED_NOW])); }
  static now() { return _FIXED_NOW; }
}
ctx.Date = FrozenDate;
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(JS + '/api.js', 'utf8'), ctx);
vm.runInContext(fs.readFileSync(JS + '/weekly.js', 'utf8'), ctx);
const run = e => vm.runInContext(e, ctx);
// 桩是懒创建的:用例要直接读写的元素先建出来(否则 els['x'] 是 undefined)
['rec-start','rec-end','rec-cat','rec-month','rec-year','rec-scope-day','rec-stats',
 'recs','bt-day','bt-month','bt-year','board-tip','w-week','w-week-tip','w-week-stats',
 'weekly-out','archive-btn'].forEach(mkEl);

const out = [];
const eq = (got, want, label) => out.push({
  label, ok: JSON.stringify(got) === JSON.stringify(want),
  got: String(JSON.stringify(got)), want: String(JSON.stringify(want)),
});
const vis = id => els[id].style.display !== 'none';

(async () => {
  // ---- 周次:周一~周日 ----
  eq(run("weekOf('2026-10-15')"), {monday:'2026-10-12', sunday:'2026-10-18', year:2026, week:42},
     '周中任意一天归一到整周(周一~周日)');
  eq(run("weekOf('2026-01-01')"), {monday:'2025-12-29', sunday:'2026-01-04', year:2026, week:1},
     '跨年周按 ISO 定年(周一落在上年 12 月)');
  eq(run("parseWeekInput('2026-W42')"), {monday:'2026-10-12', sunday:'2026-10-18', year:2026, week:42},
     'type=week 取值 2026-W42 → 整周');
  eq(run("parseWeekInput('2026-10-15')").monday, '2026-10-12',
     '降级为日期时同样归一到整周(不支持 week 的浏览器)');
  eq(run("parseWeekInput('2025-W53')"), null, '不存在的周次判无效(不静默溢出到次年)');

  // ---- 看板范围 ----
  els['rec-start'].value = '2026-09-18'; els['rec-end'].value = '2026-09-18';
  eq(run("boardMode='day'; currentRange()"), ['2026-09-18', '2026-09-18'],
     '日看板沿用起止日期(单日查询不破坏)');
  eq(run("boardMode='month'; (function(){ $('rec-month').value='2026-09'; return currentRange(); })()"),
     ['2026-09-01', '2026-09-30'], '月看板 = 月初~月末');
  eq(run("monthEndISO('2024-02')"), '2024-02-29', '闰年 2 月末');
  eq(run("boardMode='year'; (function(){ $('rec-year').value='2026'; return currentRange(); })()"),
     ['2026-01-01', '2026-12-31'], '年看板 = 年初~年末');

  // ---- 切换看板:默认值 + 控件互斥 ----
  els['rec-month'].value = ''; els['rec-year'].value = '';
  await run("switchBoard('month')");
  eq(els['rec-month'].value, '2026-10', '月看板默认本月');
  eq([vis('rec-month'), vis('rec-scope-day'), vis('rec-year')], [true, false, false],
     '月看板只显示月份选择器');
  await run("switchBoard('year')");
  eq(els['rec-year'].value, '2026', '年看板默认本年');
  eq([vis('rec-year'), vis('rec-month')], [true, false], '年看板只显示年份选择器');
  await run("switchBoard('day')");
  eq([vis('rec-scope-day'), vis('rec-month')], [true, false], '日看板恢复起止日期输入');

  // ---- 指标区 ----
  run("renderBoardStats('rec-stats', {'谈心谈话':3,'活动组织':1}, 4)");
  const h = els['rec-stats'].innerHTML;
  eq(/bs-total[^>]*><b>4<\/b>/.test(h), true, '合计卡片 = 该范围记录总数');
  eq([/<b>3<\/b>谈心谈话/.test(h), /<b>1<\/b>活动组织/.test(h), /<b>0<\/b>事务办理/.test(h)],
     [true, true, true], '按记录类型计数(未发生的类型显示 0,便于横向对比)');
  eq((h.match(/class="bs-item/g) || []).length, 6, '1 张合计 + 5 个记录类型');
  run("renderBoardStats('rec-stats', {}, 0)");
  eq(/bs-empty/.test(els['rec-stats'].innerHTML), true, '无记录时给出明确文案(不是空白)');

  // ---- 周报:按周 ----
  els['w-week'].type = 'week';
  await run("initWeek()");
  eq(els['w-week'].value, '2026-W41', '周报默认本周');
  eq(els['w-week-tip'].textContent,
     '2026 年第 41 周 · 2026-10-05（周一）~ 2026-10-11（周日）',
     '展示周次与起止日期范围');
  await run("shiftWeek(-1)"); eq(els['w-week'].value, '2026-W40', '◀ 上周');
  await run("shiftWeek(1)");  eq(els['w-week'].value, '2026-W41', '下周 ▶');
  calls.length = 0;
  await run("renderReport()");
  const rep = calls.filter(c => c[0] === 'api' && c[1] === '/api/weekly/report').pop();
  eq(rep && rep[2], { start_date: '2026-10-05', end_date: '2026-10-11' },
     '生成周报传整周(周一~周日),而不是选中那一天');

  // ---- 降级:不支持 type=week 的浏览器 ----
  els['w-week'].type = 'text'; els['w-week'].value = '';
  await run("initWeek()");
  eq(els['w-week'].type, 'date', '不支持 week 时降级为 date');
  eq(els['w-week-tip'].textContent.includes('第 41 周'), true, '降级后同样展示周次与范围');

  console.log(JSON.stringify(out));
})();
"""

if not NODE:
    check(False, "自测前置:node 可用(否则前端纯函数无法真跑)", "node 不在 PATH")
else:
    p = subprocess.run([NODE, "-e", NODE_SCRIPT, JS.as_posix()],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=120)
    if p.returncode != 0:
        check(False, "node 跑 weekly.js 成功", (p.stderr or p.stdout or "")[:400])
    else:
        try:
            for r in json.loads(p.stdout.strip()):
                check(r["ok"], r["label"], f"got {r['got']} want {r['want']}")
        except Exception as e:  # noqa: BLE001
            check(False, "node 输出可解析", f"{type(e).__name__}: {p.stdout[:200]}")


# ==================================================== 2. 静态契约
# 看板三档与周选择器都必须在 HTML 里真存在(JS 里的 $('id') 取不到 = 静默不生效)
for need in ("bt-day", "bt-month", "bt-year", "rec-scope-day", "rec-month",
             "rec-year", "board-tip", "rec-stats", "w-week", "w-week-tip",
             "w-week-stats"):
    check(f'id="{need}"' in HTML, f"HTML 声明了 #{need}", "")

# 日看板/单日查询不能被动过
check('id="rec-start"' in HTML and 'id="rec-end"' in HTML,
      "日看板的起止日期输入仍在(单日查询不破坏)", "")
check('id="w-start"' not in HTML, "旧的单日周报选择器已移除(不留两个入口)", "")

# 内联事件必须都有实现 —— 缺一个就是"点了没反应",且没有任何报错
handlers = set(re.findall(r'on(?:click|change)="([a-zA-Z_$][\w$]*)\(', HTML))
for fn in sorted(handlers):
    if fn in ("switchBoard", "loadRecords", "onWeekChange", "shiftWeek", "renderReport"):
        check(re.search(rf"function\s+{fn}\b", SRC_WEEKLY) is not None,
              f"内联事件 {fn}() 在 weekly.js 有实现", "")

check(re.search(r"onEnter:\s*'enterWeekly'", SRC_SHELLJS) is not None,
      "周报页入口改挂 enterWeekly(进入就就位本周)", "")
check("async function enterWeekly" in SRC_WEEKLY, "enterWeekly 已定义", "")
check(".board-stats" in SRC_CSS and ".board-tab.sel" in SRC_CSS,
      "shell.css 有指标区与看板选中态样式", "")
# 指标项沿用记录类型:新增类型只改数组,不用动渲染
check("const REC_CATS" in SRC_WEEKLY and "活动组织" in SRC_WEEKLY,
      "指标项沿用现有记录类型(常量集中一处,便于扩展)", "")

print("=" * 78)
failed = [r for r in RESULTS if not r[0]]
print(f"[RESULT] {len(RESULTS) - len(failed)}/{len(RESULTS)} passed")
sys.exit(1 if failed else 0)
