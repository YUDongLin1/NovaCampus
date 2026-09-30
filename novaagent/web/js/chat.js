/* P4b-0 拆分:本文件内容由 index.html 原样迁移(零修改),行为零变化。 */
/* P4b: send 携带 conversation_id + AbortController 可中止 + context 事件驱动占用条;
   loadHistory 改为加载会话列表(旧扁平消息流已迁往 /api/conversations/{id}/messages)。 */

async function send() {
  const q = $('q').value.trim(); if (!q) return;
  $('q').value = ''; addMsg('user', q);
  const btn = $('send'); btn.disabled = true;
  const bot = addMsg('bot', '');
  bot.classList.add('streaming');
  let got = false, srcs = null, trace = null, target = bot;
  abortInflight();
  window._convAbort = new AbortController();  // P4b C5: 切换会话时中止
  try {
    const resp = await fetch('/api/chat/stream', {
      method: 'POST',
      headers: Object.assign({ 'Content-Type': 'application/json' }, TOKEN ? { Authorization: 'Bearer ' + TOKEN } : {}),
      body: JSON.stringify(buildChatPayload(q)),
      signal: window._convAbort.signal
    });
    if (!resp.ok || !resp.body) throw new Error('HTTP ' + resp.status);
    const reader = resp.body.getReader();
    const dec = new TextDecoder();
    let buf = '';
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let i;
      while ((i = buf.indexOf('\n\n')) >= 0) {
        const raw = buf.slice(0, i).trim(); buf = buf.slice(i + 2);
        if (!raw.startsWith('data:')) continue;
        const payload = raw.slice(5).trim();
        if (payload === '[DONE]') continue;
        let ev; try { ev = JSON.parse(payload); } catch (err) { continue; }
        if (ev.type === 'delta') {
          if (!got) { target.textContent = ''; got = true; }
          target.textContent += ev.content;
          $('messages').scrollTop = $('messages').scrollHeight;
        } else if (ev.type === 'grounding_retry') {
          /* P4e S1-①:初稿被判定「未给出可核查依据」(有来源却零引用零数字)。
             已下发的文字**不撤回、不假装没发生**:原样折进「初稿」块并显式标注,
             重生结果另起一段继续流式。 */
          const draft = document.createElement('div');
          draft.className = 'gate-draft';
          draft.textContent = target.textContent;
          const st = document.createElement('div');
          st.className = 'gate-status';
          st.textContent = '（初稿未给出可核查依据，已重新组织答案如下）';
          target.textContent = '';
          bot.appendChild(draft);
          bot.appendChild(st);
          const fresh = document.createElement('div');
          bot.appendChild(fresh);
          target = fresh; got = false;
          $('messages').scrollTop = $('messages').scrollHeight;
        } else if (ev.type === 'sources') {
          srcs = ev.sources;
        } else if (ev.type === 'context') {
          updateCtxBar(ev);  // P4b C5: 占用条与事件数值一致
        } else if (ev.type === 'tools') {
          trace = ev.trace;
        } else if (ev.type === 'done') {
          srcs = ev.sources || srcs; trace = ev.tool_trace || trace;
          if (ev.answer && !got) { target.textContent = ev.answer; got = true; }
          if (ev.conversation_id) window._convId = ev.conversation_id;  // 首问后回填自动建的会话
          if (ev.context) updateCtxBar(ev.context);
          loadConversations();  // 列表刷新(新会话出现/updated_at 重排)
        } else if (ev.type === 'error') {
          throw new Error(ev.error || '流式错误');
        }
      }
    }
    bot.classList.remove('streaming');
    bot.className = 'msg bot' + (got ? '' : ' error');
    if (!got) bot.textContent = '(空回复)';
    renderMeta(bot, srcs, trace);
  } catch (e) {
    if (e.name === 'AbortError') {  // 切换会话中止:前端不留残影,服务端会回滚该轮 user 消息(P4b-fix ⑤)
      bot.classList.remove('streaming');
      bot.textContent += '\n(已切换会话,本次回答中止)';
      return;
    }
    bot.classList.remove('streaming');
    if (!got) {
      try {
        const d = await api('/api/chat', { method: 'POST', json: buildChatPayload(q) });
        bot.textContent = d.answer || '(空回复)';
        bot.className = 'msg bot' + (d.answer ? '' : ' error');
        if (d.conversation_id) window._convId = d.conversation_id;
        if (d.context) updateCtxBar(d.context);
        renderMeta(bot, d.sources, d.tool_trace);
        loadConversations();
      } catch (e2) {
        bot.textContent = '出错了:' + e2.message;
        bot.className = 'msg bot error';
      }
    } else {
      bot.textContent += '\n(流中断)';
    }
  }
  clearScope();
  btn.disabled = false; $('messages').scrollTop = $('messages').scrollHeight;
}

/* ===== P4c C4: @ 选择器——@ 只是唤起符号, 选中的库以 scope 分离传参, question 永不含 @xxx ===== */
window._scope = { folder_ids: [], categories: [] };

function buildChatPayload(q) {
  const p = Object.assign({ question: q }, window._convId ? { conversation_id: window._convId } : {});
  const scope = {};
  if (window._scope.folder_ids.length) scope.folder_ids = window._scope.folder_ids.slice();
  if (window._scope.categories.length) scope.categories = window._scope.categories.slice();
  if (Object.keys(scope).length) p.scope = scope;
  return p;
}

function clearScope() {
  window._scope = { folder_ids: [], categories: [] };
  renderScopeChips();
}

function composerKey(ev) {
  if (ev.key === 'Enter') { send(); return; }
  if (ev.key === '@') setTimeout(openAtPicker, 0);   // '@' 只作唤起符号, openAtPicker 会把它从问句里移除
}

async function openAtPicker() {
  const input = $('q');
  input.value = input.value.replace(/@/g, '');
  let folders = [], cats = [];
  try { folders = (await api('/api/kb/folders')).folders || []; } catch (e) {}
  try { cats = (await api('/api/kb/documents')).categories || []; } catch (e) {}
  const items = folders.map(f => ({ kind: 'folder', id: f.id, label: '📁 ' + f.name + '（' + f.doc_count + '）' }))
    .concat(cats.map(cn => ({ kind: 'category', id: cn, label: '🏷 ' + cn })));
  const el = $('at-picker'); if (!el) return;
  el.innerHTML = items.length
    ? items.map((it, i) => `<button type="button" class="at-item${isPicked(it) ? ' picked' : ''}" data-i="${i}">${esc(it.label)}</button>`).join('')
    : '<div class="at-empty">没有可选的知识库</div>';
  el.querySelectorAll('.at-item').forEach(btn => {
    btn.onclick = () => { togglePick(items[+btn.dataset.i]); closeAtPicker(); };
  });
  el.style.display = 'block';
}

function isPicked(it) {
  return it.kind === 'folder' ? window._scope.folder_ids.includes(it.id)
                              : window._scope.categories.includes(it.id);
}

function togglePick(it) {
  const arr = it.kind === 'folder' ? window._scope.folder_ids : window._scope.categories;
  const i = arr.indexOf(it.id);
  if (i >= 0) arr.splice(i, 1); else arr.push(it.id);
  renderScopeChips();
}

function closeAtPicker() { const el = $('at-picker'); if (el) el.style.display = 'none'; }

function renderScopeChips() {
  const el = $('scope-chips'); if (!el) return;
  const chips = [];
  window._scope.folder_ids.forEach(id => {
    const f = (window._kbFolders || []).find(x => x.id === id);
    chips.push({ kind: 'folder', id, label: '📁 ' + (f ? f.name : '#' + id) });
  });
  window._scope.categories.forEach(cn => chips.push({ kind: 'category', id: cn, label: '🏷 ' + cn }));
  if (!chips.length) { el.innerHTML = ''; return; }
  el.innerHTML = '<span class="chip-label">检索范围：</span>' + chips.map(c =>
    `<span class="chip" data-kind="${c.kind}" data-id="${c.id}">${esc(c.label)} ✕</span>`).join('');
  el.querySelectorAll('.chip').forEach(x => {
    x.onclick = () => {
      const kind = x.dataset.kind, id = x.dataset.id;
      const arr = kind === 'folder' ? window._scope.folder_ids : window._scope.categories;
      const i = arr.indexOf(kind === 'folder' ? +id : id);
      if (i >= 0) arr.splice(i, 1);
      renderScopeChips();
    };
  });
}

document.addEventListener('click', (ev) => {
  const el = $('at-picker');
  if (el && el.style.display === 'block' && !el.contains(ev.target) && ev.target.id !== 'q') closeAtPicker();
});

function renderMeta(bot, srcs, trace) {
  if (srcs && srcs.length) {
    const s = document.createElement('div'); s.className = 'sources';
    s.innerHTML = '<b>引用来源</b><br>' + srcs.map(x => `[${x.ref}] 《${esc(x.title)}》 · 相关度 ${x.score}`).join('<br>');
    bot.appendChild(s);
  }
  if (trace && trace.length) {
    const t = document.createElement('div'); t.className = 'sources';
    t.innerHTML = '<b>已调用工具</b> ' + trace.map(x => x.tool).join('、');
    bot.appendChild(t);
  }
}

async function loadHistory() {
  /* P4b: 登录后加载会话列表(不再拉扁平消息流——旧 /api/conversations 语义已变更,
     分页消息走 /api/conversations/{id}/messages,由 switchConversation 按需加载)。 */
  if (window.loadConversations) await loadConversations();
}
