# P5 第 2 回（一条阻塞修复 + 三条补漏）· 开单指令（粘贴给 WorkBuddy）

> 发单人：Qoder　日期：**2026-10-02**　分支：**继续 `task/P5-shell`**，不新建分支
> 第 1 回复核报告：`docs/p5/review_qoder_p5_round1.md`（静态部分全过：26 文件边界干净、
> 八个自测我逐条跑 **676 条 exit 全 0**、现算合计对上、persona 脱敏与 `avatar` 存取在真 API 上正常、证据无出网痕迹）。
> **卡合并的是一条**：真浏览器一跑，`enter()` 抛错，登录后整个左栏半瘫。全程**零额度**。

---

## 0. 先把流程补齐（不修代码，但必须写进回执）

P5 是**没有下发指令就被实现**的：我上一轮只写了设计稿 `docs/P5.md`，没开单。
所以第 2 回的回执里请补两件事：

1. 按 `docs/P5.md` **第六节那 9 条可验收标准逐条自证**：哪条做了、证据文件是哪个、哪条没做以及为什么；
2. 设计稿要求**两阶段交回**（P5-1 壳层 / P5-2 辅导员页+头像+RBAC），这次是一个 commit 全交。
   不要求重做，但**下一单起按阶段交**，并在 commit message 里标 `P5-1` / `P5-2`。

---

## ① 【阻塞】`enter()` 引用已被 P5 删除的元素，登录后左栏半瘫

`novaagent/web/js/ui.js` 第 12 与 16 行仍在操作 `#tab-records` / `#tab-weekly`，
而这两个 id 已经随「右侧 tab 抽屉」一起被 P5 删掉了 → `$()` 返回 `null` → 抛错。
我在真页面里直接调 `enter()` 拿到的原文：

```
TypeError: Cannot read properties of null (reading 'style')
    at enter (http://127.0.0.1:8991/js/ui.js:12:21)
```

**实测后果**（不是推断）：`enter()` 在 `renderNav()` 和 `await loadHistory()` **之前**中断，于是
`#conv-list` 只有占位 `—`（该账号 API 侧有 154 条会话）、欢迎气泡数量 0、
`#acct-name` 停在「未登录」、**学生侧 `#/weekly`、`#/records` 两条入口没被隐藏**、刷新回位的 `switchPage()` 没执行。
我手动 `await loadConversations()` → 156 个 `li` + 分组「今天（70）」正常出现，
**说明数据和渲染函数都是好的，坏的是启动链路**。

**改法**：把这两行对已删除元素的操**删干净**，让 `enter()` 只依赖确实存在的东西。
⚠ **不要用 `if ($(x))` 这种存在性判断糊过去** —— 那等于给下一次"删元素"留静默半瘫的口子。

## ② 【必须】补一条真执行 `enter()` 的断言（这次 109 条全绿的盲区）

`test_p5_shell.py` 是「静态接线 + DOM 桩 + node 跑纯函数」，**没有一条真的调 `enter()`** ——
这就是为什么 676 条全绿而页面是坏的（坑 60：用户真实路径上必须有断言；坑 71：接线断了所有断言一声不吭）。

DOM 桩即可，不必起浏览器，但至少覆盖四条：

1. 以 `ME.role='counselor'` 与 `'student'` 各调一次 `enter()` → **不得抛错**；
2. 调用后 `#conv-list` 有真实条目（不是占位 `—`）；
3. 学生侧 `#nav-entries [data-page=weekly]`、`[data-page=records]` 必须 `hidden`；
4. `#acct-name === ME.username`。

并且**要有反向用例**：把 `renderNav()` 调用注释掉 → 断言必须红（证明它真在守，不是走过场）。

## ③ 【强烈建议，成本几乎为零】装一条静态不变量：JS 里用到的 id 必须存在于 index.html

扫 `web/js/*.js` 里所有 `$('xxx')` / `getElementById('xxx')` 字面量，
断言每个 id 都能在 `index.html` 找到。**这条一旦装上，① 这个缺陷在实现阶段就会红**，
而且以后每次搬 DOM 都自动兜住 —— 属于"把一次性修复变成永久闸门"的那类改动。

## ④ 【第 1 回没做完的验收项，一并补证据】

我这边继续核，但请先把这些证据备齐（都在 `docs/p5/evidence/`）：

- 1440×900 与 1280×800 **两档截图**（每入口至少一张），并说明**有没有重叠/文字截断**；
- `personas.avatar` 迁移在**库副本**上连跑两遍的幂等读数（表/列/索引/计数三向一致）；
- 浏览器**前进/后退**与刷新回位的实测（hash 路由的验收标准第 2 条）；
- 知识库「左树右表」在 1280 宽下的可读性（P4f 走查时三个下拉被压到 51px 就是这个坑）；
- **后端行为零变化**这条新不变量的实测：改版前后同问句走同接口、`sources` 结构一致、落库字段一致
  （用 P4c/P4f 现有断言复跑，别新写一套）。

---

## 白名单

```
novaagent/web/js/ui.js                     # ① 删掉对已删除元素的操作
novaagent/tests/test_p5_shell.py           # ② enter() 真执行断言 + 反向用例
novaagent/tests/test_p4f_frontend_contract.py   # ③ 静态 id 不变量（放哪个文件你定，别两处各写一份）
novaagent/web/**                           # ④ 若截图暴露布局问题，一并修
docs/P5.md docs/P4B0.md docs/TASKS.md docs/HANDOFF.md docs/p5/evidence/*
```

## 禁改

`evals/**`（用例与判据一条都不许动）、`novaagent/novaagent/refusal.py`、`evals/faithfulness.py`、
`novaagent/novaagent/agent.py`、`novaagent/novaagent/data/**`（含 `contacts.json`）、
`novaagent/web/css/theme.css`（设计令牌）、`sims/**`、`mcp/**`、`weknora/**`、`.env`。

## 交回要求

1. **零额度**：假 key 护身符自查（`export LLM_API_KEY=ZERO-QUOTA-PROTECTOR-... EMBEDDING_API_KEY=同值`）。
2. 八个自测全绿 + `_sum_selftest_counts.py` 现算合计 == 文档；命令与退出码写进回执，**不接管道**（坑 55）。
3. **反向闭环自己先走一遍并留原文**：② 的注释掉 `renderNav` → 必须红；③ 故意在 JS 里引用一个不存在的 id → 必须红。
4. 前端走查一律用**库副本 + 独立端口**（`NOVA_DATA_DIR` 指副本），跑完删副本、按端口属主杀净并复查（坑 61/72）。
5. 回执写进 `docs/TASKS.md` P5 段，顶部持棒与 `HANDOFF.md` 台账同步 **IN_REVIEW / 持棒 = Qoder**。

## 我这边并行做什么

- 你交回后我继续第 1 回没做完的 §4 各项（两档视口截图、迁移幂等我自己的副本探针、前进后退、后端行为零变化实测）。
- 全绿才合并。**合并前还需要一次真实模型冒烟**（`--cleanup-only` 核语料 + 冒烟 PASSED），
  免费测试 key 的限流窗口若没恢复，我会等窗口或改用不依赖网络的断言，并在合并记录里写清冒烟是"何时、什么通道、几次跑绿的"。
