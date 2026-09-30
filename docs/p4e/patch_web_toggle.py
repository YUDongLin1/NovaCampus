#!/usr/bin/env python3
"""P4e M-A/M-B 前端:联网开关(默认关、状态可见)+ 来源**分区**渲染。

- index.html: composer 内加开关(带「仅在知识库无据时补充 / 出网只有当前问题」说明)
- chat.js:    window._webSearch;buildChatPayload 带 web_search;开关改动持久化到用户级默认;
              renderMeta 渲染「联网来源」分区(真实 URL 可点 + 「站点名由 URL 推导」标注),
              与本地「知识库来源」分区**分开、编号不混**
- theme.css:  开关与联网来源分区样式

用法: novaagent/.venv/Scripts/python.exe docs/p4e/patch_web_toggle.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HTML = ROOT / "novaagent" / "web" / "index.html"
CHAT = ROOT / "novaagent" / "web" / "js" / "chat.js"
CSS = ROOT / "novaagent" / "web" / "css" / "theme.css"
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError, OSError):
    pass

H_OLD = '      <div id="scope-chips"></div>\n'
H_NEW = '''      <div id="scope-chips"></div>
      <!-- P4e M-B: 联网开关(默认关闭、当前状态可见) -->
      <div id="web-toggle" title="默认关闭。开启后，仅在知识库查不到时才发起一次公网检索；出网内容只有你当前的问题文本，库内资料与会话历史不出网。">
        <label><input type="checkbox" id="web-search" onchange="onWebToggle()"> 联网检索</label>
        <span id="web-state">关</span>
        <span class="web-hint">（仅在知识库无据时补充；出网只有当前问题）</span>
      </div>
'''

C1_OLD = "async function send() {\n"
C1_NEW = """/* ===== P4e M-B: 联网检索开关(默认关闭;用户级默认 + 单次请求覆盖) ===== */
window._webSearch = false;

function onWebToggle() {
  const el = $('web-search'); if (!el) return;
  window._webSearch = !!el.checked;
  const st = $('web-state'); if (st) st.textContent = window._webSearch ? '开' : '关';
  /* 持久化为用户级默认(下次登录保持);失败只提示,不阻断对话 */
  api('/api/me/settings', { method: 'PUT', json: { web_search: window._webSearch } })
    .catch(e => toast('联网开关保存失败：' + e.message));
}

async function initWebToggle() {
  try {
    const s = await api('/api/me/settings');
    window._webSearch = !!s.web_search_enabled;
  } catch (e) { window._webSearch = false; }
  const el = $('web-search'); if (el) el.checked = window._webSearch;
  const st = $('web-state'); if (st) st.textContent = window._webSearch ? '开' : '关';
}

async function send() {
"""

C2_OLD = """  const p = Object.assign({ question: q }, window._convId ? { conversation_id: window._convId } : {});
"""
C2_NEW = """  const p = Object.assign({ question: q }, window._convId ? { conversation_id: window._convId } : {});
  p.web_search = !!window._webSearch;   // P4e M-B: 单次请求显式覆盖(开/关都显式传)
"""

C3_OLD = """async function loadHistory() {
  /* P4b: 登录后加载会话列表(不再拉扁平消息流——旧 /api/conversations 语义已变更,
     分页消息走 /api/conversations/{id}/messages,由 switchConversation 按需加载)。 */
  if (window.loadConversations) await loadConversations();
}"""
C3_NEW = """async function loadHistory() {
  /* P4b: 登录后加载会话列表(不再拉扁平消息流——旧 /api/conversations 语义已变更,
     分页消息走 /api/conversations/{id}/messages,由 switchConversation 按需加载)。 */
  if (window.loadConversations) await loadConversations();
  await initWebToggle();   // P4e M-B: 登录后把用户级默认同步到开关 UI
}"""

C4_OLD = "  let got = false, srcs = null, trace = null, target = bot;\n"
C4_NEW = "  let got = false, srcs = null, trace = null, target = bot, wsrcs = null;\n"

C5_OLD = """        } else if (ev.type === 'sources') {
          srcs = ev.sources;
        } else if (ev.type === 'context') {"""
C5_NEW = """        } else if (ev.type === 'sources') {
          srcs = ev.sources; wsrcs = ev.web_sources || wsrcs;
        } else if (ev.type === 'context') {"""

C6_OLD = """          srcs = ev.sources || srcs; trace = ev.tool_trace || trace;
"""
C6_NEW = """          srcs = ev.sources || srcs; trace = ev.tool_trace || trace;
          wsrcs = ev.web_sources || wsrcs;
"""

# send() 内的三处 renderMeta 调用
C7_OLD = "    renderMeta(bot, srcs, trace);\n"
C7_NEW = "    renderMeta(bot, srcs, trace, wsrcs);\n"

C8_OLD = """        if (d.conversation_id) window._convId = d.conversation_id;
        if (d.context) updateCtxBar(d.context);
        renderMeta(bot, d.sources, d.tool_trace);"""
C8_NEW = """        if (d.conversation_id) window._convId = d.conversation_id;
        if (d.context) updateCtxBar(d.context);
        renderMeta(bot, d.sources, d.tool_trace, d.web_sources);"""

C9_OLD = """function renderMeta(bot, srcs, trace) {
  if (srcs && srcs.length) {
    const s = document.createElement('div'); s.className = 'sources';
    s.innerHTML = '<b>引用来源</b><br>' + srcs.map(x => `[${x.ref}] 《${esc(x.title)}》 · 相关度 ${x.score}`).join('<br>');
    bot.appendChild(s);
  }
  if (trace && trace.length) {"""
C9_NEW = """function renderMeta(bot, srcs, trace, wsrcs) {
  if (srcs && srcs.length) {
    const s = document.createElement('div'); s.className = 'sources';
    s.innerHTML = '<b>知识库来源</b><br>' + srcs.map(x => `[${x.ref}] 《${esc(x.title)}》 · 相关度 ${x.score}`).join('<br>');
    bot.appendChild(s);
  }
  /* P4e M-A: 联网来源**单独分区**,与本地 [1..n] 不混编号;
     站点名由 URL 推导(上游只返回 {type,url}),必须显式标注,避免误导。 */
  if (wsrcs && wsrcs.length) {
    const w = document.createElement('div'); w.className = 'sources-web';
    w.innerHTML = '<b>联网来源（公网检索，未经本校核实）</b><br>' +
      wsrcs.map(x => `[${x.ref}] ${esc(x.site_name || '')} · <a href="${esc(x.url)}" target="_blank" rel="noopener noreferrer">${esc(x.url)}</a>`).join('<br>') +
      '<br><span class="web-derived">站点名由 URL 推导（上游只返回 URL）</span>';
    bot.appendChild(w);
  }
  if (trace && trace.length) {"""

CSS_NEW = """
/* P4e M-B: 联网检索开关(默认关,状态可见) */
#web-toggle { display: flex; align-items: center; gap: 6px; font-size: 13px;
  color: var(--muted, #6b6b6b); margin-bottom: 4px; }
#web-toggle #web-state { font-weight: 600; color: var(--ink, #2b2b2b); }
#web-toggle .web-hint { font-size: 12px; opacity: .8; }
/* P4e M-A: 联网来源分区——与「知识库来源」分区视觉上分开 */
.sources-web { margin-top: 6px; padding: 6px 8px; border-left: 3px solid #b98a3c;
  background: rgba(185, 138, 60, .07); font-size: 13px; line-height: 1.7; word-break: break-all; }
.sources-web a { color: var(--accent, #8a5a2b); }
.web-derived { font-size: 12px; color: var(--muted, #6b6b6b); }
"""

PAIRS_HTML = [("H1", H_OLD, H_NEW, 1)]
PAIRS_CHAT = [("C1", C1_OLD, C1_NEW, 1), ("C2", C2_OLD, C2_NEW, 1), ("C3", C3_OLD, C3_NEW, 1),
              ("C4", C4_OLD, C4_NEW, 1), ("C5", C5_OLD, C5_NEW, 1), ("C6", C6_OLD, C6_NEW, 1),
              ("C8", C8_OLD, C8_NEW, 1), ("C9", C9_OLD, C9_NEW, 1)]


def main() -> int:
    for path, items in ((HTML, PAIRS_HTML), (CHAT, PAIRS_CHAT)):
        src = path.read_text(encoding="utf-8")
        for name, old, new, cnt in items:
            n = src.count(old)
            if n != cnt:
                print(f"[FAIL] {path.name} {name} 命中 {n} 次(期望 {cnt})")
                return 1
            src = src.replace(old, new, 1)
        # C7 出现 1 次(send 内)
        n = src.count(C7_OLD)
        if path is CHAT:
            if n != 1:
                print(f"[FAIL] chat.js C7 命中 {n} 次")
                return 1
            src = src.replace(C7_OLD, C7_NEW, 1)
        path.write_text(src, encoding="utf-8")
        print(f"[OK] {path.name} 已接线")
    c = CSS.read_text(encoding="utf-8")
    if "#web-toggle" not in c:
        CSS.write_text(c.rstrip("\n") + "\n" + CSS_NEW, encoding="utf-8")
        print("[OK] theme.css 已追加开关与联网来源分区样式")
    return 0


if __name__ == "__main__":
    sys.exit(main())
