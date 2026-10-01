/* P4b-0 拆分:本文件内容由 index.html 原样迁移(零修改),行为零变化。 */
// HTTP 封装与认证状态(TOKEN/ME)+ 登录/退出

const $ = id => document.getElementById(id);
let TOKEN = localStorage.getItem('nova_token') || '';
let ME = null, lastReport = null;
const ROLE_ZH = { student: '学生', counselor: '辅导员', admin: '校管理员' };

function toast(t) { const e = $('toast'); e.textContent = t; e.style.display = 'block'; setTimeout(() => e.style.display = 'none', 2600); }
function esc(s) { return (s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;'); }

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

async function login() {
  try {
    const d = await api('/api/login', { method: 'POST', json: { username: $('u').value.trim(), password: $('p').value } });
    TOKEN = d.token; localStorage.setItem('nova_token', TOKEN); ME = d; enter();
  } catch (e) { $('login-err').textContent = e.message; }
}
function logout() { TOKEN = ''; localStorage.removeItem('nova_token'); location.reload(); }

const isStaff = () => ME && ['counselor', 'admin'].includes(ME.role);
