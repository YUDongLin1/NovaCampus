// 会议纪要:原始内容(粘贴 / 笔记文本 / 录音转写) → AI 整理 → 在线编辑 → 复制 / 导出 .docx
//
// 【出网确认是功能闸门,不是提示文案】
//   转写会把**音频文件**发往 DashScope,整理会把**会议原文**发往 LLM。两者都在
//   `mt-consent` 未勾选时保持禁用,而不是"勾了才提示一次" —— 一次性的 confirm
//   会被连点三次就习惯性地按下去,起不到告知作用。

const MT_AUDIO_EXTS = ['aac', 'amr', 'avi', 'flac', 'flv', 'm4a', 'mkv', 'mov', 'mp3',
  'mp4', 'mpeg', 'ogg', 'opus', 'wav', 'webm', 'wma', 'wmv'];
const MT_TEXT_EXTS = ['txt', 'md', 'markdown'];
const MT_MISSING = '（未提供，请补充）';

function mtExt(name) {
  const i = String(name || '').lastIndexOf('.');
  return i < 0 ? '' : String(name).slice(i + 1).toLowerCase();
}

function loadMinutes() {
  onMinutesConsent();
  return loadMinutesList();
}

async function loadMinutesList() {
  try {
    const d = await api('/api/weekly/minutes');
    $('mt-list').innerHTML = d.count ? d.minutes.map(x => `
      <li>📝 ${esc(x.title || MT_MISSING)}
        <span style="color:var(--muted);font-size:11px">${esc(x.meeting_time || '')}
          ${x.source_type === 'audio' ? '· 录音转写' : x.source_type === 'file' ? '· 笔记文件' : ''}</span>
        <button class="link" onclick="openMinutes(${x.id})">编辑</button>
        <button class="link" onclick="exportMinutes(${x.id})">导出</button>
        <button class="link del" onclick="delMinutes(${x.id})">删除</button>
      </li>`).join('') : '<li class="empty">暂无纪要</li>';
  } catch (e) { toast(e.message); }
}

async function onMinutesFile() {
  const f = $('mt-file').files[0];
  if (!f) return;
  const ext = mtExt(f.name);
  if (MT_TEXT_EXTS.includes(ext)) {
    // 文本笔记在浏览器里读进正文框,不走上传接口:内容最终仍要发给 /organize,
    // 多一次 multipart 往返只会多一个失败点
    try {
      $('mt-raw').value = await f.text();
      window._mtAudio = null;
      $('mt-audio-row').style.display = 'none';
      toast('已读入笔记文本，请核对后点「AI 整理」');
    } catch (e) { toast('读取文件失败：' + e.message); }
  } else if (MT_AUDIO_EXTS.includes(ext)) {
    window._mtAudio = f;
    window._mtAudioName = f.name;
    $('mt-audio-row').style.display = 'flex';
    $('mt-audio-state').textContent =
      `待转写：${f.name}（${(f.size / 1024 / 1024).toFixed(1)}MB）—— 点「AI 整理」会先转写再整理`;
  } else {
    $('mt-file').value = '';
    toast(`不支持的文件类型 .${ext}；文本可用 ${MT_TEXT_EXTS.join('/')}，录音可用 ${MT_AUDIO_EXTS.join('/')}`);
  }
  onMinutesConsent();
}

function clearMinutesRaw() {
  $('mt-raw').value = '';
  $('mt-file').value = '';
  window._mtAudio = null;
  window._mtAudioName = '';
  $('mt-audio-row').style.display = 'none';
  $('mt-result').style.display = 'none';
  onMinutesConsent();
}

function onMinutesConsent() {
  const ok = $('mt-consent').checked && ($('mt-raw').value.trim() || window._mtAudio);
  $('mt-organize-btn').disabled = !ok;
  $('mt-consent-tip').textContent = $('mt-consent').checked
    ? '已同意：录音将上传转写、正文将发给大模型整理'
    : '未勾选时下方按钮不可用（录音与原文都不离开本机）';
}

async function organizeMinutes() {
  if (!$('mt-consent').checked) return toast('请先勾选同意把内容发往外部模型处理');
  const btn = $('mt-organize-btn');
  const pasted = $('mt-raw').value.trim();
  if (!pasted && !window._mtAudio) return toast('请先粘贴会议内容、上传笔记或上传录音');
  btn.disabled = true;
  try {
    let raw = pasted;
    if (window._mtAudio) {
      btn.textContent = '转写中…（长音频可能要几分钟）';
      const fd = new FormData();
      fd.append('file', window._mtAudio, window._mtAudio.name);
      const t = await api('/api/weekly/minutes/transcribe', { method: 'POST', body: fd });
      raw = (pasted ? pasted + '\n\n' : '') + t.text;
      $('mt-raw').value = raw;
      $('mt-audio-row').style.display = 'flex';
      $('mt-audio-state').textContent = `已转写：${t.audio_name}（${t.chars} 字）—— 转写文本可继续手工修正`;
      window._mtAudio = null;
      $('mt-file').value = '';
    }
    btn.textContent = '整理中…';
    const d = await api('/api/weekly/minutes/organize', { method: 'POST', json: { raw } });
    window._mtRaw = raw;
    window._mtId = null;
    renderMinutesResult(d.minutes, d.untraced, window._mtAudioName ? 'audio' : 'text');
    toast('已生成纪要草稿，请核对后保存');
  } catch (e) {
    toast(e.message);
  }
  btn.textContent = '🧩 AI 整理成纪要';
  onMinutesConsent();
}

function renderMinutesResult(m, untraced, sourceType) {
  const un = v => (v === MT_MISSING ? '' : (v || ''));
  $('mt-title').value = un(m.title);
  $('mt-time').value = un(m.meeting_time);
  $('mt-attendees').value = un(m.attendees);
  $('mt-discussion').value = (m.discussion || []).join('\n');
  $('mt-resolutions').value = (m.resolutions || []).join('\n');
  $('mt-todos').innerHTML = '';
  (m.todos || []).forEach(t => addTodoRow({
    item: t.item, owner: un(t.owner), due: un(t.due)
  }));
  window._mtSource = sourceType || 'text';
  const box = $('mt-untraced');
  if (untraced && untraced.length) {
    box.style.display = 'flex';
    box.innerHTML = '<span class="tag">需核对</span> <span style="font-size:12px">'
      + untraced.map(esc).join('；') + '（原文里没有的信息不会被自动补上，占位处请手工填写）</span>';
  } else {
    box.style.display = 'none';
    box.innerHTML = '';
  }
  $('mt-result').style.display = 'block';
}

function addTodoRow(t) {
  const o = t || {};
  const div = document.createElement('div');
  div.className = 'row';
  div.dataset.todo = '1';
  const cell = (cls, ph, val, len) =>
    `<input class="${cls}" maxlength="${len}" placeholder="${ph}" value="${esc(val)}">`;
  div.innerHTML = cell('mt-todo-item', '事项', o.item, 500)
    + cell('mt-todo-owner', '责任人', o.owner, 60)
    + cell('mt-todo-due', '截止时间', o.due, 60)
    + '<button class="link del" onclick="this.parentElement.remove()">删</button>';
  $('mt-todos').appendChild(div);
}

function collectMinutes() {
  const lines = v => String(v || '').split('\n').map(s => s.trim()).filter(Boolean);
  const val = (row, cls) => { const el = row.querySelector('.' + cls); return el ? el.value.trim() : ''; };
  const todos = Array.from(document.querySelectorAll('#mt-todos [data-todo="1"]'))
    .map(r => ({ item: val(r, 'mt-todo-item'), owner: val(r, 'mt-todo-owner'), due: val(r, 'mt-todo-due') }))
    .filter(t => t.item);
  return {
    title: $('mt-title').value.trim(),
    meeting_time: $('mt-time').value.trim(),
    attendees: $('mt-attendees').value.trim(),
    discussion: lines($('mt-discussion').value),
    resolutions: lines($('mt-resolutions').value),
    todos,
  };
}

function minutesToText(p) {
  const L = [];
  L.push('会议主题：' + (p.title || MT_MISSING));
  L.push('会议时间：' + (p.meeting_time || MT_MISSING));
  L.push('参会人员：' + (p.attendees || MT_MISSING));
  L.push('讨论要点：');
  L.push(...(p.discussion.length ? p.discussion.map(x => '· ' + x) : ['· ' + MT_MISSING]));
  L.push('决议事项：');
  L.push(...(p.resolutions.length ? p.resolutions.map(x => '· ' + x) : ['· ' + MT_MISSING]));
  L.push('待办任务：');
  L.push(...(p.todos.length ? p.todos.map(t =>
    `· ${t.item}｜责任人：${t.owner || MT_MISSING}｜截止时间：${t.due || MT_MISSING}`)
    : ['· ' + MT_MISSING]));
  return L.join('\n');
}

async function saveMinutes(andExport) {
  const p = collectMinutes();
  if (!p.title) return toast('请填写会议主题');
  const body = Object.assign({}, p, {
    raw_content: window._mtRaw || '',
    source_type: window._mtSource || 'text',
    audio_name: window._mtAudioName || '',
  });
  try {
    let id = window._mtId;
    if (id) {
      await api('/api/weekly/minutes/' + id, { method: 'PUT', json: body });
    } else {
      const d = await api('/api/weekly/minutes', { method: 'POST', json: body });
      id = d.minutes_id;
      window._mtId = id;
    }
    toast('已保存');
    loadMinutesList();
    if (andExport) await exportMinutes(id, p.title);
  } catch (e) { toast(e.message); }
}

async function exportMinutes(id, title) {
  try {
    const name = await downloadFile('/api/weekly/minutes/' + id + '/export',
      (title || '会议纪要') + '.docx');
    toast('已导出：' + name);
  } catch (e) { toast(e.message); }
}

async function openMinutes(id) {
  try {
    const d = await api('/api/weekly/minutes/' + id);
    window._mtId = id;
    window._mtRaw = d.raw_content || '';
    window._mtAudioName = d.audio_name || '';
    renderMinutesResult(d, d.untraced || [], d.source_type);
    $('mt-result').scrollIntoView({ behavior: 'smooth', block: 'start' });
  } catch (e) { toast(e.message); }
}

async function delMinutes(id) {
  if (!confirm('确认删除这条会议纪要？')) return;
  try {
    await api('/api/weekly/minutes/' + id, { method: 'DELETE' });
    if (window._mtId === id) { window._mtId = null; $('mt-result').style.display = 'none'; }
    toast('已删除'); loadMinutesList();
  } catch (e) { toast(e.message); }
}

async function copyMinutes() {
  const text = minutesToText(collectMinutes());
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(text);
      return toast('已复制到剪贴板');
    }
    throw new Error('clipboard 不可用');
  } catch (e) {
    // 剪贴板 API 需要安全上下文;用本机 http://127.0.0.1 访问时可能被浏览器拒绝,
    // 回落到一个全选文本框,让用户自己 Ctrl+C,而不是"复制失败"就没了下文
    openModal('复制纪要文本', `<div class="row"><textarea id="mt-copy">${esc(text)}</textarea></div>`);
    const ta = $('mt-copy');
    ta.focus(); ta.select();
    toast('剪贴板不可用，已选中文本，请按 Ctrl+C');
  }
}
