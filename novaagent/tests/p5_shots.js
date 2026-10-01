/* P5 第 2 回④:真浏览器截图 + 重叠/截断走查(两档视口)。
 *
 * 【为什么这次能截图】第 1 回说「环境没有 playwright」,是因为**整包**装不上。
 * 本轮改装 playwright-core 并直接驱动**本机已装的 Chrome**(executablePath 指到
 * chrome.exe),不下载浏览器包。第 1 回那条「未做」的理由到此解除。
 *
 * 【截图要证明什么】不只是"能看",而是把开单点名的坑变成**可判的读数**:
 *   - 登录后左栏**不是半瘫**(账户卡有名字、历史列表有真实条目、欢迎气泡在)
 *   - 学生角色 weekly/records 两条入口 hidden
 *   - 知识库「左树右表」在 1280 宽下三个下拉**不被压到 51px**(P4f 走查的老坑)
 *   - 每页扫**元素重叠**与**文字溢出截断**,输出可疑清单
 *
 * 用法:P5_BASE=http://127.0.0.1:8985 P5_OUT=<目录> node p5_shots.js
 * 零额度:只点导航不发问句,页面加载走本地静态资源。
 */
'use strict';
const path = require('path');
const fs = require('fs');

const WORKSPACE = path.join(process.env.USERPROFILE || '', '.workbuddy', 'binaries', 'node', 'workspace');
const { chromium } = require(path.join(WORKSPACE, 'node_modules', 'playwright-core'));

const BASE = process.env.P5_BASE || 'http://127.0.0.1:8985';
const OUT = process.env.P5_OUT || path.join(__dirname, '..', '..', 'docs', 'p5', 'evidence', 'shots');
const CHROME = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';

const VIEWPORTS = [
  { name: '1440x900', width: 1440, height: 900 },
  { name: '1280x800', width: 1280, height: 800 },
];
const PAGES = [
  { id: 'chat', label: '会话' },
  { id: 'kb', label: '知识库' },
  { id: 'personas', label: '辅导员' },
  { id: 'weekly', label: '周报' },
  { id: 'records', label: '工作记录' },
];

/* 在页面里跑的体检脚本:重叠 + 截断 + 关键元素读数 */
const PROBE = () => {
  const vis = (el) => {
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  };
  /* 被滚动容器**裁掉**的元素不算"可见区域重叠"。
     第一版没判这个,于是 #conv-list 里滚出可视区的 li(它在文档坐标里仍占位)
     与底部账户卡 #acct-entry 被报成 ratio 0.97 的重叠 —— 截图上两者根本不挨着。
     这是**判据缺陷不是布局缺陷**:修检测器,不去动已经正确的实现。 */
  const clippedByScroller = (el) => {
    for (let p = el.parentElement; p; p = p.parentElement) {
      const cs = getComputedStyle(p);
      if (cs.overflowY === 'auto' || cs.overflowY === 'scroll' ||
          cs.overflowX === 'auto' || cs.overflowX === 'scroll' ||
          cs.overflow === 'auto' || cs.overflow === 'scroll' || cs.overflow === 'hidden') {
        const pr = p.getBoundingClientRect(), r = el.getBoundingClientRect();
        const inX = r.right > pr.left && r.left < pr.right;
        const inY = r.bottom > pr.top && r.top < pr.bottom;
        if (!inX || !inY) return true;          // 完全落在可视区之外 → 被裁
      }
    }
    return false;
  };
  const rects = [];
  const trunc = [];
  const doc = document.documentElement;

  for (const el of document.querySelectorAll('#shell *')) {
    if (!vis(el)) continue;
    if (clippedByScroller(el)) continue;       // 被滚动容器裁掉,不参与重叠判据
    const r = el.getBoundingClientRect();
    const cs = getComputedStyle(el);
    if (cs.position === 'fixed' || cs.position === 'absolute') continue;
    const tag = el.tagName.toLowerCase();
    const id = el.id ? '#' + el.id : '';
    const cls = el.className && typeof el.className === 'string'
      ? '.' + el.className.trim().split(/\s+/).slice(0, 2).join('.') : '';
    rects.push({ el, sel: tag + id + cls, r });

    /* 文字溢出截断:内容宽度 > 可视宽度 且 overflow 已被隐藏 */
    if (el.children.length === 0 && (el.textContent || '').trim()) {
      const overflows = el.scrollWidth - el.clientWidth;
      if (overflows > 2 && cs.overflowX !== 'visible' && cs.textOverflow !== 'ellipsis') {
        trunc.push({
          sel: tag + id + cls, overflowPx: overflows,
          clientW: el.clientWidth, scrollW: el.scrollWidth,
          text: (el.textContent || '').trim().slice(0, 30),
        });
      }
    }
  }
  /* 横向溢出页面(P4f 老坑的根因之一) */
  const hOverflow = doc.scrollWidth - doc.clientWidth;

  /* 两两重叠:只报"面积交集 > 25% 且都不是对方的祖先"的组合,避免父子误报 */
  const overlaps = [];
  for (let i = 0; i < rects.length; i++) {
    for (let j = i + 1; j < rects.length; j++) {
      const a = rects[i], b = rects[j];
      if (a.el.contains(b.el) || b.el.contains(a.el)) continue;
      const w = Math.min(a.r.right, b.r.right) - Math.max(a.r.left, b.r.left);
      const h = Math.min(a.r.bottom, b.r.bottom) - Math.max(a.r.top, b.r.top);
      if (w <= 2 || h <= 2) continue;
      const inter = w * h;
      const small = Math.min(a.r.width * a.r.height, b.r.width * b.r.height);
      if (small > 0 && inter / small > 0.25) {
        overlaps.push({
          a: a.sel, b: b.sel,
          ratio: +(inter / small).toFixed(2),
          box: [Math.round(Math.max(a.r.left, b.r.left)), Math.round(Math.max(a.r.top, b.r.top)),
                Math.round(Math.min(a.r.right, b.r.right)), Math.round(Math.min(a.r.bottom, b.r.bottom))],
        });
      }
    }
  }

  const txt = (sel) => { const e = document.querySelector(sel); return e ? (e.textContent || '').trim() : null; };
  const w = (sel) => { const e = document.querySelector(sel); return e ? Math.round(e.getBoundingClientRect().width) : null; };
  const navHidden = [...document.querySelectorAll('#nav-entries .nav-item')]
    .filter((li) => li.classList.contains('hidden')).map((li) => li.dataset.page);
  const navVisible = [...document.querySelectorAll('#nav-entries .nav-item')]
    .filter((li) => !li.classList.contains('hidden')).map((li) => li.dataset.page);

  return {
    acctName: txt('#acct-name'), acctRole: txt('#acct-role'),
    convItems: document.querySelectorAll('#conv-list li').length,
    convPlaceholder: !!document.querySelector('#conv-list li.empty'),
    convCount: txt('#conv-count'),
    msgChildren: document.querySelector('#messages') ? document.querySelector('#messages').children.length : 0,
    navHidden, navVisible,
    activePage: document.querySelector('#nav-entries .nav-item.active')?.dataset.page || null,
    activePane: document.querySelector('#stage .tabpane.active')?.id || null,
    hash: location.hash,
    maskDisplay: getComputedStyle(document.querySelector('#mask')).display,
    /* P4f 老坑:知识库三个下拉的实测宽度 */
    kbDropdowns: {
      folder: w('#kb-folder-filter'), cat: w('#kb-cat-filter'), audience: w('#kb-audience-filter'),
    },
    /* P4f 走查的「51px 窄条」老坑:上传解析行三个下拉 + 文件选择器 */
    uploadRow: {
      file: w('#f'), vis: w('#vis'), upCat: w('#up-cat'),
      upAudience: w('#up-audience'), upFolder: w('#up-folder'),
    },
    /* 账户卡(搬进左栏后与历史列表重叠,1440/1280 两档都实测到) */
    acctEntry: (() => {
      const e = document.querySelector('#acct-entry');
      if (!e) return null;
      const r = e.getBoundingClientRect();
      return { x: Math.round(r.left), y: Math.round(r.top), w: Math.round(r.width), h: Math.round(r.height) };
    })(),
    convListBox: (() => {
      const e = document.querySelector('#conv-list');
      if (!e) return null;
      const r = e.getBoundingClientRect();
      return { y: Math.round(r.top), bottom: Math.round(r.bottom) };
    })(),
    kbTreeW: w('#folder-tree'), kbDocsW: w('#docs'),
    hOverflowPx: hOverflow,
    overlaps: overlaps.slice(0, 20),
    truncated: trunc.slice(0, 20),
  };
};

/* ---------- 前进 / 后退 / 刷新回位(验收标准第 2 条) ----------
 * 真浏览器按 back()/forward()/reload() 走一遍,读的是 hashchange 之后的真实落点。 */
async function testHistoryNav(page, who, out) {
  const at = async () => page.evaluate(() => ({
    hash: location.hash,
    pane: document.querySelector('#stage .tabpane.active')?.id || null,
    nav: document.querySelector('#nav-entries .nav-item.active')?.dataset.page || null,
  }));
  await page.evaluate(() => { location.hash = '#/chat'; });
  await page.waitForTimeout(350);
  await page.evaluate(() => { location.hash = '#/kb'; });
  await page.waitForTimeout(350);
  await page.evaluate(() => { location.hash = '#/personas'; });
  await page.waitForTimeout(350);
  const steps = [];
  steps.push({ act: 'goto #/personas', ...(await at()) });

  await page.goBack(); await page.waitForTimeout(400); steps.push({ act: 'back()', ...(await at()) });
  await page.goBack(); await page.waitForTimeout(400); steps.push({ act: 'back()', ...(await at()) });
  await page.goForward(); await page.waitForTimeout(400); steps.push({ act: 'forward()', ...(await at()) });
  /* ⚠ 刷新后必须等够时间:刷新走的是 index.html 里的 boot() —— 读 localStorage 的
     token、GET /api/me、再 enter(),全程两次网络往返。第一版只等 1.5s,
     读数 pane=None 被我当成"刷新回位失效",实测是**等少了**(3s 时 pane-kb 正常)。
     判据:等 pane 真的激活,而不是等一个拍脑袋的毫秒数。 */
  await page.reload({ waitUntil: 'commit' });
  await page.waitForFunction(
    () => !!document.querySelector('#stage .tabpane.active'),
    null, { timeout: 20000 },
  ).catch(() => {});
  await page.waitForTimeout(500);
  const afterReload = await at();
  out.push({ role: who, steps, afterReload,
    reloadKeptPage: afterReload.pane === 'pane-kb',
    afterReloadAcct: await page.evaluate(() => (document.querySelector('#acct-name') || {}).textContent || null) });
}

/* goto + 等登录框,带重试。
 * ⚠ 为什么要重试:连着开 5 个 context 跑 20+ 次 goto 时,第二次 context 偶尔
 *   就在首个 goto 上超时(服务 curl 同一时刻是 200,见证据),属本机 Chrome 冷启抖动。
 *   判据:重试仍失败才算数,读数里记 attempts。 */
async function openLogin(page) {
  let last = '';
  for (let i = 1; i <= 3; i++) {
    try {
      await page.goto(BASE + '/', { waitUntil: 'commit', timeout: 20000 });
      await page.waitForSelector('#login-box', { state: 'visible', timeout: 15000 });
      return i;
    } catch (e) {
      last = String((e && e.message) || e).slice(0, 120);
      await page.waitForTimeout(1200);
    }
  }
  throw new Error('三次 goto 都失败: ' + last);
}

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const report = { base: BASE, chrome: CHROME, viewports: [], errors: [], historyNav: [] };
  const browser = await chromium.launch({
    executablePath: CHROME,
    headless: true,
    /* ⚠ 必须显式关代理:本机系统代理会把 127.0.0.1 也带走,page.goto 直接超时 30s。
       环境变量 NO_PROXY 对 Chromium 无效(它读的是系统/自己的代理设置)。踩过一次。 */
    args: ['--no-proxy-server', '--disable-gpu'],
  });

  /* 第一遍:前进/后退/刷新回位(单独一个 context,避免与截图循环的状态互相污染) */
  for (const who of [{ role: 'counselor', u: 'counselor', p: 'counselor123' },
                     { role: 'student', u: 'student', p: 'student123' }]) {
    const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    const page = await ctx.newPage();
    await openLogin(page);
    await page.fill('#u', who.u); await page.fill('#p', who.p);
    await page.click('button:has-text("登 录"), #login-box button').catch(() => {});
    await page.waitForTimeout(1200);
    await testHistoryNav(page, who.role, report.historyNav);
    await ctx.close();
  }

  for (const vp of VIEWPORTS) {
    for (const who of [{ role: 'counselor', u: 'counselor', p: 'counselor123' },
                       { role: 'student', u: 'student', p: 'student123' }]) {
      const ctx = await browser.newContext({ viewport: { width: vp.width, height: vp.height } });
      const page = await ctx.newPage();
      const pageErrors = [];
      page.on('pageerror', (e) => pageErrors.push(String(e && e.message || e)));
      page.on('console', (m) => { if (m.type() === 'error') pageErrors.push('console: ' + m.text()); });

      /* ⚠ waitUntil 用 'commit' 再显式等登录框:本机上有一个资源让
         'domcontentloaded' 一直不触发(实测 commit 立刻成功、dcl 10s 超时,
         两者都不是脚本错误 —— 故不追查是哪个资源,改用不依赖它的等法)。 */
      const attempts = await openLogin(page);
      await page.fill('#u', who.u);
      await page.fill('#p', who.p);
      await page.click('button:has-text("登 录"), #login-box button').catch(() => {});
      await page.waitForTimeout(1200);

      const seen = [];
      for (const p of PAGES) {
        /* 学生点不到 staffOnly 页:直接改 hash 也应被挡回(顺带验越权回落) */
        await page.evaluate((id) => { location.hash = '#/' + id; }, p.id);
        await page.waitForTimeout(700);
        const probe = await page.evaluate(PROBE);
        probe.requested = p.id;
        probe.pageErrors = pageErrors.slice();
        probe.gotoAttempts = attempts;
        const file = `${vp.name}_${who.role}_${p.id}.png`;
        await page.screenshot({ path: path.join(OUT, file), fullPage: false });
        probe.shot = file;
        seen.push(probe);
      }
      report.viewports.push({ viewport: vp.name, role: who.role, pages: seen });
      await ctx.close();
    }
  }
  await browser.close();
  fs.writeFileSync(path.join(OUT, 'p5_shots_report.json'), JSON.stringify(report, null, 2), 'utf-8');
  console.log(JSON.stringify({ ok: true, out: OUT, files: fs.readdirSync(OUT).length }));
})().catch((e) => {
  console.log(JSON.stringify({ ok: false, error: String((e && e.stack) || e) }));
  process.exit(1);
});