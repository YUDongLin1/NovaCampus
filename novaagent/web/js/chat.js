/* P4b-0 拆分:本文件内容由 index.html 原样迁移(零修改),行为零变化。 */
// 对话:SSE 流式问答、来源与工具轨迹渲染、历史加载

async function send() {
  const q = $('q').value.trim(); if (!q) return;
  $('q').value = ''; addMsg('user', q);
  const btn = $('send'); btn.disabled = true;
  const bot = addMsg('bot', '');
  bot.classList.add('streaming');
  let got = false, srcs = null, trace = null;
  try {
    const resp = await fetch('/api/chat/stream', {
      method: 'POST',
      headers: Object.assign({ 'Content-Type': 'application/json' }, TOKEN ? { Authorization: 'Bearer ' + TOKEN } : {}),
      body: JSON.stringify({ question: q })
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
        } else if (ev.type === 'tools') {
          trace = ev.trace;
        } else if (ev.type === 'done') {
          srcs = ev.sources || srcs; trace = ev.tool_trace || trace;
          if (ev.answer && !got) { bot.textContent = ev.answer; got = true; }
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
    bot.classList.remove('streaming');
    if (!got) {
      try {
        const d = await api('/api/chat', { method: 'POST', json: { question: q } });
        bot.textContent = d.answer || '(空回复)';
        bot.className = 'msg bot' + (d.answer ? '' : ' error');
        renderMeta(bot, d.sources, d.tool_trace);
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
  try {
    const d = await api('/api/conversations?limit=30');
    if (d.messages && d.messages.length) {
      for (const m of d.messages) addMsg(m.role === 'user' ? 'user' : 'bot', m.content);
      $('messages').scrollTop = $('messages').scrollHeight;
    }
  } catch (e) { /* 历史加载失败不阻断 */ }
}
