/* P4b-0 拆分:本文件内容由 index.html 原样迁移(零修改),行为零变化。 */
// 周报:工作记录/详情/AI 扩充/生成/归档

async function loadRecords() {
  try {
    const qs = new URLSearchParams({ category: $('rec-cat').value, start_date: $('rec-start').value, end_date: $('rec-end').value });
    const d = await api('/api/weekly/fragments?' + qs);
    $('rec-stats').innerHTML = Object.entries(d.stats).map(([k, v]) => `<span>${k} ${v}</span>`).join('') || '<span>无记录</span>';
    $('recs').innerHTML = d.fragments.length ? d.fragments.map(x => `
      <tr>
        <td>${x.occurred_at}</td>
        <td><span class="tag">${x.category}</span></td>
        <td class="t-content">${esc(x.content.length > 60 ? x.content.slice(0, 60) + '…' : x.content)}</td>
        <td style="white-space:nowrap">
          <button class="link" onclick="viewFrag(${x.id},'${x.occurred_at}','${x.category}')">详情</button>
          <button class="link del" onclick="delFrag(${x.id})">删除</button>
        </td>
      </tr>`).join('') : '<tr><td colspan="4" class="empty">该范围内没有记录</td></tr>';
    window._frags = Object.fromEntries(d.fragments.map(f => [f.id, f]));
  } catch (e) { toast(e.message); }
}

function viewFrag(id, date, cat) {
  const f = (window._frags || {})[id];
  if (!f) return;
  openModal(`工作记录详情 · ${date}`,
    `<div class="meta-grid">
       <span class="k">分类</span><span><span class="tag">${esc(f.category)}</span></span>
       <span class="k">发生日期</span><span>${esc(f.occurred_at)}</span>
       <span class="k">记录编号</span><span>#${f.id}</span>
     </div>
     <div class="detail-label">记录内容</div>
     <div class="md-pre">${esc(f.content)}</div>
     <p style="color:var(--muted);font-size:11px;margin-top:10px">提示：保存到知识库的周报会包含本条内容；删除前请确认周报是否已归档。</p>`);
}

async function delFrag(id) {
  if (!confirm('确认删除这条记录？')) return;
  try { await api(`/api/weekly/fragments/${id}`, { method: 'DELETE' }); toast('已删除'); loadRecords(); }
  catch (e) { toast(e.message); }
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
  try {
    const d = await api('/api/weekly/fragments', { method: 'POST', json: { content: c, category: $('w-cat').value, occurred_at: $('w-date').value } });
    toast(d.ok ? `已记录（分类：${d.category}）` : d.error); $('w-content').value = '';
  } catch (e) { toast(e.message); }
}

async function renderReport() {
  const s = $('w-start').value; if (!s) return toast('请选择周起始日期');
  try {
    const d = await api('/api/weekly/report', { method: 'POST', json: { start_date: s } });
    if (!d.ok) return toast(d.error);
    lastReport = d; $('weekly-out').style.display = 'block'; $('weekly-out').textContent = d.report_markdown;
    $('archive-btn').disabled = false;
  } catch (e) { toast(e.message); }
}

async function archiveReport() {
  if (!lastReport) return;
  try {
    const d = await api('/api/weekly/archive', { method: 'POST', json: { title: '辅导员工作周报', start_date: lastReport.start_date, end_date: lastReport.end_date, content_md: lastReport.report_markdown } });
    toast(d.ok ? '已归档：' + d.file : d.error); $('archive-btn').disabled = true; loadArchived();
  } catch (e) { toast(e.message); }
}
