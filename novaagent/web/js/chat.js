/* P4b-0 拆分:本文件内容由 index.html 原样迁移(零修改),行为零变化。 */
/* P4b: send 携带 conversation_id + AbortController 可中止 + context 事件驱动占用条;
   loadHistory 改为加载会话列表(旧扁平消息流已迁往 /api/conversations/{id}/messages)。 */

async function send() {
  const q = $('q').value.trim(); if (!q) return;
  $('q').value = ''; addMsg('user', q);
  const btn = $('send'); btn.disabled = true;
  const bot = addMsg('bot', '');
  bot.classList.add('streaming');
  let got = false, srcs = null, trace = null;
  abortInflight();
  window._convAbort = new AbortController();  // P4b C5: 切换会话时中止
  try {
    const resp = await fetch('/api/chat/stream', {
      method: 'POST',
      headers: Object.assign({ 'Content-Type': 'application/json' }, TOKEN ? { Authorization: 'Bearer ' + TOKEN } : {}),
      body: JSON.stringify(Object.assign({ question: q }, window._convId ? { conversation_id: window._convId } : {})),
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
          if (!got) { bot.textContent = ''; got = true; }
          bot.textContent += ev.content;
          $('messages').scrollTop = $('messages').scrollHeight;
        } else if (ev.type === 'sources') {
          srcs = ev.sources;
        } else if (ev.type === 'context') {
          updateCtxBar(ev);  // P4b C5: 占用条与事件数值一致
        } else if (ev.type === 'tools') {
          trace = ev.trace;
        } else if (ev.type === 'done') {
          srcs = ev.sources || srcs; trace = ev.tool_trace || trace;
          if (ev.answer && !got) { bot.textContent = ev.answer; got = true; }
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
    if (e.name === 'AbortError') {  // 切换会话中止:不写残留内容(服务端同样不落库)
      bot.classList.remove('streaming');
      bot.textContent += '\n(已切换会话,本次回答中止)';
      return;
    }
    bot.classList.remove('streaming');
    if (!got) {
      try {
        const d = await api('/api/chat', { method: 'POST', json: Object.assign({ question: q }, window._convId ? { conversation_id: window._convId } : {}) });
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
  btn.disabled = false; $('messages').scrollTop = $('messages').scrollHeight;
}

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
