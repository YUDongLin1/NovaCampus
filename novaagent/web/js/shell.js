/* P5-1:应用外壳 —— 左栏入口注册 / URL hash 路由 / 主区整页切换。
 *
 * 【为什么路由用 hash 而不是自己记状态】
 *   验收标准第 2 条要求「刷新后回到同一页、浏览器前进/后退可用」。
 *   自己存一个 window._page 也能刷新后复原(配合 localStorage),但**前进/后退**
 *   必须自己接管 popstate 并重建历史栈 —— 用 `location.hash` 则浏览器原生就做对了,
 *   少一整套容易错的状态机(坑 45 同族:同一件事只应有一处权威实现)。
 *
 * 【前端隐藏 ≠ 安全边界】
 *   本文件只按角色**决定渲染哪些入口**。周报/工作记录的真实拦截在后端
 *   `require_role`(`/api/weekly/*` 对 student 是 403)。前端跳过只是体验:
 *   学生手敲 `#/weekly` 会被 `visiblePageIds` 挡回会话页,但即便绕过 UI 直连接口,
 *   后端仍然 403 —— 两层都要,见 P5 第四节。
 */
const PAGES = [
  { id: 'chat', staffOnly: false, onEnter: null },
  { id: 'kb', staffOnly: false, onEnter: 'loadDocs' },
  { id: 'personas', staffOnly: false, onEnter: 'loadPersonaPage' },
  { id: 'weekly', staffOnly: true, onEnter: 'enterWeekly' },
  { id: 'records', staffOnly: true, onEnter: 'loadRecords' },
  { id: 'minutes', staffOnly: true, onEnter: 'loadMinutes' },
];
const DEFAULT_PAGE = 'chat';
const STAFF_ROLES = ['counselor', 'admin'];

/** 该角色**可见**的入口 id(纯函数,自测直接调用;不碰 DOM、不发请求)。 */
function visiblePageIds(role) {
  const staff = STAFF_ROLES.indexOf(role) >= 0;
  return PAGES.filter(p => !p.staffOnly || staff).map(p => p.id);
}

/** `#/kb` → `kb`;未知/空 → 默认页(纯函数)。 */
function hashToPage(hash) {
  const m = /^#\/([a-z]+)$/.exec(String(hash || '').trim());
  const id = m ? m[1] : '';
  return PAGES.some(p => p.id === id) ? id : DEFAULT_PAGE;
}

function pageById(id) {
  return PAGES.find(p => p.id === id) || null;
}

function navigate(id) {
  // 只改 hash —— 真正的切换统一由 hashchange 驱动(点同一个入口不会重复触发)
  const target = hashToPage('#/' + id);
  if (('#/' + target) === location.hash) switchPage(target);
  else location.hash = '#/' + target;
}

/** 按当前角色渲染左栏:不可见的入口整条隐藏(不是禁用 —— 禁用会让人以为有权限)。 */
function renderNav() {
  const visible = visiblePageIds(ME ? ME.role : 'student');
  document.querySelectorAll('#nav-entries .nav-item').forEach(li => {
    const p = li.dataset.page;
    li.classList.toggle('hidden', visible.indexOf(p) < 0);
  });
}

function switchPage(id) {
  const role = ME ? ME.role : 'student';
  // 越权/不存在的页一律回落到会话页:宁可回到一个一定能用的页,也不留半瘫的空主区
  const target = visiblePageIds(role).indexOf(id) >= 0 ? id : DEFAULT_PAGE;
  window._page = target;
  document.querySelectorAll('#nav-entries .nav-item').forEach(li => {
    // 「新会话」与「历史对话」都指向 chat:只有第一个(不带 data-no-switch)高亮,
    // 否则两个入口会同时亮,看着像有两个当前页
    li.classList.toggle('active', li.dataset.page === target && !li.dataset.noSwitch);
  });
  document.querySelectorAll('#stage .tabpane').forEach(p => {
    p.classList.toggle('active', p.id === 'pane-' + target);
  });
  const pg = pageById(target);
  if (pg && pg.onEnter && typeof window[pg.onEnter] === 'function') {
    try { window[pg.onEnter](); } catch (e) { /* 页面自己的加载失败由它自己 toast,不连坐切换 */ }
  }
  return target;
}

/* 兼容别名:P4b-0 起 `switchTab` 就是「切主区那一页」的名字(当时是右侧抽屉的页签)。
   语义从「抽屉页签」变成「整页」,但**机制没变**(仍是 .tabpane + .active),
   保留这个名字是为了既有调用点与契约断言不失效 —— 不是留着不用。 */
function switchTab(name) { return switchPage(name); }

window.addEventListener('hashchange', () => switchPage(hashToPage(location.hash)));

if (typeof module !== 'undefined' && module.exports) {
  module.exports = { PAGES, DEFAULT_PAGE, visiblePageIds, hashToPage };
}
