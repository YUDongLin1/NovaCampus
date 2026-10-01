/* P4b-0 拆分:本文件内容由 index.html 原样迁移(零修改),行为零变化。 */
// 应用外壳(enter/switchTab)、弹窗、设置、消息 UI 原语

async function enter() {
  $('mask').style.display = 'none';
  $('role-badge').textContent = ME.username + ' · ' + ROLE_ZH[ME.role];
  /* P5-1:入口可见性由 renderNav() 统一按角色渲染(整条隐藏而不是禁用 ——
     禁用会让人以为「我有权限、只是暂时不能用」)。
     ⚠ 这里**只是体验层**:周报/工作记录的真实拦截在后端 require_role,
     学生绕过 UI 直连接口仍拿 403(P5 第四节:两层都要)。 */
  if (!isStaff()) {
    $('tab-records').style.display = 'none'; $('tab-weekly').style.display = 'none';
  } else {
    $('upload-row').style.display = 'flex';
    $('import-row').style.display = 'flex';
    $('tab-records').style.display = ''; $('tab-weekly').style.display = '';
  }
  // 学生没有建/改人设的权限 —— 顶部「新建人设」按钮不渲染(P5 第四节矩阵)
  const pn = $('personas-new'); if (pn) pn.style.display = isStaff() ? '' : 'none';
  $('acct-name').textContent = ME.username;
  $('acct-role').textContent = ROLE_ZH[ME.role];
  $('acct-avatar').textContent = (ME.username || '?')[0].toUpperCase();
  mountAvatarSprite();          // P5-2:头像雪碧图(幂等)
  renderNav();
  await loadHistory();
  /* 刷新后回到同一页:URL 上带 #/kb 就落在知识库页。
     默认会话页 —— 改版前默认是知识库,而用户进来第一件事是**提问**,
     落会话页才不挡路。 */
  switchPage(hashToPage(location.hash));
  addMsg('bot', '你好，' + ME.username + '（' + ROLE_ZH[ME.role] + '）。可以问学校政策流程，也可以让我记工作碎片、写周报。');
}

function openModal(title, html) { $('modal-title').textContent = title; $('modal-body').innerHTML = html; $('modal').style.display = 'flex'; }
function closeModal() { $('modal').style.display = 'none'; }
$('modal').addEventListener('click', e => { if (e.target.id === 'modal') closeModal(); });

async function openSettings() {
  try {
    const s = await api('/api/me/settings');
    window._settings = s;
    openModal('设置', `
      <div class="detail-label">对话模型</div>
      ${s.candidates.map(m => `
        <label class="radio-line">
          <input type="radio" name="m" value="${m.id}" ${!s.custom.enabled && m.id === s.model ? 'checked' : ''}>
          ${m.label}
        </label>`).join('')}
      <div class="cust-box">
        <label class="radio-line" style="font-weight:600">
          <input type="radio" name="m" id="m-custom" ${s.custom.enabled ? 'checked' : ''}>
          使用自定义 API（OpenAI 兼容）
        </label>
        <div class="detail-label">模型名称</div>
        <div class="row"><input id="cust-model" placeholder="如 deepseek-chat / gpt-4o / glm-4" value="${esc(s.custom.model || '')}"></div>
        <div class="detail-label">Base URL</div>
        <div class="row"><input id="cust-url" placeholder="如 https://api.deepseek.com/v1" value="${esc(s.custom.base_url || '')}"></div>
        <div class="detail-label">API Key ${s.custom.api_key_set ? '（已保存，留空则沿用）' : ''}</div>
        <div class="row"><input id="cust-key" type="password" placeholder="${s.custom.api_key_set ? '••••••••（已保存）' : 'sk-...'}"></div>
        <div class="row">
          <button class="btn ghost" onclick="testModel()">测试连接</button>
          <span id="test-result" style="font-size:12px;color:var(--muted)"></span>
        </div>
      </div>
      <p id="settings-tip">保存后对新对话即刻生效。自定义 API 优先于上方候选；生成内容请在保存前人工核对。</p>
      <div class="row" style="margin-top:12px">
        <button class="btn" onclick="saveModel()">保存设置</button>
        <button class="btn danger-ghost" onclick="logout()">退出登录</button>
      </div>`);
  } catch (e) { toast(e.message); }
}

function pickedModel() {
  const checked = document.querySelector('input[name=m]:checked');
  if (!checked) return { model: '' };
  if (checked.id === 'm-custom') {
    return { custom: { model: $('cust-model').value.trim(), base_url: $('cust-url').value.trim(), api_key: $('cust-key').value.trim() } };
  }
  return { model: checked.value };
}

async function testModel() {
  const p = pickedModel();
  $('test-result').textContent = '测试中…';
  try {
    const d = await api('/api/me/settings/test', { method: 'POST', json: p });
    $('test-result').textContent = d.ok ? `✅ 连接成功（${d.reply}）` : `❌ ${d.error || '失败'}`;
    $('test-result').style.color = d.ok ? 'var(--ok-tx)' : 'var(--danger)';
  } catch (e) { $('test-result').textContent = '❌ ' + e.message; $('test-result').style.color = 'var(--danger)'; }
}

async function saveModel() {
  try {
    const p = pickedModel();
    const d = await api('/api/me/settings', { method: 'PUT', json: p });
    toast('已保存，当前模型：' + d.effective_model);
    closeModal();
  } catch (e) { toast(e.message); }
}

function addMsg(kind, text) {
  const div = document.createElement('div');
  div.className = 'msg ' + kind; div.textContent = text;
  $('messages').appendChild(div); $('messages').scrollTop = $('messages').scrollHeight;
  return div;
}
