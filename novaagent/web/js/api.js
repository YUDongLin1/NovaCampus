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
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(typeof data.detail === 'string' ? data.detail : ('HTTP ' + resp.status));
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
