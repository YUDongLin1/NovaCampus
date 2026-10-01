# P4f 第 5 回（两条收尾：冒烟的通道守卫 + F3 上传原子性）· 开单指令（粘贴给 WorkBuddy）

> 发单人：Qoder　日期：**2026-10-01**　分支：**继续 `task/P4f-persona`**
> 第 4 回复核：✅ **⑥ 修完并被我验穿**（报告 `docs/p4f/review_qoder_p4f_round4.md`）——
> 我拿 15 条自造样本原样重打：两个假绿（URL / 小数）现在判红，五种**裸编造**（含"先承认没有再跨分句编"）
> 仍全部判红，噪声项清零；`_sum_selftest_counts.py` 现算合计 532 == 文档 532 == 我手加 532。
> **v2.5 两档整轮已经跑出来了**（canonical **57/59**、R@k 1.0、忠实度 **0.9722(llm)**、拒答 1.0、
> `env_error=0`、隔离 55/55 成立）——见 `docs/EVAL_BASELINE.md` §20.7。
> **只剩冒烟这一道门没过关**，而且原因有两条是你的 ③ 与 F3 造成的，所以是第 5 回而不是直接合并。
> 全程**零额度**。

---

## 0. 为什么还不合并（把话说白）

合并闸门要求「验收命令 + 冒烟 + 评测」三件都绿。评测已经绿（除两条**通道根本不支持**的联网用例）。
冒烟我连跑三次都过不去，**两次是代码问题、一次是额度问题**：

| 次 | 端口 | 失败点 | 归因 |
|---|---|---|---|
| 1 | `:8973` | `[13]` `assert smoke_model in _cands` → `NOVA_SMOKE_MODEL='qwen/qwen-plus' 不在候选 ['qwen-flash','qwen3.7-plus']` | **③ 的新守卫本身是缺陷**（见 ⑨） |
| 2 | `:8974` | 同一条 assert | 同上 |
| 3 | `:8975` | `[3]` 上传 → `/api/kb/upload` 500（上游 **429**） | 额度窗口（第 4 条坑），**但炸在上传处却留下 3 篇孤儿文档** → F3 |

而且**每一次失败都往知识库里留 3 篇脏文档**（`65/487 → 68/490` 三次），我手工清了三轮。
`--cleanup` 不是"只清理"，它是"先清理再跑完整套"，所以每跑一次失败的冒烟就重新污染一次 —— 这个设计要一起改。

---

## ⑨ 冒烟的通道守卫写反了：非 DashScope 通道**根本跑不了**冒烟

`MODEL_CANDIDATES` 是**内置 DashScope 候选清单**，而 `PUT /api/me/settings {"model":X}` 只接受清单内的值。
你在 ③ 里加的 `assert smoke_model in _cands` 于是变成：**只要换了通道（这正是额度纪律要求的能力），
冒烟第 13 步必炸**。第 340 行已经有一条「检测到自定义通道就跳过」的分支，
但它的触发条件是"用户配了 custom API"，**覆盖不到"全局 config 指向非候选模型"这一种**。

**改法**：
- 判据从「模型名必须在候选里」改成「**当前通道是不是内置通道**」：
  `config.LLM_BASE_URL` 属于内置 DashScope 域 → 才做 `[13]` 的合法/非法切换断言；
  否则打印 `[13][skip] 内置模型切换不适用于自定义通道（base_url=…）` 并**跳过**，**不 assert 炸**；
- `bad-model → 400` 那条反向断言**保留在内置通道分支里**（它验的是 API 校验，不是通道）；
- 新增一条能判红的自测：伪造 `LLM_BASE_URL=https://openrouter.ai/api/v1` → `[13]` 必须走 skip 分支
  且**整轮冒烟不因此判红**；伪造回 DashScope 域 → `[13]` 必须真的执行切换与还原。

## ⑩ 冒烟与上传都不许"炸了就留脏"

两件事一起修：

1. **F3（我第 2 轮回核时提的产品缺陷，现在它直接挡路）**：
   `/api/kb/upload` 是 `insert_document` → `insert_chunks` → **之后**才 `summarize_document`；
   摘要调用失败（429/400/超时）→ 接口 500，但**文档与分块已经落库**。
   **改法**：摘要失败**回滚整条写入**（删掉刚插入的 document 与 chunks，或先写占位、摘要成功后再更新），
   并**必须**有一条能判红的自测：mock `agent.summarize_document` 抛异常 →
   断言 `POST /api/kb/upload` 返回非 2xx **且** `documents`/`chunks` 计数**不变**。
   ⚠ 这条改的是 `main.py` 上传路径的**顺序/回滚**，**不许碰** `refusal.py`、检索、闸门。
2. **冒烟自清理要进 `finally`**：现在 `[18]` 在正常路径末尾，中途任何 assert/异常都不会执行 → 每次失败留 3 篇。
   把"删除本次冒烟文档"放进 `finally`（或 `try/except` 后统一收尾），并让 `--cleanup` **支持只清理不跑**
   （例如 `--cleanup-only`：清完就退出，打印删掉的 id 列表）。

---

## 白名单

```
novaagent/tests/smoke_test.py        # ⑨ 通道判据 + ⑩ finally 自清理 + --cleanup-only
novaagent/novaagent/main.py          # ⑩ F3 上传回滚（只动 kb_upload 的写入顺序/回滚，别碰别的）
novaagent/tests/test_p4f_c0.py       # ⑨⑩ 的新断言（或新建 test_p4f_smoke_channel.py）
novaagent/tests/_sum_selftest_counts.py  # 若新增自测文件，把 EXPECTED_TOTAL 现算逻辑同步
docs/P4F.md docs/TASKS.md docs/p4f/evidence/*
```

## 禁改

`evals/cases.json`、`evals/run_evals.py`（第 4 回已定稿，别再动判据）、
`novaagent/novaagent/refusal.py`、`evals/faithfulness.py`、`novaagent/novaagent/agent.py`
（**摘要函数本身别改签名**，要改的是调用顺序）、`novaagent/novaagent/data/**`（含 `contacts.json`）、
`sims/**`、`mcp/**`、`weknora/**`、`theme.css`、`.env`。

## 交回要求

1. **零额度**：假 key 护身符自查。冒烟会真发请求，所以**冒烟的绿/红由我来跑**，你只需保证
   「不依赖网络也能验证」的断言（skip 分支、回滚断言用 mock）在自测里。
2. 交回前**自己先跑一遍 `--cleanup-only`**，确认 `documents=65 chunks=487`，把读数写进回执。
3. 七个自测全绿 + `_sum_selftest_counts.py` 现算合计与文档一致；命令与退出码写进回执，不接管道（坑 55）。
4. 反向闭环自己先走：把回滚删掉 → 断言必须红；把 skip 条件写死成 True → 断言必须红。留原文。
5. 端口按属主杀净并复查（坑 61）。

## 我这边并行做什么

- v2.5 两档读数已经落进 `docs/EVAL_BASELINE.md` §20.7（含**通道口径变更**登记：
  OpenRouter `qwen/qwen-plus` ≠ 生产 DashScope `qwen-flash`，联网两条在本通道**结构性不可用**）。
- 你交回后我跑：`--cleanup-only` 核语料 → 冒烟（skip 分支应 `[13][skip]` 且整轮 exit 0）→
  七个自测 → **合并 `task/P4f-persona` → `master`** → 删分支 → 文档同步 → 下发 **P5**。
- ⚠ 免费 key 的限流窗口可能还没恢复（第 3 次冒烟就是 429 炸的）。若我复跑冒烟仍撞 429，
  我会等窗口恢复或改用**不依赖网络的断言**判定，并在合并记录里写清冒烟是"何时、什么通道、几次跑绿的"。
