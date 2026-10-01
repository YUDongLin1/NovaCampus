# P5 第 2 回复核（Qoder，零额度）—— ✅ **一条阻塞已修 + 两条永久闸门装上；另发现一条早于 P5 的老缺陷（F5）**

> **结论先行**：① 的修法是对的（**删干净**，没有用 `if ($(x))` 糊），② 的 `enter()` 真执行断言我核过实现、
> ③ 的静态 id 闸门**我自己注入悬空 id 复现出红**，renderNav 的反向用例**我自己注释掉源码复现出红**。
> 真浏览器走查：counselor 登录后历史列表 156 条正常渲染、账户卡显示真名、hash 刷新复原、前进/后退可用、
> 1280×800 与 1440×900 两档**无横向溢出、无元素重叠**（只有会话标题按设计省略号截断）、
> 未知头像 id `av-999` 回落成默认头像不报错。
> **但我在走查里撞到一个学生侧的老 bug**：学生登录后历史列表在启动时**永远不加载** ——
> 我用 master 的独立 worktree 做了 A/B，**改版前就存在**，不是 P5 引入的（F5，另开单修）。
>
> 追认：负责人已确认 P5 为**正式开工**（虽未经我下发指令，流程偏差已在台账记账）。
> 复核人：Qoder　分支 `task/P5-shell` @ `17c29a2`　日期 **2026-10-02**　全程假 key 护身符

---

## 1. 第 1 回三条要求的逐条复验

| 要求 | 我的复验方式 | 结果 |
|---|---|---|
| ① `enter()` 删干净对已删除元素的引用 | 读 diff：`#tab-records`/`#tab-weekly` 两处操作**整段删除**，只保留确实存在的 `#upload-row`/`#import-row`；并且把原来 `const pn = $('personas-new'); if (pn) …` 的**存在性判断也去掉**了（改成硬依赖，方向正确） | ✅ 没有用 `if ($(x))` 糊 |
| ② 真执行 `enter()` 的断言 | 读 `tests/p5_dom_stub.js`：node 里搭最小 DOM + **fetch 桩**，`vm.runInContext('enter()')` 真调一次；断言含「role=counselor/student 不抛错」「`#conv-list` 有真实条目（非占位）」「带 `#/page` hash 真跑」「未知 hash 真跑」；fetch 桩还有一条 **「桩未覆盖的端点 = enter() 打了新请求」直接抛错** —— 这条设计我认可，它让"启动链路偷偷多打一个接口"也会红 | ✅ 148/148（原 109） |
| ② 的反向用例 | **我自己做**：把 `ui.js` 里 `renderNav();` 注释掉 → `test_p5_shell.py` **146/148 退 1**，红的正是「学生侧 weekly/records 入口被隐藏」两条 → `git checkout --` 复原 → 148/148 退 0 | ✅ 证据 `evidence/review/r2_qoder_reverse_rendernav.txt` |
| ③ 静态闸门「JS 引用的 id 必须存在于 index.html」 | **我自己做**：往 `ui.js` 注入 `$('qoder_bogus_id_never_exists')` → `test_p4f_frontend_contract.py` **111/113 退 1**，红项点名悬空 id 与引用方文件 → 复原 → 112/112 退 0 | ✅ 这条闸门装上后，第 1 回那个缺陷在实现阶段就会红 |
| ④ 补证据 | 见下表 | ✅ |

**八个自测我逐条现跑：`91 / 158 / 92 / 66 / 112 / 148 / 20 / 33` = 720 条 exit 全 0**，
`_sum_selftest_counts.py` 现算 720 == 文档 720。边界：`refusal.py`/`faithfulness.py`/`run_evals.py`/
`cases.json`/`theme.css`/`contacts.json`/`agent.py`/`sims/**`/`mcp/**`/`.env` **零改动**。

## 2. 真浏览器走查（我自己跑的，不采信他们的走查文件）

环境：`agent.db` **副本** + `NOVA_DATA_DIR` 指过去 + 假 key 护身符，端口 `:8993`，跑完按端口属主杀净、副本删除，
**原库零写入**（`documents 65 / chunks 487 / 可见 personas 0 / user_settings 未变`）。

| 验收项 | 实测 |
|---|---|
| counselor 登录后左栏 | `#conv-list` **156 个条目**，分组「今天（70）」「近 7 天（84）」；`#acct-name=counselor`、`#acct-role=辅导员`；欢迎气泡在 |
| student 登录后入口 RBAC | `weekly`/`records` 两条 `hidden=true`、`display:none`；`#personas-new` 隐藏；手敲 `#/weekly` 被挡回会话页（`activePage=pane-chat`） |
| hash 路由与复原 | 停在 `#/kb` 刷新 → 仍在知识库页、导航 active 正确 |
| 前进 / 后退 | `history.back()` → `''`（会话页）；`history.forward()` → `#/kb` ✅ |
| 辅导员页 | 4 张 `.pcard`，头像 52×52 各自不同；**未知 id `av-999` 回落默认头像、不报错**；卡面不显示 prompt 正文 |
| 1440×900 / 1280×800 | `overflowX=false`、无元素越出父容器；唯一"截断"是会话标题 `.ct` 的**按设计省略号**（want 181 / got 155） |
| `personas.avatar` 迁移 | 我在**副本**上连跑两遍 `_migrate()`：列存在、两遍 schema/列/索引/计数**三向一致**、`documents=65 chunks=487` 未丢 |

截图入库：`docs/p5/evidence/review/qoder_kb_1440.png`、`qoder_personas_1440.png`、`qoder_personas_1280.png`。

**一处视觉 nit（不阻塞）**：卡片 meta 行会**中途换行**（「信息学院 · 详尽」拆成两行、「学工部 · 条理清晰」断成「条 / 理清晰」），
建议给 `.pcard` 的 meta 加 `white-space: nowrap` + 溢出省略，或把「学院 · 风格」拆成两个字段各占一行。

## 3. ⚠ F5：学生登录后历史列表在启动时永远不加载 —— **早于 P5 就存在**

**症状**（我在 `:8993` 的 P5 版上先看到，随后在 **master 独立 worktree `:8994`** 上复现，**两边一模一样**）：

```
student 刷新后：#conv-list 只有占位「—」；performance 资源列表只有 /api/me 与 /api/personas
—— /api/conversations 根本没发出去。
```

**定位过程**（都是实测，不是猜）：

| 实验 | 结果 |
|---|---|
| 直接 `await loadConversations()` | ✅ 201 个条目立刻出现 → 数据与渲染函数都是好的 |
| `Promise.race([loadPersonas(), 3s 超时])` | ⚠ **personas-HUNG** —— `loadHistory()` 里 `await loadPersonas()` 在**启动那一次**不 resolve，于是后面的 `loadConversations()` 永远轮不到 |
| 稍后再调 `api('/api/personas')` / `loadPersonas()` | ✅ 秒回（该学生 `personas` 为 0 条）→ 不是网络、不是后端 |
| 手动 `await enter()` | ✅ 列表 201 条 → 说明 enter() 本身没问题，是**启动时序**里第一次卡住 |
| counselor 同版本 | ✅ 正常（156 条）→ **学生侧特有** |
| **master（P4f 版）worktree 同样测** | ⚠ **一模一样卡住** → **不是 P5 引入的回归** |

**归因**：`chat.js:loadHistory()` 用 `await loadPersonas()` 串在 `await loadConversations()` **前面**，
而 `loadPersonas()` 在"学生 + 启动首次"这条路径上有一次不 resolve（其内部 `try/catch` 只包了 fetch，
`renderPersonaBar()` 在 catch 之外 —— 若它同步抛错，`loadPersonas` 的 promise 会以 rejected 结束，
`loadHistory` 又没 catch，于是**静默吞掉**、后面的加载全断）。
⚠ 这一段是**假设**，我没有在页面里抓到那条 rejection（console 无记录），第 3 回请按上面表格逐条复现确认，别照抄我的归因。

**为什么 720 条自测全绿看不见它**：② 的 DOM 桩 fetch 桩是"按端点返回预置数据"，
**桩里的 `/api/personas` 一定 resolve**，所以桩测天然测不到"真后端 + 学生 + 首屏"这个组合。
这不是要怪桩测 —— 而是说明**还缺一层**：`loadHistory()` 里任何一步失败都**必须留痕**（toast 或 console.error），
不能静默让后面的加载全断。

**修法建议（第 3 回或单独一张小单，零额度）**：
1. `loadHistory()` 每一步**独立 try/catch 且互不阻塞**（personas 挂了不能连累会话列表）；
2. 失败必须**可见**（`console.error` + toast），不许静默；
3. 补一条断言：`loadPersonas` 抛错时 `#conv-list` **仍然有真实条目**（证明解耦真的生效）；
4. 顺带把这条列进 `docs/TASKS.md` 技术债，**不要塞回 P5**（P5 已经两轮回交，别扩大改动面）。

## 4. 裁决

**P5 第 2 回 ✅ 通过**：第 1 回那条阻塞已修，两条永久闸门（enter 真执行 + id 静态不变量）都经我亲手复现过红。
F5 是**改版前就有的老缺陷**，不并入 P5，另开一张小单（或作为 P5-3 / T11 技术债）。
合并前还需要：① 生产同档（DashScope `qwen-flash`）整轮 —— **正在跑**（负责人已授权用 `.env` 额度，
在 master 的独立 worktree 上跑两档，跑完把报告拷回主仓并**在 HANDOFF 明记"本轮经授权花用户额度"**）；
② 合并后在 master 上复跑一次冒烟。
