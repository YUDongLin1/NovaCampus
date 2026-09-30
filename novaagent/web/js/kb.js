/* P4c: KB 页改造——文件夹树 + 文档列表(移动/学段标注/批量) + @ 选择器数据源。
   沿用「学术水墨 × 朱砂印」主题变量,零新依赖;权限判断一律后端(前端不新增权限逻辑)。 */

const AUD_ZH = { common: '通用', undergrad: '本科', postgrad: '研究生' };
window._kbFolders = [];
window._kbDocs = [];

async function loadFolders() {
  try {
    const d = await api('/api/kb/folders');
    window._kbFolders = d.folders || [];
  } catch (e) { window._kbFolders = []; }
  renderFolderTree();
  fillFolderSelects();
  const nb = $('kb-new-folder');
  if (nb) nb.style.display = isStaff() ? '' : 'none';
  if (window._atRefresh) window._atRefresh();
}

function folderDepth(f) {
  let depth = 0, cur = f;
  while (cur && cur.parent_id) { depth++; cur = window._kbFolders.find(x => x.id === cur.parent_id) || {}; }
  return depth;
}

function fillFolderSelects() {
  const fs = window._kbFolders;
  const ff = $('kb-folder-filter');
  if (ff) {
    const cur = ff.value || '';
    ff.innerHTML = ['<option value="">全部位置</option>',
      '<option value="root">根目录（未归类）</option>']
      .concat(fs.map(f => `<option value="${f.id}">${'　'.repeat(folderDepth(f))}${esc(f.name)}（${f.doc_count}）</option>`)).join('');
    ff.value = cur;
    if (ff.selectedIndex === -1) ff.value = '';
  }
  const up = $('up-folder');
  if (up) {
    const ucur = up.value || '';
    up.innerHTML = ['<option value="">根目录</option>']
      .concat(fs.map(f => `<option value="${f.id}">${'　'.repeat(folderDepth(f))}${esc(f.name)}</option>`)).join('');
    up.value = ucur;
  }
}

function renderFolderTree() {
  const el = $('folder-tree'); if (!el) return;
  const staff = isStaff();
  const canManage = f => staff && (ME.role === 'admin' || f.owner_id === ME.id);
  const items = [];
  const cur = String($('kb-folder-filter') ? $('kb-folder-filter').value : '');
  items.push(`<div class="folder-item ${cur === '' ? 'active' : ''}" onclick="pickFolder('')"><span class="f-ico">🗂️</span> 全部文档</div>`);
  items.push(`<div class="folder-item ${cur === 'root' ? 'active' : ''}" onclick="pickFolder('root')"><span class="f-ico">📄</span> 根目录（未归类）</div>`);
  window._kbFolders.forEach(f => {
    const acts = canManage(f)
      ? `<span class="f-acts"><button class="link" onclick="event.stopPropagation();renameFolder(${f.id})">改名</button>`
        + `<button class="link del" onclick="event.stopPropagation();delFolder(${f.id})">删除</button></span>`
      : '';
    items.push(`<div class="folder-item ${cur === String(f.id) ? 'active' : ''}"
      style="margin-left:${folderDepth(f) * 16}px" onclick="pickFolder(${f.id})">
      <span class="f-ico">📁</span> ${esc(f.name)} <span class="f-count">${f.doc_count}</span>${acts}</div>`);
  });
  el.innerHTML = items.join('');
}

function pickFolder(v) {
  $('kb-folder-filter').value = v;
  loadDocs();
}

async function loadDocs() {
  try {
    await loadFolders();
    const cat = $('kb-cat-filter').value;
    const fid = $('kb-folder-filter').value;
    const aud = $('kb-audience-filter') ? $('kb-audience-filter').value : '';
    const qs = new URLSearchParams();
    if (cat) qs.set('category', cat);
    if (fid) qs.set('folder_id', fid);
    if (aud) qs.set('audience', aud);
    const d = await api('/api/kb/documents' + (qs.toString() ? '?' + qs.toString() : ''));
    const cats = [...new Set([...(d.categories || []), '其他'])];
    const cur = $('kb-cat-filter').value;
    $('kb-cat-filter').innerHTML = '<option value="">全部分类</option>' + cats.map(c => `<option ${c === cur ? 'selected' : ''}>${c}</option>`).join('');
    window._kbDocs = d.documents || [];
    const staff = isStaff();
    $('docs').innerHTML = window._kbDocs.length ? window._kbDocs.map(x => `
      <tr>
        <td class="t-title">${staff ? `<input type="checkbox" class="doc-check" value="${x.id}" onchange="syncBatchBar()"> ` : ''}${esc(x.title)}<br>
          <span class="tag cat">${esc(x.category || '其他')}</span>
          <span class="tag aud aud-${x.audience || 'common'}">${AUD_ZH[x.audience || 'common']}</span>
          <span style="color:var(--muted);font-size:11px">${esc(x.uploaded_by)} · ${(x.created_at || '').slice(0, 10)}</span></td>
        <td><span class="tag ${x.role_min}">${{student:'全体',counselor:'辅导员+',admin:'仅管理'}[x.role_min]}</span></td>
        <td>${x.chunk_count}</td>
        <td style="white-space:nowrap">
          <button class="link" onclick="viewDoc(${x.id})">查看</button>
          ${staff ? `<button class="link" onclick="moveDocModal([${x.id}])">移动</button>
                     <button class="link del" onclick="delDoc(${x.id})">删除</button>` : ''}
        </td>
      </tr>`).join('') : '<tr><td colspan="4" class="empty">当前位置没有文档</td></tr>';
    syncBatchBar();
  } catch (e) { toast(e.message); }
}

async function viewDoc(id) {
  try {
    const d = await api(`/api/kb/documents/${id}/chunks`);
    openModal(`《${d.document.title}》`,
      `<div class="meta-grid">
         <span class="k">分类</span><span><span class="tag cat">${esc(d.document.category || '其他')}</span></span>
         <span class="k">可见级别</span><span>${ROLE_ZH[d.document.role_min] || d.document.role_min}及以上</span>
         <span class="k">学段</span><span>${AUD_ZH[d.document.audience || 'common'] || '通用'}</span>
         <span class="k">位置</span><span>${esc(folderName(d.document.folder_id))}</span>
         <span class="k">上传</span><span>${esc(d.document.uploaded_by)} · ${(d.document.created_at || '').slice(0, 10)}</span>
         <span class="k">分块数</span><span>${d.chunks.length}</span>
       </div>` +
      (d.document.summary ? `<div class="detail-label">AI 摘要</div><div class="chunk" style="background:#f0f7ff;border-color:#cfe0fb">${esc(d.document.summary)}</div>` : '') +
      d.chunks.map(c => `<div class="chunk"><div class="cid">分块 #${c.idx + 1}</div>${esc(c.content)}</div>`).join(''));
  } catch (e) { toast(e.message); }
}

function folderName(fid) {
  if (fid === null || fid === undefined) return '根目录';
  const f = window._kbFolders.find(x => x.id === fid);
  return f ? f.name : ('文件夹 #' + fid);
}

async function delDoc(id) {
  const doc = window._kbDocs.find(x => x.id === id);
  if (!confirm(`确认删除文档《${doc ? doc.title : '#' + id}》及其全部分块？`)) return;
  try { await api(`/api/kb/documents/${id}`, { method: 'DELETE' }); toast('已删除'); loadDocs(); }
  catch (e) { toast(e.message); }
}

/* ---------- 批量与移动(C2) ---------- */

function checkedIds() { return [...document.querySelectorAll('.doc-check:checked')].map(x => +x.value); }
function syncBatchBar() {
  const bar = $('batch-bar'); if (!bar) return;
  const n = checkedIds().length;
  bar.style.display = n ? 'flex' : 'none';
  const bn = $('batch-n'); if (bn) bn.textContent = n;
}

function moveDocModal(ids) {
  const arr = Array.isArray(ids) ? ids : [ids];
  if (!arr.length) return toast('请先勾选文档');
  window._mvIds = arr;
  const opts = ['<option value="">根目录（未归类）</option>']
    .concat(window._kbFolders.map(f => `<option value="${f.id}">${esc(f.name)}</option>`)).join('');
  openModal(`移动 ${arr.length} 篇文档`,
    `<select id="mv-folder" style="width:100%">${opts}</select>
     <button class="btn" style="margin-top:12px;width:100%" onclick="doMove()">移动</button>`);
}

async function doMove() {
  try {
    const sel = $('mv-folder').value;
    const d = await api('/api/kb/documents/move', { method: 'POST',
      json: { doc_ids: window._mvIds, folder_id: sel === '' ? null : +sel } });
    closeModal(); toast(`已移动 ${d.moved} 篇`); loadDocs();
  } catch (e) { toast(e.message); }
}

async function batchAudience(aud) {
  const ids = checkedIds(); if (!ids.length) return toast('请先勾选文档');
  try {
    for (const id of ids) await api(`/api/kb/documents/${id}`, { method: 'PATCH', json: { audience: aud } });
    toast('已标注学段'); loadDocs();
  } catch (e) { toast(e.message); }
}

/* ---------- 文件夹 CRUD(C2) ---------- */

function newFolder() {
  if (!isStaff()) return;
  const parent = $('kb-folder-filter').value;
  const pid = (parent === '' || parent === 'root') ? 'null' : parent;
  openModal('新建文件夹', `
    <input id="nf-name" placeholder="文件夹名称" style="width:100%">
    <select id="nf-vis" style="width:100%;margin-top:10px">
      <option value="private">仅自己可见</option>
      <option value="student">全体可见</option>
      <option value="counselor">辅导员+</option>
      <option value="admin">仅管理员</option>
    </select>
    <button class="btn" style="margin-top:12px;width:100%" onclick="createFolderSubmit(${pid})">创建</button>`);
}

async function createFolderSubmit(parentId) {
  const pid = (parentId === 'null' || parentId === undefined || parentId === null) ? null : +parentId;
  try {
    await api('/api/kb/folders', { method: 'POST', json: {
      name: $('nf-name').value.trim(),
      parent_id: pid,
      visibility: $('nf-vis').value } });
    closeModal(); toast('文件夹已创建'); loadDocs();
  } catch (e) { toast(e.message); }
}

async function renameFolder(id) {
  const f = window._kbFolders.find(x => x.id === id);
  const name = prompt('新的文件夹名称', f ? f.name : '');
  if (!name || !name.trim()) return;
  try { await api(`/api/kb/folders/${id}`, { method: 'PATCH', json: { name: name.trim() } }); toast('已改名'); loadDocs(); }
  catch (e) { toast(e.message); }
}

async function delFolder(id) {
  if (!confirm('删除该文件夹？其下文档将移回根目录（不会被删除）。')) return;
  try { await api(`/api/kb/folders/${id}?cascade=true`, { method: 'DELETE' }); toast('文件夹已删除'); loadDocs(); }
  catch (e) { toast(e.message); }
}

/* ---------- 上传/导入(C5: 标注文件夹与学段) ---------- */

async function upload() {
  const f = $('f').files[0]; if (!f) return toast('请选择文件');
  const fd = new FormData();
  fd.append('file', f); fd.append('role_min', $('vis').value); fd.append('category', $('up-cat').value);
  fd.append('audience', $('up-audience').value);
  if ($('up-folder').value) fd.append('folder_id', $('up-folder').value);
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
