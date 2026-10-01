/* P4b-0 拆分:本文件内容由 index.html 原样迁移(零修改),行为零变化。 */
// 应用外壳(enter/switchTab)、弹窗、设置、消息 UI 原语

async function enter() {
  $('mask').style.display = 'none';
  $('role-badge').textContent = ME.username + ' · ' + ROLE_ZH[ME.role];
  /* P5 第 2 回①【阻塞修复】:这里原先操作的是 `#tab-records` / `#tab-weekly`
     —— 那两个 id 属于「右侧 tab 抽屉」,已随 P5 一起被删掉。`$()` 取不到返回 null,
     两条分支都抛 `TypeError` → `enter()` 在 `renderNav()` 与 `loadHistory()` **之前**中断,
     登录后整个左栏半瘫(历史列表只剩占位、账户卡停在「未登录」、学生侧的
     周报/工作记录入口没被隐藏、刷新回位的 switchPage() 没执行)。
     ⚠ 修法是**删干净**,不是 `if ($(x))` 糊过去:存在性判断会让下一次删元素
     继续静默半瘫(坑 71 的另一面:接线断了所有断言一声不吭)。
     角色差异现在**只有一处**权威实现 = `renderNav()`(见 js/shell.js)。
     已加静态闸门:JS 里出现的每个 `$(…)` 字面量 id 都必须**有人声明**
     (index.html 或 JS 自己渲染的模板),见 test_p4f_frontend_contract.py
     的「id 不变量」断言。 */
  if (isStaff()) {
    $('upload-row').style.display = 'flex';
    $('import-row').style.display = 'flex';
  }
  // 学生没有建/改人设的权限 —— 顶部「新建人设」按钮不渲染(P5 第四节矩阵)
  $('personas-new').style.display = isStaff() ? '' : 'none';
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
