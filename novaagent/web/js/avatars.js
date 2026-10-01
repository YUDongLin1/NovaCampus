/* P5-2 内置头像库:16 个内联 SVG 符号,**零外部依赖**(不引字体/图片/CDN)。
 *
 * 【为什么存逻辑 id 而不是路径/base64】
 *   `personas.avatar` 只存 `'av-07'` 这样的 id。将来换画风、加第 17 个头像,
 *   只要前端这个映射表改一行,**库里一条数据都不用迁移**(P5 §3.5)。
 *   存路径会把「某次改版换了目录」变成一堆 404;存 base64 会把几十 KB 塞进
 *   SQLite 并污染每一个 API 响应。
 *
 * 【区分维度】
 *   只用**配色 / 发型 / 配饰**三项组合,**不绑定职业、不绑定性别**(P5 §3.5 红线)。
 *   id 是流水号,id 本身不携带任何人物属性语义。
 *
 * 【红线】
 *   不含任何真实人物形象、不含校徽/校名图形、不含真实学工数据 —— 全部是抽象几何形。
 */
const AVATAR_SPECS = [
  { id: 'av-01', bg: '#e3ecf6', cloth: '#5b6f86', skin: '#f7dcc7', hair: '#39485a', style: 'short', acc: 'none' },
  { id: 'av-02', bg: '#eae7f4', cloth: '#6b5f8c', skin: '#f7dcc7', hair: '#4a3f63', style: 'short', acc: 'glasses' },
  { id: 'av-03', bg: '#e6f2ea', cloth: '#3f6f56', skin: '#f2d3ba', hair: '#2f4a3c', style: 'long', acc: 'none' },
  { id: 'av-04', bg: '#f7eee2', cloth: '#9a6b23', skin: '#f7dcc7', hair: '#5a3f1e', style: 'bun', acc: 'none' },
  { id: 'av-05', bg: '#f6e7e1', cloth: '#bf3b2b', skin: '#f2d3ba', hair: '#3b2a26', style: 'short', acc: 'none' },
  { id: 'av-06', bg: '#e6f0f5', cloth: '#2f5f75', skin: '#f7dcc7', hair: '#25485a', style: 'cap', acc: 'none' },
  { id: 'av-07', bg: '#efe9f6', cloth: '#7a5f95', skin: '#f2d3ba', hair: '#463559', style: 'long', acc: 'glasses' },
  { id: 'av-08', bg: '#e9efe6', cloth: '#4f6b3f', skin: '#f7dcc7', hair: '#33452a', style: 'short', acc: 'scarf' },
  { id: 'av-09', bg: '#f7e9ef', cloth: '#a8476b', skin: '#f7dcc7', hair: '#4a2b39', style: 'long', acc: 'none' },
  { id: 'av-10', bg: '#e8f1f4', cloth: '#386f7a', skin: '#f2d3ba', hair: '#2a4b52', style: 'bun', acc: 'glasses' },
  { id: 'av-11', bg: '#f4efe4', cloth: '#8a6f3f', skin: '#f7dcc7', hair: '#4f3d22', style: 'long', acc: 'scarf' },
  { id: 'av-12', bg: '#e4eaf7', cloth: '#4a5f96', skin: '#f2d3ba', hair: '#2e3a5c', style: 'short', acc: 'none' },
  { id: 'av-13', bg: '#eaf0e8', cloth: '#54703f', skin: '#f7dcc7', hair: '#35472a', style: 'cap', acc: 'glasses' },
  { id: 'av-14', bg: '#f6eae4', cloth: '#a05a33', skin: '#f2d3ba', hair: '#4a2f1c', style: 'short', acc: 'none' },
  { id: 'av-15', bg: '#e7e9f5', cloth: '#5a5f92', skin: '#f7dcc7', hair: '#33375c', style: 'bun', acc: 'scarf' },
  { id: 'av-16', bg: '#e9f1ef', cloth: '#3c6a63', skin: '#f2d3ba', hair: '#274541', style: 'long', acc: 'none' },
];

const AVATAR_IDS = AVATAR_SPECS.map(s => s.id);
const AVATAR_DEFAULT_ID = AVATAR_IDS[0];

/** 未知 id 一律回落到默认头像(**不抛错**)。前向兼容:将来加了 av-17,
 *  老前端照样渲染出一个头像而不是破图(纯函数,自测直接调用)。 */
function avatarId(id) {
  return AVATAR_IDS.indexOf(id) >= 0 ? id : AVATAR_DEFAULT_ID;
}

function _hairPath(style, hair) {
  if (style === 'long') {
    return `<path d="M13 22a11 11 0 0 1 22 0v9c0 5-2 8-4 9-1-6-1-11-1-14-3 2-9 2-12 0 0 3 0 8-1 14-2-1-4-4-4-9z" fill="${hair}"/>`;
  }
  if (style === 'bun') {
    return `<circle cx="24" cy="9" r="4" fill="${hair}"/>` +
           `<path d="M14 20a10 10 0 0 1 20 0c0-6-4-10-10-10s-10 4-10 10z" fill="${hair}"/>`;
  }
  if (style === 'cap') {
    return `<path d="M13 18a11 11 0 0 1 22 0z" fill="${hair}"/>` +
           `<rect x="12" y="16" width="24" height="4" rx="2" fill="${hair}"/>`;
  }
  return `<path d="M14 20a10 10 0 0 1 20 0c0-6-4-10-10-10s-10 4-10 10z" fill="${hair}"/>`;
}

function _accPath(acc, ink) {
  if (acc === 'glasses') {
    return `<g fill="none" stroke="${ink}" stroke-width="1.4" opacity=".75">
      <circle cx="19" cy="22" r="3.4"/><circle cx="29" cy="22" r="3.4"/>
      <path d="M22.4 22h2.2"/></g>`;
  }
  if (acc === 'scarf') {
    return `<path d="M16 35c3 3 13 3 16 0-1 3-4 4-8 4s-7-1-8-4z" fill="${ink}" opacity=".55"/>`;
  }
  return '';
}

function avatarSymbol(s) {
  return `<symbol id="${s.id}" viewBox="0 0 48 48">` +
    `<rect width="48" height="48" rx="16" fill="${s.bg}"/>` +
    `<path d="M9 48c2-10 8-14 15-14s13 4 15 14z" fill="${s.cloth}"/>` +
    `<circle cx="24" cy="23" r="9.5" fill="${s.skin}"/>` +
    _hairPath(s.style, s.hair) +
    _accPath(s.acc, s.cloth) +
    `</symbol>`;
}

function avatarSpriteMarkup() {
  return '<svg xmlns="http://www.w3.org/2000/svg" style="display:none" aria-hidden="true">' +
    AVATAR_SPECS.map(avatarSymbol).join('') + '</svg>';
}

/** 把雪碧图挂进 DOM(幂等:已有就不再插一份)。 */
function mountAvatarSprite() {
  if (document.getElementById('avatar-sprite')) return;
  const wrap = document.createElement('div');
  wrap.id = 'avatar-sprite';
  wrap.innerHTML = avatarSpriteMarkup();
  document.body.appendChild(wrap);
}

/** 渲染一个头像。<use> 引用雪碧图里的符号,故**不重复**内联 16 份图形。 */
function avatarSvg(id, size) {
  const s = size || 44;
  return `<svg class="av-svg" viewBox="0 0 48 48" width="${s}" height="${s}" aria-hidden="true">` +
    `<use href="#${avatarId(id)}"/></svg>`;
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = {
    AVATAR_SPECS, AVATAR_IDS, AVATAR_DEFAULT_ID,
    avatarId, avatarSymbol, avatarSpriteMarkup,
  };
}
