/* P4b-0 拆分:本文件内容由 index.html 原样迁移(零修改),行为零变化。 */
// 知识库:列表/筛选/分块查看/删除/上传/网页导入

async function loadDocs() {
  try {
    const cat = $('kb-cat-filter').value;
    const d = await api('/api/kb/documents' + (cat ? '?category=' + encodeURIComponent(cat) : ''));
    const cats = [...new Set([...(d.categories || []), '其他'])];
    const cur = $('kb-cat-filter').value;
    $('kb-cat-filter').innerHTML = '<option value="">全部分类</option>' + cats.map(c => `<option ${c === cur ? 'selected' : ''}>${c}</option>`).join('');
    $('docs').innerHTML = d.documents.length ? d.documents.map(x => `
      <tr>
        <td class="t-title">${esc(x.title)}<br>
          <span class="tag cat">${esc(x.category || '其他')}</span>
          <span style="color:var(--muted);font-size:11px">${esc(x.uploaded_by)} · ${(x.created_at || '').slice(0, 10)}</span></td>
        <td><span class="tag ${x.role_min}">${{student:'全体',counselor:'辅导员+',admin:'仅管理'}[x.role_min]}</span></td>
        <td>${x.chunk_count}</td>
        <td style="white-space:nowrap">
          <button class="link" onclick="viewDoc(${x.id})">查看</button>
          ${isStaff() ? `<button class="link del" onclick="delDoc(${x.id},'${esc(x.title)}')">删除</button>` : ''}
        </td>
      </tr>`).join('') : '<tr><td colspan="4" class="empty">暂无文档</td></tr>';
  } catch (e) { toast(e.message); }
}

async function viewDoc(id) {
  try {
    const d = await api(`/api/kb/documents/${id}/chunks`);
    openModal(`《${d.document.title}》`,
      `<div class="meta-grid">
         <span class="k">分类</span><span><span class="tag cat">${esc(d.document.category || '其他')}</span></span>
         <span class="k">可见级别</span><span>${ROLE_ZH[d.document.role_min] || d.document.role_min}及以上</span>
         <span class="k">上传</span><span>${esc(d.document.uploaded_by)} · ${(d.document.created_at || '').slice(0, 10)}</span>
         <span class="k">分块数</span><span>${d.chunks.length}</span>
       </div>` +
      (d.document.summary ? `<div class="detail-label">AI 摘要</div><div class="chunk" style="background:#f0f7ff;border-color:#cfe0fb">${esc(d.document.summary)}</div>` : '') +
      d.chunks.map(c => `<div class="chunk"><div class="cid">分块 #${c.idx + 1}</div>${esc(c.content)}</div>`).join(''));
  } catch (e) { toast(e.message); }
}

async function delDoc(id, title) {
  if (!confirm(`确认删除文档《${title}》及其全部分块？`)) return;
  try { await api(`/api/kb/documents/${id}`, { method: 'DELETE' }); toast('已删除'); loadDocs(); }
  catch (e) { toast(e.message); }
}

async function upload() {
  const f = $('f').files[0]; if (!f) return toast('请选择文件');
  const fd = new FormData(); fd.append('file', f); fd.append('role_min', $('vis').value); fd.append('category', $('up-cat').value);
  try { const d = await api('/api/kb/upload', { method: 'POST', body: fd }); toast(`已解析 ${d.chunks} 个分块，摘要已生成`); loadDocs(); }
  catch (e) { toast('上传失败：' + e.message); }
}

async function importUrl() {
  const url = $('page-url').value.trim(); if (!url) return toast('请输入网页链接');
  const btn = event.target; btn.disabled = true; btn.textContent = '抓取中…';
  try {
    const d = await api('/api/kb/import_url', { method: 'POST', json: { url, role_min: $('vis').value, category: $('up-cat').value } });
    toast(`已导入《${d.title}》：${d.chunks} 个分块，摘要已生成`);
    $('page-url').value = ''; loadDocs();
  } catch (e) { toast('导入失败：' + e.message); }
  btn.disabled = false; btn.textContent = '导入网页';
}
