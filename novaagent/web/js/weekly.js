/* P4b-0 拆分:本文件内容由 index.html 原样迁移(零修改),行为零变化。 */
// 周报:工作记录/详情/AI 扩充/生成/归档
// 谈心谈话:学生姓名 + 自动摘要 + 按月导出
// 工作记录看板:日 / 月 / 年三档(同一套筛选条件与数据结构)

const NAME_PH = '（未登记姓名）';
const SUMMARY_PH = '（未生成摘要）';
const TALK_CAT = '谈心谈话';

/* 看板指标项 = 记录类型本身,与后端 CATEGORIES 同源。新增类型只改这一处
   (后端返回了表里没有的分类时会被自动追加,不会漏统计)。 */
const REC_CATS = ['谈心谈话', '事务办理', '活动组织', '异常突发', '其他'];
const REC_BOARDS = ['day', 'month', 'year'];
let boardMode = 'day';

// ---------- 日期 / 周次(纯函数,不发请求、不碰 DOM) ----------
/* ⚠ 叫 MS_DAY 而不是 DAY_MS:conversations.js 已在**同一全局作用域**声明了 DAY_MS,
   这里再 const 一次会让整个文件顶层抛 "already been declared" —— 那不是某一行报错,
   是**本文件所有函数一起不生效**(会话历史照常加载,于是看起来"只是周报不正常")。
   不复用对方那个常量的原因是:本文件的周次算法会被自测单独加载运行,
   依赖别的文件先加载等于把加载顺序变成隐式契约。 */
const MS_DAY = 86400000;

/** 本机时区的今天 YYYY-MM-DD。不用 toISOString():那是 UTC,早晨 8 点前会差一天。 */
function todayISO() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}
function toUTCDate(iso) {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(iso || '').trim());
  return m ? new Date(Date.UTC(+m[1], +m[2] - 1, +m[3])) : null;
}
function toISO(d) { return d.toISOString().slice(0, 10); }
const pad2 = n => String(n).padStart(2, '0');

/** ISO 周次:该周的**周四**落在哪年,这周就属于哪年(跨年周由此定年)。 */
function isoWeekInfo(d) {
  const day = d.getUTCDay() || 7;                       // 周一=1 … 周日=7
  const thu = new Date(d.getTime() + (4 - day) * MS_DAY);
  const year = thu.getUTCFullYear();
  const jan1 = new Date(Date.UTC(year, 0, 1));
  const jan1Dow = jan1.getUTCDay() || 7;
  const firstMon = new Date(jan1.getTime() - (jan1Dow - 1) * MS_DAY);
  return { year, week: Math.round((thu - firstMon) / (7 * MS_DAY)) + 1 };
}

/** 由某个周一推出整周范围(周一~周日)+ 周次。 */
function weekRangeOf(mon) {
  const info = isoWeekInfo(mon);
  return { monday: toISO(mon), sunday: toISO(new Date(mon.getTime() + 6 * MS_DAY)),
           year: info.year, week: info.week };
}
/** 任一日期 → 它所在的那一周(周一起)。 */
function weekOf(iso) {
  const d = toUTCDate(iso);
  if (!d) return null;
  return weekRangeOf(new Date(d.getTime() - ((d.getUTCDay() || 7) - 1) * MS_DAY));
}
/** 周选择器取值 → 整周范围。同时接受 `2026-W42`(type=week)与 `2026-10-12`
    (不支持 week 的浏览器降级成 date/手填),两条路都归一到周一~周日。 */
function parseWeekInput(v) {
  const s = String(v || '').trim();
  const m = /^(\d{4})-W(\d{1,2})$/i.exec(s);
  if (m) {
    const y = +m[1], w = +m[2];
    if (w < 1 || w > 53) return null;
    const jan4 = new Date(Date.UTC(y, 0, 4));
    const w1Mon = new Date(jan4.getTime() - ((jan4.getUTCDay() || 7) - 1) * MS_DAY);
    const mon = new Date(w1Mon.getTime() + (w - 1) * 7 * MS_DAY);
    // W53 溢出到下一年第 1 周的,判为无效:宁可让按钮提示"请重选",也不把
    // 2026-W53 静默算成 2027 年第 1 周 —— 那会让归档文件的日期与界面显示的周对不上
    const info = isoWeekInfo(mon);
    if (info.year !== y || info.week !== w) return null;
    return weekRangeOf(mon);
  }
  if (/^\d{4}-\d{2}-\d{2}$/.test(s)) return weekOf(s);
  return null;
}
const weekValue = r => `${r.year}-W${pad2(r.week)}`;
/** 月末日(下个月的第 0 天 = 本月最后一天)。 */
function monthEndISO(ym) {
  const m = /^(\d{4})-(\d{2})$/.exec(String(ym || ''));
  if (!m) return '';
  return toISO(new Date(Date.UTC(+m[1], +m[2], 0)));
}

// ---------- 看板切换 ----------

/** 当前看板对应的 [start_date, end_date]。日看板沿用原有的起止日期输入(可留空=全部)。 */
function currentRange() {
  if (boardMode === 'month') {
    const ym = $('rec-month').value;
    return ym ? [ym + '-01', monthEndISO(ym)] : ['', ''];
  }
  if (boardMode === 'year') {
    const y = $('rec-year').value;
    return y ? [`${y}-01-01`, `${y}-12-31`] : ['', ''];
  }
  return [$('rec-start').value, $('rec-end').value];
}

function fillYears() {
  const sel = $('rec-year');
  if (!sel || sel.options.length) return;
  const cur = new Date().getFullYear();
  // 倒序:常用年份在最上面;上限取到明年,允许为下学期提前建记录
  for (let y = cur + 1; y >= 2000; y--) {
    const o = document.createElement('option');
    o.value = String(y); o.textContent = `${y} 年`;
    sel.appendChild(o);
  }
}

function switchBoard(mode) {
  boardMode = REC_BOARDS.indexOf(mode) >= 0 ? mode : 'day';
  const isDay = boardMode === 'day', isMonth = boardMode === 'month', isYear = boardMode === 'year';
  $('rec-scope-day').style.display = isDay ? 'flex' : 'none';
  $('rec-month').style.display = isMonth ? '' : 'none';
  $('rec-year').style.display = isYear ? '' : 'none';
  REC_BOARDS.forEach(m => {
    $(`bt-${m}`).classList.toggle('sel', m === boardMode);
  });
  // 默认值只在**切进去时**填,不覆盖用户已经手选过的值
  if (isMonth && !$('rec-month').value) $('rec-month').value = todayISO().slice(0, 7);
  if (isYear) { fillYears(); if (!$('rec-year').value) $('rec-year').value = String(new Date().getFullYear()); }
  $('board-tip').textContent = isDay
    ? '按起止日期查询；两个日期都留空 = 全部记录'
    : isMonth ? '默认本月；可切换其它月份'
              : '默认本年；可切换其它年份';
  return loadRecords();
}

/** 指标区:合计 + 各记录类型条数(沿用现有类型,含 0 也列出,便于横向对比)。 */
function renderBoardStats(elId, stats, total) {
  const el = $(elId);
  if (!el) return;
  const st = stats || {};
  if (!total) { el.innerHTML = '<span class="bs-empty">该范围内没有记录</span>'; return; }
  const cats = REC_CATS.concat(Object.keys(st).filter(k => REC_CATS.indexOf(k) < 0));
  el.innerHTML = `<span class="bs-item bs-total"><b>${total}</b>合计</span>`
    + cats.map(c => `<span class="bs-item"><b>${st[c] || 0}</b>${esc(c)}</span>`).join('');
}

async function loadRecords() {
  const [s, e] = currentRange();
  try {
    const qs = new URLSearchParams({ category: $('rec-cat').value, start_date: s, end_date: e });
    const d = await api('/api/weekly/fragments?' + qs);
    renderBoardStats('rec-stats', d.stats, d.fragments.length);
    $('recs').innerHTML = d.fragments.length ? d.fragments.map(x => `
      <tr>
        <td class="c-date">${x.occurred_at}</td>
        <td class="c-cat"><span class="tag">${x.category}</span></td>
        <td class="c-name">${esc(x.student_name || NAME_PH)}</td>
        <td class="t-content"><span class="clamp">${esc(x.content.length > 60 ? x.content.slice(0, 60) + '…' : x.content)}</span></td>
        <td class="c-ops">
          <button class="link" onclick="viewFrag(${x.id},'${x.occurred_at}','${x.category}')">详情</button>
          <button class="link del" onclick="delFrag(${x.id})">删除</button>
        </td>
      </tr>`).join('') : '<tr><td colspan="5" class="empty">该范围内没有记录</td></tr>';
    window._frags = Object.fromEntries(d.fragments.map(f => [f.id, f]));
  } catch (e) { toast(e.message); }
}

function viewFrag(id, date, cat) {
  const f = (window._frags || {})[id];
  if (!f) return;
  const isTalk = f.category === TALK_CAT;
  openModal(`工作记录详情 · ${date}`,
    `<div class="meta-grid">
       <span class="k">分类</span><span><span class="tag">${esc(f.category)}</span></span>
       <span class="k">发生日期</span><span>${esc(f.occurred_at)}</span>
       <span class="k">记录编号</span><span>#${f.id}</span>
     </div>
     <div class="detail-label">学生姓名${isTalk ? '（谈心谈话必填）' : ''}</div>
     <div class="row"><input id="fv-name" maxlength="40" value="${esc(f.student_name || '')}" placeholder="${NAME_PH}"></div>
     ${isTalk ? '<div class="detail-label">谈话摘要（可手动修改）</div>'
              + '<div class="row"><input id="fv-summary" maxlength="200" value="'
              + esc(f.summary || '') + '" placeholder="' + SUMMARY_PH + '"></div>' : ''}
     <div class="detail-label">记录内容</div>
     <div class="md-pre">${esc(f.content)}</div>
     <div class="row"><button class="btn ghost" onclick="saveFrag(${f.id},${isTalk ? 'true' : 'false'})">保存修改</button></div>
     <p style="color:var(--muted);font-size:11px;margin-top:10px">提示：历史记录的姓名与摘要为空属正常（这两项是后加的，系统不回填、不代填）；导出时这些位置写成占位串。</p>`);
}

async function saveFrag(id, isTalk) {
  const body = { student_name: $('fv-name').value.trim() };
  if (isTalk) body.summary = $('fv-summary').value.trim();
  if (isTalk && !body.student_name) return toast('谈心谈话记录必须填写学生姓名');
  if (!body.student_name && !body.summary) return toast('请至少填写姓名或摘要');
  try {
    await api(`/api/weekly/fragments/${id}`, { method: 'PATCH', json: body });
    toast('已保存'); closeModal(); loadRecords();
  } catch (e) { toast(e.message); }
}

async function exportTalkMonth() {
  const month = $('rec-export-month').value;
  if (!month) return toast('请先选择要导出的月份');
  try {
    const name = await downloadFile(`/api/weekly/records/export?month=${encodeURIComponent(month)}`,
      '谈心谈话记录_' + month + '.csv');
    toast('已导出：' + name);
  } catch (e) { toast(e.message); }
}

function onTalkCatChange() {
  const talk = $('w-cat').value === TALK_CAT;
  $('w-name-row').style.display = talk ? 'flex' : 'none';
  $('w-name-tip').textContent = talk ? '谈心谈话类记录必须登记学生姓名' : '这一类不需要学生姓名';
}

async function summarizeTalk() {
  const c = $('w-content').value.trim(); if (!c) return toast('请先写记录内容');
  const btn = $('summarize-btn'); btn.disabled = true; btn.textContent = '摘要中…';
  try {
    const d = await api('/api/weekly/summarize', { method: 'POST', json: { content: c } });
    const s = (d.summary || '').trim();
    // 空结果必须**说出来**:静默留空和「按钮是死的」在用户眼里是同一件事。
    // 这里不清空摘要框 —— 辅导员手填的内容不能被一次失败的生成冲掉。
    if (s) { $('w-summary').value = s; toast('已生成摘要，请核对后再保存'); }
    else toast('模型没能判定谈话主题，摘要保持原样：可手动填写，或直接保存记录');
  } catch (e) {
    toast('摘要生成失败：' + (e.message || e) + '（记录内容没丢，可手填摘要后直接保存）');
  } finally {
    btn.disabled = false; btn.textContent = '✨ 生成摘要';
  }
}

async function delFrag(id) {
  if (!confirm('确认删除这条记录？')) return;
  try { await api(`/api/weekly/fragments/${id}`, { method: 'DELETE' }); toast('已删除'); loadRecords(); }
  catch (e) { toast(e.message); }
}

/** 周报页入口(shell.js PAGES.onEnter):先就位本周,再拉归档列表。 */
async function enterWeekly() {
  initWeek();
  await loadArchived();
}

async function loadArchived() {
  try {
    const d = await api('/api/weekly/reports');
    $('archived').innerHTML = d.count ? d.reports.map(x => `
      <li>📄 ${esc(x.title)} <span style="color:var(--muted);font-size:11px">${x.start_date}~${x.end_date}</span>
        <button class="link" onclick="viewReport(${x.id})">查看</button></li>`).join('')
      : '<li class="empty">暂无归档周报</li>';
  } catch (e) { toast(e.message); }
}

async function viewReport(id) {
  try {
    const d = await api(`/api/weekly/reports/${id}`);
    openModal(`${d.title}（${d.start_date} ~ ${d.end_date}）`, `<div class="md-pre">${esc(d.content_md)}</div><p style="color:var(--muted);font-size:11px;margin-top:8px">归档于 ${(d.archived_at || '').slice(0, 16).replace('T', ' ')} · 文件：${esc(d.file_path)}</p>`);
  } catch (e) { toast(e.message); }
}

async function expandFragment() {
  const c = $('w-content').value.trim(); if (!c) return toast('请先写几句简短笔记');
  const btn = $('expand-btn'); btn.disabled = true; btn.textContent = '扩充中…';
  try {
    const d = await api('/api/weekly/expand', { method: 'POST', json: { content: c, category: $('w-cat').value } });
    $('w-content').value = d.expanded;
    toast('已生成草稿，请核对修改后保存（AI 仅按你的纪要风格润色，不会虚构学生反馈）');
  } catch (e) { toast(e.message); }
  btn.disabled = false; btn.textContent = '✨ AI 扩充';
}

async function addFragment() {
  const c = $('w-content').value.trim(); if (!c) return toast('请输入内容');
  const cat = $('w-cat').value;
  const name = $('w-name').value.trim();
  if (cat === TALK_CAT && !name) {
    // 与后端 400 同一判据,只是先把话拦在本地,省一个来回(后端仍是权威)
    $('w-name-row').style.display = 'flex';
    return toast('谈心谈话记录必须填写学生姓名');
  }
  try {
    const d = await api('/api/weekly/fragments', {
      method: 'POST',
      json: { content: c, category: cat, occurred_at: $('w-date').value,
              student_name: name, summary: $('w-summary').value.trim() }
    });
    if (!d.ok) return toast(d.error || '保存失败');
    toast(d.summary ? `已记录（分类：${d.category}｜摘要：${d.summary}）` : `已记录（分类：${d.category}）`);
    $('w-content').value = ''; $('w-name').value = ''; $('w-summary').value = '';
  } catch (e) { toast(e.message); }
}

// ---------- 周报:按周(周一~周日)选择 ----------

/** 进入周报页时的初始化:填本周,并降级不支持 `type=week` 的浏览器。 */
function initWeek() {
  const el = $('w-week');
  if (!el) return;
  // 不支持 week 输入时浏览器会把 type 降级成 text —— 换成 date,选任一天即归到所在周
  if (el.type !== 'week') el.type = 'date';
  if (!el.value) {
    const r = weekOf(todayISO());
    if (r) el.value = el.type === 'week' ? weekValue(r) : r.monday;
  }
  onWeekChange();
}

function currentWeekRange() {
  const el = $('w-week');
  return el ? parseWeekInput(el.value) : null;
}

/** 选定周后先统计该周记录(谈心谈话/活动组织…),让用户生成前就能核对范围与条数。 */
async function onWeekChange() {
  const r = currentWeekRange();
  const tip = $('w-week-tip');
  if (!r) {
    if (tip) tip.textContent = '请选择要生成周报的周（周一至周日）';
    renderBoardStats('w-week-stats', null, 0);
    return;
  }
  if (tip) tip.textContent = `${r.year} 年第 ${r.week} 周 · ${r.monday}（周一）~ ${r.sunday}（周日）`;
  try {
    const qs = new URLSearchParams({ start_date: r.monday, end_date: r.sunday });
    const d = await api('/api/weekly/fragments?' + qs);
    renderBoardStats('w-week-stats', d.stats, d.fragments.length);
  } catch (e) {
    renderBoardStats('w-week-stats', null, 0);   // 统计失败不阻断生成,只留空
  }
}

function shiftWeek(n) {
  const r = currentWeekRange() || weekOf(todayISO());
  const el = $('w-week');
  if (!r || !el) return;
  const mon = toUTCDate(r.monday);
  const nr = weekRangeOf(new Date(mon.getTime() + n * 7 * MS_DAY));
  el.value = el.type === 'week' ? weekValue(nr) : nr.monday;
  onWeekChange();
}

async function renderReport() {
  const r = currentWeekRange();
  if (!r) return toast('请先选择要生成周报的周');
  try {
    // end_date 显式传周日:后端缺省虽也算到周日,但它以**传入的 start** 为起点,
    // 起点选在周三就会生成"周三~周日"的半周周报
    const d = await api('/api/weekly/report', { method: 'POST', json: { start_date: r.monday, end_date: r.sunday } });
    if (!d.ok) return toast(d.error || '生成失败');
    lastReport = d; $('weekly-out').style.display = 'block'; $('weekly-out').textContent = d.report_markdown;
    $('archive-btn').disabled = false;
    onWeekChange();     // 生成后同步刷新该周统计,与周报正文口径一致
  } catch (e) { toast(e.message); }
}

async function archiveReport() {
  if (!lastReport) return;
  try {
    const d = await api('/api/weekly/archive', { method: 'POST', json: { title: '辅导员工作周报', start_date: lastReport.start_date, end_date: lastReport.end_date, content_md: lastReport.report_markdown } });
    toast(d.ok ? '已归档：' + d.file : d.error); $('archive-btn').disabled = true; loadArchived();
  } catch (e) { toast(e.message); }
}
