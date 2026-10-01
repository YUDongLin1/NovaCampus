/* P5-2 辅导员（人设）页面:列表卡片 / 搜索 / 选用 / 详情。
 *
 * 【职责边界(与 persona.js 的分工)】
 *   persona.js  = 会话里的**选择器**与**编辑弹窗**(单一实现,本页复用它,不另写一套表单)。
 *   本文件      = 列表页的**呈现与入口**:卡片网格、纯前端搜索、选用、只读详情。
 *   「谁能看到谁」一律由后端 `/api/personas` 决定,本页只渲染它返回的东西
 *   (P4b C2 / P4f 的延续:同一判据只应有一处权威实现)。
 *
 * 【学生只读位】
 *   学生看到的是后端脱敏后的 public 人设卡,只有「用这个人设开会话」,
 *   没有新建/编辑/删除入口(后端对 student 的写操作本就是 403 —— 两层都要)。
 */
async function loadPersonaPage() {
  await loadPersonas();          // 复用 persona.js 的拉取与缓存(不另写一份请求)
  renderPersonaCards();
}

function personaScopeText(p) {
  const bits = [];
  const nf = (p.bound_folder_ids || []).length;
  const nc = (p.bound_categories || []).length;
  if (nf) bits.push(`绑定 ${nf} 个文件夹`);
  if (nc) bits.push(`分类：${(p.bound_categories || []).join('、')}`);
  return bits.length ? bits.join(' · ') : '全库';
}

function personaMatches(p, q) {
  if (!q) return true;
  const s = q.trim().toLowerCase();
  if (!s) return true;
  // 纯前端过滤(按名称/学院),**不发请求** —— 库就这么大,没必要每敲一个字打一次接口
  return (p.name || '').toLowerCase().indexOf(s) >= 0
      || (p.college || '').toLowerCase().indexOf(s) >= 0;
}

function personaCardHtml(p) {
  const canManage = isStaff();
  const mine = canManage && (ME && (p.owner_id === ME.id || ME.role === 'admin'));
  const using = window._personaId && p.id === window._personaId;
  const vis = p.visibility === 'public' ? '全校可用' : '仅自己';
  return `<div class="pcard${using ? ' using' : ''}">
    <div class="pcard-av">${avatarSvg(p.avatar, 52)}</div>
    <div class="pcard-body">
      <div class="pcard-name">${esc(p.name)}${p.is_default ? '<span class="pcard-tag def">默认</span>' : ''}${using ? '<span class="pcard-tag using">使用中</span>' : ''}</div>
      <div class="pcard-meta">${esc(p.college || '未填学院')} · ${STYLE_ZH[p.style] || p.style}</div>
      <div class="pcard-meta">${esc(personaScopeText(p))}</div>
      <div class="pcard-meta vis">${vis}</div>
    </div>
    <div class="pcard-acts">
      <button class="btn ghost sm" onclick="usePersonaForChat(${p.id})">用这个人设开会话</button>
      ${mine ? `<button class="icon-btn" title="编辑" onclick="openPersonaEditor(${p.id})">✎</button>` : ''}
      ${canManage ? `<button class="btn ghost sm" onclick="openPersonaDetail(${p.id})">详情</button>` : ''}
    </div>
  </div>`;
}

function renderPersonaCards() {
  const box = $('persona-grid');
  if (!box) return;
  const list = (window._personas || []).filter(p => personaMatches(p, $('persona-search') ? $('persona-search').value : ''));
  const sub = $('personas-sub');
  if (sub) {
    sub.textContent = isStaff()
      ? `共 ${(window._personas || []).length} 个人设${list.length !== (window._personas || []).length ? `（筛出 ${list.length}）` : ''}`
      : '学生只读：可用的人设由辅导员维护，选一个即可开始提问';
  }
  if (!list.length) {
    box.innerHTML = `<div class="persona-empty">${(window._personas || []).length
      ? '没有匹配的人设' : (isStaff() ? '还没有人设，点右上角「＋ 新建人设」' : '暂无可用人设')}</div>`;
    return;
  }
  box.innerHTML = list.map(personaCardHtml).join('');
}

/** 选用 → 开一个新会话 → 落到会话页。人设**跟着请求走**(chat.js 每轮带 persona_id),
 *  所以「先选人设再提问」这条路径不依赖会话已存在。 */
function usePersonaForChat(pid) {
  window._personaId = +pid;
  newConversation();          // 复用既有语义:不清空人设选择,只重置会话
  navigate('chat');
  const p = personaById(pid);
  toast(p ? `已选用「${p.name}」` : '已选用该人设');
}

/** 详情(只读)。非作者拿不到 persona_prompt(后端已置空),这里**不显示也不给占位提示**
 *  —— 提示「此处内容对你隐藏」本身就是一种存在性披露(P5 §3.4)。 */
function openPersonaDetail(pid) {
  const p = personaById(pid);
  if (!p) { toast('该人设不可见'); return; }
  const mine = ME && (p.owner_id === ME.id || ME.role === 'admin');
  const av = avatarSvg(p.avatar, 56);
  const rows = [
    ['头像', av],
    ['名称', esc(p.name)],
    ['学院', esc(p.college || '—')],
    ['风格', STYLE_ZH[p.style] || p.style],
    ['可见性', p.visibility === 'public' ? '全校可用' : '仅自己'],
    ['检索范围', esc(personaScopeText(p))],
    ['默认人设', p.is_default ? '是' : '否'],
  ];
  const promptRow = (mine && p.persona_prompt)
    ? `<div class="detail-label">人设补充</div><div class="pcard-read">${esc(p.persona_prompt)}</div>`
    : '';
  openModal(`人设详情 · ${esc(p.name)}`,
    `<div class="pd-head">${av}<div><div class="pd-name">${esc(p.name)}</div>
      <div class="pd-sub">${esc(p.college || '未填学院')} · ${STYLE_ZH[p.style] || p.style}</div></div></div>
     ${rows.filter(r => r[0] !== '头像').map(r =>
       `<div class="detail-label">${r[0]}</div><div class="pcard-read">${r[1]}</div>`).join('')}
     ${promptRow}
     <div class="row" style="margin-top:14px">
       ${mine ? `<button class="btn" onclick="openPersonaEditor(${p.id})">编辑</button>` : ''}
       <button class="btn ghost" onclick="closeModal()">关闭</button>
     </div>`);
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = { personaScopeText, personaMatches };
}
