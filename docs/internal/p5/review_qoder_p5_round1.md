# P5 第 1 回复核（Qoder）—— ❌ **一条阻塞缺陷：`enter()` 抛错，登录后整个左栏是半瘫的**

> **先说流程**：负责人转来的这条交回信息**是旧的** —— 它写的是「P4f 第 5 回，commit `a8f910d`」，
> 而那条**已经合并**（`master` `377f1e8`，分支 `task/P4f-persona` 已删）。
> 仓库里真正的新东西是 **`c0c3ebb`（分支 `task/P5-shell`）= P5 应用外壳重构**，
> 而**我没有下发过 P5 开单指令**（上一轮我说的是"你说开始我就写"）。
> 实现本身完成度不低、证据也齐，但**跳过下发流程**这件事要记账：规格依据、验收口径由谁确认，
> 得在回执里与 `docs/P5.md` 对上（见 §4）。
>
> **技术结论**：静态部分我全复验通过；**真浏览器一跑就炸** —— 一条阻塞缺陷，P5 现在**不能合并**。
>
> 复核人：Qoder　分支 `task/P5-shell` @ `c0c3ebb`　日期 **2026-10-02**　全程假 key 护身符

---

## 1. 复验通过的部分

| 项 | 我的做法 | 结果 |
|---|---|---|
| 边界 | `git diff --name-only master...HEAD` = 26 文件；`refusal.py`/`faithfulness.py`/`run_evals.py`/`cases.json`/`theme.css`/`contacts.json`/`agent.py`/`sims/**`/`mcp/**`/`.env` **零改动** | ✅ |
| 八个自测 | 我逐条现跑：`91 / 158 / 92 / 66 / 107 / 109 / 20 / 33` | ✅ **676 条 exit 全 0** |
| 聚合数 | `_sum_selftest_counts.py` 现算 676 == 文档 676 == 我手加 676 | ✅ 不再手抄 |
| P4f 无回归 | 上述前五项条数与合并时一致（`frontend_contract` 99→107 是新增断言） | ✅ |
| persona API 行为 | 我在**库副本**上建 3 个人设（带 `avatar`）→ 学生侧 `GET /api/personas` | ✅ `avatar` 存取正常；学生只见 2 个 public；**`persona_prompt` 长度 0**（P4f ② 的脱敏在 P5 之后仍生效） |
| 零额度 | `docs/p5/evidence/` 全量 grep `openrouter\|dashscope\|siliconflow\|sk-\|Bearer` | ✅ 无出网痕迹 |
| 资源接线 | 真机 `:8991`（库副本 + 假 key）加载页面，10 个 `<script>` 全部 200 | ✅ 无 404 资源 |

## 2. ❌ 阻塞缺陷：`ui.js:12` 与 `:16` 还引用被 P5 删掉的元素，`enter()` 直接抛错

P5 把「知识库 / 工作记录 / 周报」从右侧 tab 抽屉搬成了主区整页，**`#tab-records` 与 `#tab-weekly` 这两个 id 已经从 `index.html` 消失**
（我实测 `grep -c 'id="tab-records"' = 0`），但 `ui.js` 的 `enter()` 里还留着旧代码：

```js
if (!isStaff()) {
  $('tab-records').style.display = 'none'; $('tab-weekly').style.display = 'none';   // 第 12 行
} else {
  $('upload-row').style.display = 'flex';
  $('import-row').style.display = 'flex';
  $('tab-records').style.display = ''; $('tab-weekly').style.display = '';            // 第 16 行
}
```

`$()` 是 `document.getElementById`，取不到就是 `null` → **两条分支都抛 `TypeError`**。我在真浏览器里直接调 `enter()` 拿到原文：

```
TypeError: Cannot read properties of null (reading 'style')
    at enter (http://127.0.0.1:8991/js/ui.js:12:21)
```

**后果（都是我在真页面实测到的，不是推断）**：`enter()` 在 `renderNav()` 与 `await loadHistory()` **之前**就中断，于是

| 应发生 | 实测 |
|---|---|
| 左栏历史对话列表加载并分组（今天/近 7 天/更早） | `#conv-list` 只有占位 `—`；而 API 侧该账号**有 154 条会话** |
| 欢迎气泡 | `.msg/.bubble` 数量 **0** |
| 账户卡显示用户名与角色 | `#acct-name` 仍是初始占位「未登录」、`#acct-role` 是「—」 |
| 按角色隐藏入口（P5 第四节的体验层那一半） | 学生侧 `#/weekly`、`#/records` 两条入口 `hidden=false`，**照样可见** |
| 刷新后回到同一页 | `switchPage()` 在抛错之后，未执行（我看到的页面能显示，是因为我手动改了 hash，`hashchange` 兜住了 `onEnter`） |

我手动 `await loadConversations()` → **156 个 `li`、分组「今天（70）」正常出现** ——
说明**数据与渲染函数都是好的，坏的是启动链路**。

**为什么 109 条自测没抓到**：`test_p5_shell.py` 做的是「静态接线 + DOM 桩 + 用 node 跑前端纯函数」，
**没有任何一条真的执行 `enter()`**。这正是本项目已经立过的 **坑 60**：
*评测与静态契约对"用户真实走的这条路径"零证明力*；也是坑 71 的另一面 ——
**接线断了，所有断言可以一声不吭**。

## 3. 修法（第 2 回，零额度）

1. `enter()` 里删掉对 `#tab-records`/`#tab-weekly` 的操作（tab 已不存在，角色差异现在由 `renderNav()` 负责），
   `#upload-row`/`#import-row` 这类**仍存在**的元素保留；
   ⚠ 别用 `if ($(x)) $(x).style...` 把问题糊过去 —— 那等于允许下一轮再删元素时继续静默半瘫。
   要删干净，让 `enter()` 只依赖**确实存在**的东西。
2. **必须补一条真执行 `enter()` 的断言**（DOM 桩即可，不必起浏览器），至少覆盖：
   - 以 `counselor` 与 `student` 两种 `ME` 各调一次 `enter()` → **不得抛错**；
   - 调用后 `#conv-list` 有真实条目（不是占位 `—`）；
   - 学生侧 `#nav-entries [data-page=weekly]` 与 `[data-page=records]` 必须 `hidden`；
   - `#acct-name` 等于登录用户名。
   并且要有**反向用例**：把任一 `renderNav()` 调用注释掉 → 断言必须红（证明它真在守）。
3. 建议再加一条**静态不变量**（成本几乎为零、能防整类问题）：
   扫 `web/js/*.js` 里所有 `$('xxx')` 字面量，断言每个 id 都在 `index.html` 里存在。
   这条一旦装上，本次这个缺陷在实现阶段就会被抓住。

## 4. 流程记账（不修代码，但要写清）

- P5 **没有下发指令就被实现**。规格依据算 `docs/P5.md`（我写的四项裁决），但**验收清单没走"下发→交回"这一步**，
  回执里也没引用它。第 2 回请把这行补上：按 `docs/P5.md` 第六节 9 条**逐条自证**（哪条做了、证据文件是哪个、哪条没做为什么）。
- 设计稿要求**两阶段交回**（P5-1 壳层 / P5-2 辅导员页+头像+RBAC），实际是**一个 commit 全交**。
  我不要求重做，但复验面一次变大；下一单起按阶段交。
- 我这轮**还没做完**的验收项（等第 2 回一起看）：1440×900 与 1280×800 两档截图与重叠/截断检查、
  `personas.avatar` 迁移幂等（我自己的库副本探针）、归档列表、浏览器前进/后退、
  知识库「左树右表」在窄视口下的可读性、以及**后端行为零变化**那条新不变量的实测。

## 5. 状态

我起过的 `:8991` 已按端口属主杀净并复查 `closed=True`；走查用的是**库副本**
（`%TEMP%/p5_ui_data`，已删除），**原库零写入**：`documents 65 / chunks 487 / 可见 personas 0 / user_settings 未变`。
工作树已清理（我复跑自测导致 `p5_selftest_output.txt` 出现两行**顺序差异**，已 `git checkout --` 还原）。
