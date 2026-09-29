/* P4b C5/C6: 左侧会话栏 —— 列表/新建/切换/重命名/删除/归档开关 + 上下文占用条。
   会话可见性一律后端按 user_id 过滤;前端不做任何权限判断(C2 延续)。 */
window._convId = null;     // 当前会话 id(null = 未持久化的新会话,首问后由后端自动建)
window._convAbort = null;  // 进行中 SSE 的中止器(P4b C5: 切换会话即中止)

async function loadConversations() {
  try {
    const showArch = document.getElementById('conv-show-archived')?.checked;
    const d = await api('/api/conversations' + (showArch ? '?include_archived=true' : ''));
    const ul = document.getElementById('conv-list');
    if (!ul) return;
    ul.innerHTML = (d.conversations || []).map(c =>
      `<li data-cid="${c.id}" class="${c.id === window._convId ? 'sel' : ''}${c.archived ? ' arch' : ''}">` +
      `<span class="ct" onclick="switchConversation(${c.id})" title="${esc(c.title)}">${esc(c.title)}</span>` +
      `<span class="ops">` +
      `<a href="javascript:void(0)" onclick="renameConversation(${c.id}, '${esc(c.title)}')">改名</a>` +
      `<a href="javascript:void(0)" onclick="archiveConversation(${c.id}, ${c.archived ? 0 : 1})">${c.archived ? '恢复' : '归档'}</a>` +
      `<a href="javascript:void(0)" class="del" onclick="deleteConversation(${c.id})">删</a>` +
      `</span></li>`
    ).join('') || '<li class="empty">—</li>';
  } catch (e) { toast('会话列表加载失败:' + e.message); }
}

const WELCOME_HINT = '知识库问答自动检索并标注引用 [n]；「记一条碎片…」「生成本周周报」会触发周报工具；右下角可切换模型与账户设置。';

function newConversation() {
  abortInflight();
  window._convId = null;
  document.getElementById('messages').innerHTML = `<div class="hint">${WELCOME_HINT}</div>`;
  const bar = document.getElementById('ctx-bar');
  if (bar) bar.style.display = 'none';  // 新会话尚无占用数据
  loadConversations();
}

async function switchConversation(cid) {
  if (cid === window._convId) return;
  abortInflight();  // P4b C5: 切走即中止进行中的 SSE(服务端生成器随之取消,不落库)
  window._convId = cid;
  const bar = document.getElementById('ctx-bar');
  if (bar) bar.style.display = 'none';  // 占用条随会话切换清空(下一轮回答时按事件重建)
  try {
    const d = await api(`/api/conversations/${cid}/messages?limit=200`);
    const box = document.getElementById('messages');
    box.innerHTML = '';
    for (const m of d.messages) addMsg(m.role === 'user' ? 'user' : 'bot', m.content);
    box.scrollTop = box.scrollHeight;
  } catch (e) { toast('会话消息加载失败:' + e.message); }
  loadConversations();
}

async function renameConversation(cid, oldTitle) {
  const t = prompt('重命名会话', oldTitle || '');
  if (t === null) return;
  try { await api(`/api/conversations/${cid}`, { method: 'PATCH', json: { title: t } }); } catch (e) { toast(e.message); return; }
  loadConversations();
}

async function archiveConversation(cid, toArchived) {
  try { await api(`/api/conversations/${cid}`, { method: 'PATCH', json: { archived: !!toArchived } }); }
  catch (e) { toast(e.message); return; }
  loadConversations();
}

async function deleteConversation(cid) {
  if (!confirm('删除该会话及其全部消息?')) return;
  try {
    const d = await api(`/api/conversations/${cid}`, { method: 'DELETE' });
    toast(`已删除(${d.messages_deleted} 条消息)`);
  } catch (e) { toast(e.message); return; }
  if (cid === window._convId) {
    abortInflight();
    window._convId = null;
    document.getElementById('messages').innerHTML = `<div class="hint">${WELCOME_HINT}</div>`;
  }
  loadConversations();
}

function abortInflight() {
  if (window._convAbort) { try { window._convAbort.abort(); } catch (e) { /* 已结束 */ } window._convAbort = null; }
}

function updateCtxBar(ev) {
  const bar = document.getElementById('ctx-bar');
  if (!bar || !ev) return;
  bar.style.display = 'flex';
  const budget = ev.budget || 1;
  const pct = Math.min(100, Math.round((ev.used || 0) / budget * 100));
  const fill = document.getElementById('ctx-fill');
  fill.style.width = pct + '%';
  fill.className = ev.truncated ? 'truncated' : (ev.compressed ? 'compressed' : (pct > 85 ? 'hot' : ''));
  document.getElementById('ctx-text').textContent =
    `上下文 ${pct}%（${ev.used || 0}/${budget} tok 估算）` +
    (ev.compressed ? ' · 已压缩' : '') + (ev.truncated ? ' · 已截断' : '');
}
