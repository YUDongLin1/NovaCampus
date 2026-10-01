/* P4b C5/C6: 左侧会话栏 —— 列表/新建/切换/重命名/删除/归档开关 + 上下文占用条。
   P4f: 列表项带出人设徽标;切会话时把 persona 选择器对齐到该会话(见 persona.js)。
   会话可见性一律后端按 user_id 过滤;前端不做任何权限判断(C2 延续)。 */
window._convId = null;     // 当前会话 id(null = 未持久化的新会话,首问后由后端自动建)
window._convAbort = null;  // 进行中 SSE 的中止器(P4b C5: 切换会话即中止)

const DAY_MS = 86400000;

/** 「现在」取**服务端时间**(api.js 从 HTTP Date 头记下);拿不到才退回本地。 */
function serverNowMs() {
  return window._serverNowMs || Date.now();
}

/** 按服务端时间把会话分三组(纯函数,自测直接调用;不碰 DOM、不发请求)。
 *
 *  ⚠ 边界一律按 **UTC 日历日**算:库里的 `updated_at` 是 `datetime.now(timezone.utc)
 *  .isoformat()`(带 +00:00),而"现在"用的是服务端 Date 头(也是 UTC)。
 *  若改用浏览器本地时区取「今天零点」,演示机时区一换,同一份数据会分到不同的组
 *  —— 飘的是**展示**不是数据,排障时最难查(P5 §3.2 点名这条)。
 */
function groupConversations(list, nowMs) {
  const now = Number(nowMs) || Date.now();
  const today0 = Math.floor(now / DAY_MS) * DAY_MS;   // UTC 当日零点
  const out = { today: [], week: [], earlier: [] };
  for (const c of (list || [])) {
    const t = Date.parse(c.updated_at || c.created_at || '');
    if (!t) { out.earlier.push(c); continue; }        // 解析不出就归到最早一组,不丢
    if (t >= today0) out.today.push(c);
    else if (t >= today0 - 7 * DAY_MS) out.week.push(c);
    else out.earlier.push(c);
  }
  return out;
}

function convItem(c) {
  const n = c.message_count ? `<span class="cn" title="消息数">${c.message_count}</span>` : '';
  return `<li data-cid="${c.id}" class="${c.id === window._convId ? 'sel' : ''}${c.archived ? ' arch' : ''}">` +
    `<span class="ct" onclick="switchConversation(${c.id})" title="${esc(c.title)}">${esc(c.title)}</span>` +
    /* P4f: 人设徽标。已软删除的人设后端给「人设已删除」,这里原样显示,
       不去判断它到底为什么没了(那是后端的可见性语义,前端不猜)。 */
    (c.persona_name ? `<span class="cbadge" title="辅导星人设：${esc(c.persona_name)}">${esc(c.persona_name)}</span>` : '') +
    n +
    (c.archived ? `<span class="ctag" title="已归档">归档</span>` : '') +
    `<span class="ops">` +
    `<a href="javascript:void(0)" onclick="renameConversation(${c.id}, '${esc(c.title)}')">改名</a>` +
    `<a href="javascript:void(0)" onclick="archiveConversation(${c.id}, ${c.archived ? 0 : 1})">${c.archived ? '恢复' : '归档'}</a>` +
    `<a href="javascript:void(0)" class="del" onclick="deleteConversation(${c.id})">删</a>` +
    `</span></li>`;
}

function renderConversationList(list) {
  const ul = document.getElementById('conv-list');
  if (!ul) return;
  const b = groupConversations(list, serverNowMs());
  const sections = [['今天', b.today], ['近 7 天', b.week], ['更早', b.earlier]];
  ul.innerHTML = sections.filter(s => s[1].length)
    .map(s => `<li class="conv-group">${s[0]}（${s[1].length}）</li>` + s[1].map(convItem).join(''))
    .join('') || '<li class="empty">—</li>';
  const n = document.getElementById('conv-count');
  if (n) n.textContent = String((list || []).length);
}

async function loadConversations() {
  try {
    const showArch = document.getElementById('conv-show-archived')?.checked;
    const d = await api('/api/conversations' + (showArch ? '?include_archived=true' : ''));
    renderConversationList(d.conversations || []);
  } catch (e) { toast('会话列表加载失败:' + e.message); }
}

const WELCOME_HINT = '知识库问答自动检索并标注引用 [n]；「记一条碎片…」「生成本周周报」会触发周报工具；右下角可切换模型与账户设置。';

function newConversation() {
  abortInflight();
  window._convId = null;
  /* P4f: 新会话**保留**当前人设选择(用户选好张老师再点新建,期望还是张老师),
     只把选择器上的"已落到某个会话"这层含义清掉。 */
  const sel = $('persona-select'); if (sel && window._personaId) sel.value = String(window._personaId);
  renderPersonaHint();
  document.getElementById('messages').innerHTML = `<div class="hint">${WELCOME_HINT}</div>`;
  const bar = document.getElementById('ctx-bar');
  if (bar) bar.style.display = 'none';  // 新会话尚无占用数据
  loadConversations();
}

async function switchConversation(cid) {
  if (cid === window._convId) return;
  abortInflight();  // P4b C5: 切走即中止进行中的 SSE(服务端生成器随之取消并回滚该轮 user 消息,P4b-fix ⑤)
  window._convId = cid;
  const bar = document.getElementById('ctx-bar');
  if (bar) bar.style.display = 'none';  // 占用条随会话切换清空(下一轮回答时按事件重建)
  /* P4f: 选择器对齐到该会话绑定的人设。不对齐就会出现「界面显示张老师、
     实际在用李老师」——而且下一次提问还会把错的 persona_id 发出去。 */
  syncPersonaFromConversation(cid);
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
  /* P4f: 删掉的可能正是当前人设所在的会话 → 列表里已无人可对齐,清回"无"。
     不清的话选择器会停在一个已经不属于任何会话的 persona 上(看着像还在生效)。 */
  if (cid === window._convId) { window._personaId = null; renderPersonaHint(); const s = $('persona-select'); if (s) s.value = ''; }
}

function abortInflight() {
  if (window._convAbort) { try { window._convAbort.abort(); } catch (e) { /* 已结束 */ } window._convAbort = null; }
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = { groupConversations, DAY_MS };
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
