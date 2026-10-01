/* P5 第 2 回②:给 `enter()` 用的**最小 DOM 桩**(node 里跑,零浏览器、零额度)。
 *
 * 【为什么需要它】—— 这一轮之前 109 条断言全绿而真页面是坏的(坑 71:接线断了所有断言一声不吭)。
 * 那批断言是「静态接线 + 纯函数」,**没有一条真的调 `enter()`**。
 * 桩不需要像浏览器,只需要**忠实反映一件事**:
 *   `document.getElementById(<不存在的 id>)` 必须返回 **null**,
 *   于是 `$(x).style` 会真抛 `TypeError` —— 和真浏览器一模一样。
 * 桩若「什么都返回对象」,这条缺陷就永远测不出来(那才是自欺)。
 *
 * 【id 从哪来】index.html 真解析(不是手抄名单):改了 DOM 不同步桩,自测当场红。
 * 导航项的 data-page / data-no-switch / data-staff 也从 HTML 真解析,
 * `renderNav()` 隐藏的是真条目而不是替身。
 *
 * 用法:P5_PAGE=kb node p5_dom_stub.js <web目录> <role>
 *   输出:{"ok":true,"v":{...}}  —— v.threw 非空 = enter() 抛错(本轮缺陷的原始症状)
 *
 * ⚠ 页面 id 走**环境变量**且**不带 `#/` 前缀**:命令行与 env 里的 `#/kb` 都会被
 *   Git Bash 的路径转换吃掉 —— `/kb` 被当成盘符相对路径,实测值变成
 *   `#C:/Users/<user>/.workbuddy/binaries/PortableGit/versions/1.2.0/kb`。
 *   前缀由桩自己拼,踩过一次,记在这里。
 */
'use strict';
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const WEB = process.argv[2];
const ROLE = process.argv[3] || 'counselor';
const PAGE_ARG = process.env.P5_PAGE || '';
const HASH = PAGE_ARG ? '#/' + PAGE_ARG : '';
const HTML_TXT = fs.readFileSync(path.join(WEB, 'index.html'), 'utf8');

/* ---------- 1. 从 index.html 真解析 id 与导航项 ---------- */
const HTML_IDS = new Set();
for (const m of HTML_TXT.matchAll(/\bid="([^"]+)"/g)) HTML_IDS.add(m[1]);

const NAV_ITEMS = [];
const navUl = /<ul id="nav-entries">([\s\S]*?)<\/ul>/.exec(HTML_TXT);
if (navUl) {
  for (const m of navUl[1].matchAll(/<li class="nav-item"([^>]*)>/g)) {
    const attrs = m[1];
    const pg = /data-page="([a-z]+)"/.exec(attrs);
    NAV_ITEMS.push({
      page: pg ? pg[1] : '',
      noSwitch: /data-no-switch="1"/.test(attrs),
      staffOnly: /data-staff="1"/.test(attrs),
    });
  }
}
const PANE_IDS = [...HTML_IDS].filter((i) => i.startsWith('pane-'));

/* ---------- 2. 元素工厂 ---------- */
function mkEl(id, tag) {
  const el = {
    id: id || '',
    tagName: (tag || 'div').toUpperCase(),
    style: {}, dataset: {}, attrs: {},
    className: '', textContent: '', innerHTML: '',
    value: '', checked: false, disabled: false, hidden: false,
    scrollTop: 0, scrollHeight: 0, children: [],
    addEventListener() {}, removeEventListener() {},
    appendChild(c) { this.children.push(c); return c; },
    removeChild(c) { this.children = this.children.filter((x) => x !== c); return c; },
    remove() {},
    setAttribute(k, v) { this.attrs[k] = String(v); if (k === 'id') this.id = String(v); },
    getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; },
    querySelector() { return null; },
    querySelectorAll() { return []; },
    closest() { return null; },
    focus() {}, blur() {}, contains() { return false; },
  };
  const set = new Set();
  el.classList = {
    add: (...c) => c.forEach((x) => set.add(x)),
    remove: (...c) => c.forEach((x) => set.delete(x)),
    contains: (c) => set.has(c),
    toggle(c, force) {
      const on = force === undefined ? !set.has(c) : !!force;
      if (on) set.add(c); else set.delete(c);
      return on;
    },
  };
  return el;
}

/* ---------- 3. document / window ---------- */
const REG = new Map();                       // id → 元素(**只装 index.html 里真实存在的**)
for (const id of HTML_IDS) REG.set(id, mkEl(id));

const NAV_ELS = NAV_ITEMS.map((n) => {
  const el = mkEl('', 'li');
  el.className = 'nav-item';
  el.dataset.page = n.page;
  if (n.noSwitch) el.dataset.noSwitch = '1';
  if (n.staffOnly) el.dataset.staff = '1';
  return el;
});

const doc = {
  getElementById(id) { return REG.has(id) ? REG.get(id) : null; },   // 关键:不存在 → null
  querySelectorAll(sel) {
    const s = String(sel).replace(/\s+/g, ' ').trim();
    if (s === '#nav-entries .nav-item') return NAV_ELS;
    if (s === '#stage .tabpane') return PANE_IDS.map((i) => REG.get(i)).filter(Boolean);
    return [];
  },
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; },
  createElement(tag) { return mkEl('', tag); },
  createTextNode(t) { return { nodeValue: String(t) }; },
  addEventListener() {}, removeEventListener() {},
  body: mkEl('body', 'body'),
  head: mkEl('head', 'head'),
  documentElement: mkEl('html', 'html'),
};

/* ---------- 4. fetch 桩:只答 enter() 真会打到的端点,数据非空 ---------- */
const SERVER_NOW_MS = 1770000000000;
function mkResp(obj) {
  return {
    ok: true, status: 200, statusText: 'OK',
    headers: { get: (k) => (String(k).toLowerCase() === 'date' ? new Date(SERVER_NOW_MS).toUTCString() : null) },
    async json() { return obj; },
    async text() { return JSON.stringify(obj); },
  };
}
const NOW_ISO = new Date(SERVER_NOW_MS).toISOString();
const CONVS = [
  { id: 901, title: '贫困生认定流程', message_count: 6, archived: false, updated_at: NOW_ISO, persona_name: '张老师' },
  { id: 902, title: '奖学金申请材料', message_count: 2, archived: false, updated_at: NOW_ISO, persona_name: null },
  { id: 903, title: '两周前的旧会话', message_count: 11, archived: true, updated_at: '2026-01-02T03:04:05+00:00', persona_name: null },
];
const UNAME = ROLE === 'student' ? 'student01' : 'counselor01';
async function fetchStub(pathArg) {
  const p = String(pathArg || '');
  if (p.startsWith('/api/personas')) {
    return mkResp({ personas: [{ id: 7, name: '张老师', college: '信息学院', style: 'warm', avatar: 'av-07', visibility: 'public', is_default: true, persona_prompt: '', bound_folder_ids: [], bound_categories: [] }] });
  }
  if (p.startsWith('/api/conversations')) return mkResp({ conversations: CONVS });
  if (p.startsWith('/api/me/settings')) return mkResp({ web_search_enabled: false });
  if (p.startsWith('/api/me')) return mkResp({ id: 1, username: UNAME, role: ROLE });
  throw new Error('fetch 桩未覆盖的端点(说明 enter() 打了新的网络请求): ' + p);
}

/* ---------- 5. 装上下文,按 index.html 的顺序加载脚本 ---------- */
const store = new Map();
const sandbox = {
  console, setTimeout, clearTimeout, setInterval, clearInterval,
  fetch: fetchStub, document: doc,
  localStorage: {
    getItem: (k) => (store.has(k) ? store.get(k) : null),
    setItem: (k, v) => store.set(k, String(v)),
    removeItem: (k) => store.delete(k),
  },
  location: { hash: HASH, href: 'http://127.0.0.1:9/', reload() {}, pathname: '/' },
  navigator: { userAgent: 'node-p5-dom-stub' },
  alert() {}, confirm() { return true; },
  Date, Math, JSON, Promise, Object, Array, String, Number, Boolean, RegExp, Error,
  Map, Set, URLSearchParams, Intl,
  isNaN, parseInt, parseFloat, encodeURIComponent, decodeURIComponent,
};
sandbox.window = sandbox;
sandbox.globalThis = sandbox;
sandbox.self = sandbox;
sandbox.addEventListener = () => {};
vm.createContext(sandbox);

const ORDER = [...HTML_TXT.matchAll(/<script src="\/js\/([^"]+)"><\/script>/g)].map((m) => m[1]);
const LOAD_ERRORS = [];
for (const f of ORDER) {
  try {
    vm.runInContext(fs.readFileSync(path.join(WEB, 'js', f), 'utf8'), sandbox, { filename: 'js/' + f });
  } catch (e) {
    LOAD_ERRORS.push(`${f}: ${e.message}`);
  }
}

/* ---------- 6. 真调 enter() ---------- */
function snapshot(threw) {
  const cl = REG.get('conv-list');
  const pane = REG.get('pane-' + sandbox.window._page);
  return {
    role: ROLE, hash: HASH, scripts: ORDER, loadErrors: LOAD_ERRORS,
    threw: threw || null,
    navHidden: NAV_ELS.filter((e) => e.classList.contains('hidden')).map((e) => e.dataset.page),
    navVisible: NAV_ELS.filter((e) => !e.classList.contains('hidden')).map((e) => e.dataset.page),
    convListItems: cl ? (cl.innerHTML.match(/<li /g) || []).length : 0,
    convListPlaceholder: cl ? /<li class="empty">—<\/li>/.test(cl.innerHTML) : null,
    convListHtml: cl ? cl.innerHTML : null,
    convCount: (REG.get('conv-count') || {}).textContent || null,
    acctName: (REG.get('acct-name') || {}).textContent || null,
    acctRole: (REG.get('acct-role') || {}).textContent || null,
    roleBadge: (REG.get('role-badge') || {}).textContent || null,
    maskDisplay: ((REG.get('mask') || {}).style || {}).display,
    personasNewDisplay: ((REG.get('personas-new') || {}).style || {}).display,
    uploadRowDisplay: ((REG.get('upload-row') || {}).style || {}).display,
    personaBarHtml: (REG.get('persona-bar') || {}).innerHTML || '',
    messagesChildren: ((REG.get('messages') || {}).children || []).length,
    page: sandbox.window._page,
    activePane: pane ? pane.classList.contains('active') : null,
  };
}

(async () => {
  try {
    vm.runInContext(`TOKEN = 'stub-token'; ME = ${JSON.stringify({ id: 1, username: UNAME, role: ROLE })};`, sandbox);
  } catch (e) {
    console.log(JSON.stringify({ ok: true, v: snapshot('setup: ' + e.message) }));
    return;
  }
  let threw = null;
  try {
    await vm.runInContext('enter()', sandbox);
  } catch (e) {
    threw = String((e && e.message) || e);
  }
  console.log(JSON.stringify({ ok: true, v: snapshot(threw) }));
})();