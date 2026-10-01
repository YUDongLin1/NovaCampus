/* P4f C3/C4: 辅导星人设(左侧会话栏内的选择器)。
 *
 * 【职责边界】
 *   本文件只管「选谁 / 建谁 / 切谁」。**可见性判断一律在后端**——
 *   前端不做任何权限判断(P4b C2 起的延续:同一判据只应有一处权威实现)。
 *   列表接口返回什么就渲染什么,拿不到就是拿不到,不在前端猜。
 *
 * 【与 conversation 的关系】
 *   persona 挂在会话上(conversations.persona_id),但**每轮请求都显式带 persona_id**:
 *   只靠会话绑定的话,「首次提问前先选人设」这条路径就落不了地(会话还不存在)。
 *   显式带上之后,新建会话与已有会话两条路径口径一致。
 */
window._personas = [];        // 后端返回的可见人设(原样缓存,不做客户端过滤)
window._personaId = null;     // 当前选择(null = 不用人设,走默认助手)
window._personaEditId = null; // 正在编辑的人设 id(新建时为 null)

const STYLE_ZH = {
  concise: '简洁', balanced: '条理清晰', detailed: '详尽', warm: '亲和', formal: '正式'
};
const VIS_ZH = { private: '仅自己', public: '学生可见' };

function personaById(pid) {
  return (window._personas || []).find(p => p.id === +pid) || null;
}

/** 当前人设对象;已软删除的历史会话会拿到 null,此时按「人设已删除」显示。 */
function currentPersona() {
  return window._personaId ? personaById(window._personaId) : null;
}

/** 人设的展示名:已删除/不可见一律「人设已删除」,不区分原因(不泄露存在性)。 */
function personaLabel(pid) {
  if (!pid) return '';
  const p = personaById(pid);
  return p ? p.name : '人设已删除';
}

async function loadPersonas() {
  try {
    const d = await api('/api/personas');
    window._personas = d.personas || [];
  } catch (e) {
    window._personas = [];
    toast('人设列表加载失败：' + e.message);
  }
  renderPersonaBar();
}

/** 渲染左侧栏里的选择器行。 */
function renderPersonaBar() {
  const box = $('persona-bar');
  if (!box) return;
  const list = window._personas || [];
  // 学生没有建/改权限,选择器降级为纯展示 + 一点说明,不给"管理"入口制造错觉
  const canManage = isStaff();
  if (!list.length) {
    box.innerHTML = canManage
      ? `<div class="persona-empty">还没有辅导星人设</div>
         <button class="btn ghost sm" onclick="openPersonaEditor()">＋ 建一个人设</button>`
      : `<div class="persona-empty">暂无可用辅导星人设</div>`;
    return;
  }
  box.innerHTML =
    `<select id="persona-select" onchange="onPersonaPick(this.value)">` +
      `<option value="">默认助手（无 人设）</option>` +
      list.map(p =>
        `<option value="${p.id}"${p.id === window._personaId ? ' selected' : ''}>` +
        `${esc(p.name)}${p.is_default ? '（默认）' : ''}${p.college ? ' · ' + esc(p.college) : ''}` +
        `</option>`).join('') +
    `</select>` +
    (canManage
      ? `<button class="icon-btn" title="新建人设" onclick="openPersonaEditor()">＋</button>` +
        (window._personaId
          ? `<button class="icon-btn" title="编辑当前人设" onclick="openPersonaEditor(window._personaId)">✎</button>`
          : '')
      : `<span class="persona-lock" title="人设由辅导员维护">🔒</span>`);
}

function onPersonaPick(v) {
  window._personaId = v ? +v : null;
  applyPersonaToConversation();
  renderPersonaHint();
}

/** 把当前选择落到会话上。会话还没建(首问前)时无事可做,靠请求体里的 persona_id 生效。 */
async function applyPersonaToConversation() {
  const cid = window._convId;
  if (!cid) return;
  try {
    await api(`/api/conversations/${cid}`, {
      method: 'PATCH',
      json: { persona_id: window._personaId }
    });
  } catch (e) {
    // 人设不可见(404)在这里是**预期**表现:切到别人私有的人设会被拒。
    // 不弹错误刷屏,只把选择回滚成后端认可的值。
    toast('该人设不可用：' + e.message);
    await loadPersonas();
    if (window._convId) syncPersonaFromConversation(window._convId);
  }
}

function renderPersonaHint() {
  const el = $('persona-hint');
  if (!el) return;
  const p = currentPersona();
  if (!p) { el.textContent = ''; el.style.display = 'none'; return; }
  const bits = [STYLE_ZH[p.style] || p.style];
  if (p.bound_folder_ids && p.bound_folder_ids.length) bits.push(`绑定 ${p.bound_folder_ids.length} 个文件夹`);
  if (p.bound_categories && p.bound_categories.length) bits.push(`分类：${p.bound_categories.join('、')}`);
  el.textContent = bits.join(' · ');
  el.style.display = 'block';
}

/** 切会话时把选择器对齐到该会话绑定的 persona(不同步就会"张冠李戴")。 */
async function syncPersonaFromConversation(cid) {
  const sel = $('persona-select');
  if (!sel) return;
  let target = null;
  try {
    const d = await api('/api/conversations?include_archived=true&limit=200');
    const c = (d.conversations || []).find(x => x.id === +cid);
    target = (c && c.persona_id) || null;
  } catch (e) { /* 列表拉不到就保持当前选择,不猜 */ }
  window._personaId = target;
  sel.value = target ? String(target) : '';
  renderPersonaHint();
}

/* ==================== 人设管理(仅辅导员/管理员) ==================== */

function openPersonaEditor(pid) {
  window._personaEditId = pid || null;
  const p = pid ? personaById(pid) : null;
  openModal(p ? `编辑人设 · ${p.name}` : '新建辅导星人设', `
    <div class="detail-label">显示名<span class="req">*</span></div>
    <div class="row"><input id="pf-name" maxlength="40" value="${esc(p ? p.name : '')}" placeholder="如：张老师"></div>
    <div class="detail-label">所属学院</div>
    <div class="row"><input id="pf-college" maxlength="40" value="${esc(p ? p.college : '')}" placeholder="如：信息学院（选填）"></div>
    <div class="detail-label">回复风格</div>
    <div class="row"><select id="pf-style">
      ${Object.keys(STYLE_ZH).map(k =>
        `<option value="${k}"${p && p.style === k ? ' selected' : ''}>${STYLE_ZH[k]}</option>`).join('')}
    </select></div>
    <div class="detail-label">人设补充（只影响语气与侧重点，<b>不能覆盖回答规则</b>）</div>
    <div class="row"><textarea id="pf-prompt" maxlength="2000"
      placeholder="如：语气耐心，先安抚情绪再给流程；涉及心理危机时优先 suggest 转介心理中心。">${esc(p ? p.persona_prompt : '')}</textarea></div>
    <div class="detail-label">可见性</div>
    <div class="row"><select id="pf-vis">
      <option value="private"${!p || p.visibility === 'private' ? ' selected' : ''}>仅自己</option>
      <option value="public"${p && p.visibility === 'public' ? ' selected' : ''}>学生可见</option>
    </select></div>
    <div class="detail-label">绑定知识库文件夹（可选，缩小检索范围）</div>
    <div class="row"><div id="pf-folders" class="pf-folders">加载中…</div></div>
    <p class="pf-tip">绑定范围只是"缩小检索范围"，<b>不会扩大权限</b>：实际检索范围永远与你的可见范围取交集。</p>
    <div class="row" style="margin-top:14px">
      <button class="btn" onclick="savePersona()">保存</button>
      ${p ? `<button class="btn danger-ghost" onclick="removePersona(${p.id})">删除</button>` : ''}
      <button class="btn ghost" onclick="closeModal()">取消</button>
    </div>
    <p id="pf-err" class="pf-err"></p>`);
  loadPersonaFolders(p ? (p.bound_folder_ids || []) : []);
}

async function loadPersonaFolders(sel) {
  const box = $('pf-folders');
  if (!box) return;
  let folders = [];
  try { folders = (await api('/api/kb/folders')).folders || []; }
  catch (e) { box.innerHTML = '<span class="pf-err">文件夹列表加载失败</span>'; return; }
  if (!folders.length) { box.innerHTML = '<span class="persona-empty">没有可选文件夹</span>'; return; }
  box.innerHTML = folders.map(f =>
    `<label class="pf-folder"><input type="checkbox" value="${f.id}"${sel.includes(f.id) ? ' checked' : ''}>` +
    `${esc(f.name)}<span class="pf-folder-n">${f.doc_count}</span></label>`).join('');
}

function pickedFolders() {
  return Array.from(document.querySelectorAll('#pf-folders input:checked')).map(x => +x.value);
}

async function savePersona() {
  const body = {
    name: $('pf-name').value.trim(),
    college: $('pf-college').value.trim(),
    style: $('pf-style').value,
    persona_prompt: $('pf-prompt').value.trim(),
    visibility: $('pf-vis').value,
    bound_folder_ids: pickedFolders()
  };
  if (!body.name) { $('pf-err').textContent = '显示名必填'; return; }
  try {
    if (window._personaEditId) {
      await api(`/api/personas/${window._personaEditId}`, { method: 'PATCH', json: body });
      toast('已保存');
    } else {
      const d = await api('/api/personas', { method: 'POST', json: body });
      window._personaId = d.persona.id;
      toast('已创建');
    }
  } catch (e) { $('pf-err').textContent = e.message; return; }
  closeModal();
  await loadPersonas();
  renderPersonaHint();
  await applyPersonaToConversation();
}

async function removePersona(pid) {
  if (!confirm('删除该人设？已用它创建的会话会保留，标记为「人设已删除」。')) return;
  try {
    await api(`/api/personas/${pid}`, { method: 'DELETE' });
  } catch (e) { $('pf-err').textContent = e.message; return; }
  closeModal();
  if (window._personaId === +pid) window._personaId = null;
  await loadPersonas();
  renderPersonaHint();
  loadConversations();
}
