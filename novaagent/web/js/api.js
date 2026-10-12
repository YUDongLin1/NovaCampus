/* P4b-0 拆分:本文件内容由 index.html 原样迁移(零修改),行为零变化。 */
// HTTP 封装与认证状态(TOKEN/ME)+ 登录/退出

const $ = id => document.getElementById(id);
let TOKEN = localStorage.getItem('nova_token') || '';
let ME = null, lastReport = null;
const ROLE_ZH = { student: '学生', counselor: '辅导员', admin: '校管理员' };

function toast(t) { const e = $('toast'); e.textContent = t; e.style.display = 'block'; setTimeout(() => e.style.display = 'none', 2600); }
function esc(s) { return (s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;'); }

/* 未捕获的脚本错误必须**让用户看见**。内联 onclick 指向的函数不存在时(混版、脚本没
   加载、文件名拼错),浏览器只往 console 丢一条 ReferenceError,页面上的表现就是
   「按钮点了没反应,不转圈也不报错」—— 这条比"报错弹窗"危险,因为用户无从判断是
   自己操作错了还是系统坏了。 */
window.addEventListener('error', (e) => {
  if (e && e.message) toast('页面脚本异常：' + e.message + '（按 Ctrl+F5 重新载入可取回最新脚本）');
});

async function api(path, opts = {}) {
  opts.headers = Object.assign({}, opts.headers, TOKEN ? { Authorization: 'Bearer ' + TOKEN } : {});
  if (opts.json) { opts.headers['Content-Type'] = 'application/json'; opts.body = JSON.stringify(opts.json); }
  const resp = await fetch(path, opts);
  /* P5-1:顺手记下**服务端时间**(HTTP Date 响应头)。
     历史对话要按「今天 / 近 7 天 / 更早」分组,判据必须是服务端时间 ——
     用浏览器本地时区的话,演示机时区(或用户改了系统时间)一变分组边界就飘,
     而飘的是**展示**不是数据,极难归因(验收标准 §3.2 明确点名这条)。 */
  try {
    const sv = resp.headers && resp.headers.get ? resp.headers.get('Date') : null;
    if (sv) { const ms = Date.parse(sv); if (ms) window._serverNowMs = ms; }
  } catch (e) { /* 拿不到就沿用上次/本地时间,不连坐业务请求 */ }
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    // 坑 30 消费端同步(P4c): {code,reason,hint} 结构化错误渲染为可读文案
    const dt = data.detail;
    let msg = 'HTTP ' + resp.status;
    if (typeof dt === 'string') msg = dt;
    else if (dt && typeof dt === 'object') msg = [dt.reason, dt.hint].filter(Boolean).join('：') || msg;
    throw new Error(msg);
  }
  return data;
}

/** 带认证头的文件下载:fetch 取 blob → 临时 <a download> 触发保存。
 *  不能用裸 `<a href>` —— 下载接口要 `Authorization: Bearer`,<a> 带不上这个头。 */
async function downloadFile(path, fallbackName) {
  const resp = await fetch(path, { headers: TOKEN ? { Authorization: 'Bearer ' + TOKEN } : {} });
  if (!resp.ok) {
    let msg = 'HTTP ' + resp.status;
    try { const d = await resp.json(); if (typeof d.detail === 'string') msg = d.detail; }
    catch (e) { /* 错误体不是 JSON 就用状态码 */ }
    throw new Error(msg);
  }
  const cd = resp.headers.get('Content-Disposition') || '';
  let name = fallbackName || 'download';
  const star = /filename\*=UTF-8''([^;]+)/i.exec(cd);
  if (star) { try { name = decodeURIComponent(star[1]); } catch (e) { /* 保留兜底名 */ } }
  const url = URL.createObjectURL(await resp.blob());
  const a = document.createElement('a');
  a.href = url; a.download = name;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 4000);
  return name;
}

async function login() {
  try {
    const d = await api('/api/login', { method: 'POST', json: { username: $('u').value.trim(), password: $('p').value } });
    TOKEN = d.token; localStorage.setItem('nova_token', TOKEN); ME = d; enter();
  } catch (e) { $('login-err').textContent = e.message; }
}
function logout() { TOKEN = ''; localStorage.removeItem('nova_token'); location.reload(); }

const isStaff = () => ME && ['counselor', 'admin'].includes(ME.role);
