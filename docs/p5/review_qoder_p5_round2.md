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

## 3. ⚠ 学生首屏历史列表不加载 —— **不是 P5 引入**，且**归因以 WorkBuddy 的 T11 为准**

**症状**（我在 `:8993` 的 P5 版上先看到，随后在 **master 独立 worktree `:8994`** 上复现，两边一模一样）：
student 刷新后 `#conv-list` 只有占位「—」，`performance` 资源列表只有 `/api/me` 与 `/api/personas`，
**`/api/conversations` 根本没发出去**。

**我实测到的四件事**：

| 实验 | 结果 |
|---|---|
| 直接 `await loadConversations()` | ✅ 201 条立刻出现 → 数据与渲染函数都是好的 |
| `Promise.race([loadPersonas(), 3s])` | ⚠ **HUNG**（启动那一次不 resolve） |
| 稍后再调 `api('/api/personas')` / `loadPersonas()` | ✅ 秒回 → 不是网络、不是后端持续故障 |
| counselor 同版本 | ✅ 正常（156 条）→ 学生侧更易触发 |
| **master（P4f 版）同样测** | ⚠ **一模一样卡住** → **不是 P5 的回归** |

**归因更正（重要）**：我上一稿把这条写成 F5，并猜「`loadHistory()` 里 `await loadPersonas()` 的 rejection
被静默吞掉」，还写了"建议按我的表格复现确认"。**WorkBuddy 在第 2 回回执里已经把同一条症状查到更深一层**，
并登记为技术债 **T11**：`db.py` 单例 `_conn` + `check_same_thread=False`，而 FastAPI 的 `Depends` 经
`anyio.run_in_threadpool` 在**多个工作线程**里用它，**31 个读函数全部无锁**（含 `user_by_token`、
`list_conversations`）→ 同一 `Connection` 被并发 `execute` → `sqlite3.InterfaceError` → 依赖链炸掉 →
请求挂起，前端表现正是「`enter()` 卡在 `await loadHistory()`」。他们的症状记录是
「counselor 刷新约 2s 正常，**student 连续 3 次 20s 超时**」。

**所以：这条不是新缺陷 F5，是 T11 的客户端可见面；我不另开一张单，并入 T11。**
⚠ 但有一处**我的读数与 T11 的叙述还没对上**，留给修的人注意：我这次看到的两个 fetch
**都已完成**（`/api/personas` 5ms 返回 200），卡住的是**它之后** `loadPersonas()` 的 promise 未 settle，
且 `/api/conversations` **从未发出**。这与"请求在服务端挂住"不完全是同一个形状。
可能是同一根因的另一种表现（服务端把连接搞坏后，前端 `api()` 的某个 await 永远不返回），
也可能是**两处独立问题**。**请以 T11 为母单，先复现我上面那张表，再决定要不要拆第二张。**

**为什么 720 条自测看不见它**：② 的 DOM 桩里 `/api/personas` 一定 resolve，桩测天然测不到
「真后端 + 并发连接坏掉 + 首屏」这个组合。这不是桩测的错，但推出一条要求：
**启动链路上任何一步失败/挂起都必须留痕**（`console.error` + toast），
不能静默让后面的加载全断 —— 这条建议随 T11 一起做。

## 4. 裁决

**P5 第 2 回 ✅ 通过**：第 1 回那条阻塞已修，两条永久闸门（enter 真执行 + id 静态不变量）都经我亲手复现过红。
首屏卡死那条**不是 P5 引入**，且 WorkBuddy 已查到更深一层并登记为 **T11**（`db` 单例连接跨线程不安全）→ 并入 T11，不另开单、不阻塞 P5。
合并前还需要：① 生产同档（DashScope `qwen-flash`）整轮 —— **正在跑**（负责人已授权用 `.env` 额度，
在 master 的独立 worktree 上跑两档，跑完把报告拷回主仓并**在 HANDOFF 明记"本轮经授权花用户额度"**）；
② 合并后在 master 上复跑一次冒烟。
