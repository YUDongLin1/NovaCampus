# P4a-1 开单指令（粘进 Zcode 新会话）

> 由 Qoder 于 2026-09-29 生成。规格正文以 `docs/TASKS.md` 的 P4a-1 条目（C1~C5）为唯一事实源，本文件只是开场指令副本。
> **这是一个小单**，做完就交回，不要扩范围。

=== PROMPT 开始 ===

你是 **Zcode**，NovaCampus 项目（`E:\AILearn\NovaCampus`）的实现者。**P4a 已由 Qoder Review 通过并合并 master（`827e1ae`）**，现在下发 **P4a-1：导入质量门补口——识别并拦截导航/索引型页面**。**当前持棒=Zcode**。

按序做：

1. 读 `docs/TASKS.md` 头部「当前持棒」确认是你，然后读 **P4a-1 条目**（背景 / 目标 / 白名单 / 黑名单 / C1~C5 / 验收命令 / 依赖）。
2. 读 `docs/P4A.md`（你上一单写的）与 `docs/TASKS.md` 里 P4a 的「Review 结论」——里面有我批准的两处裁决和这次的缺口说明；`docs/EVAL_BASELINE.md` 第十一节是 v1.7 口径。
3. 切分支：`git checkout -b task/P4a-1-index-gate`（从 master 切）。

**要解决的问题（一句话）**：C4 的长度门「正文 ≥200 字」拦不住导航/索引页，因为**整站菜单本身就有 1600+ 字**。Review 实测 `https://infpub.swjtu.edu.cn/gksx/cw_zcjsfxx/sfxm_sfyj_sfbzjtsfs.htm` 导入成功，KB 一度 65→66（我已清回 65）。这条缺口是我的规格没写成可执行判据，不是你的实现问题。

**做法（C1）**：在 `main.py` 的质量门里加一条**结构性判据** `index_page`——建议：提取正文后「菜单式短行占比 ≥50%（短行 = ≤12 字且不含 `、，。：；！？` 与数字）」**且**「正文式长行 <15%（长行 = >25 字且含句读）」→ 拒绝，返回 `{code:"index_page", reason, hint:"请粘贴具体文章页 URL（含发布日期/正文的页面），导航页无法入库"}`。**判据可按你实测调整，但必须在回执说明理由**，并优先保证 C2 零误伤。

**边界（黑名单）**：`evals/**`（评测集与 judge 口径本单一律不动）、`corpus/**`、`sims/**`、`mcp/**`、`weknora/**`、`novaagent/web/**`、`novaagent/novaagent/{agent.py,rag.py,refusal.py,db.py,config.py}`。**只准动** `main.py` 的质量门相关函数、`novaagent/tests/smoke_test.py`（新增 U7）、`docs/P4A.md`、`docs/P4A1.md`。

**三条硬要求**：
- **C2 零误伤**：现有 6 篇已入库语料（`doc_id 110~115`）与 `corpus/clean/**` 全部政策文件重跑门控必须**全部放行**。误伤比漏检更糟——如需用收窄判据来消除误伤，请收窄并在回执写明取舍。
- **C3 用真实样本做单测**：`docs/p4/evidence/sample_index_page.txt` 是我实抓落盘的导航页样本（81 行 / 菜单式短行 62% / 正文式长行 9 条 / 1623 字），U7 断言它被拒；同一单测里放一篇正文页断言放行。另把 `smoke_test.py` 的 [16a] 脏 URL 回归项扩充为含该索引页。
- **C4/C5 不回退**：冒烟前后 `documents` 仍须 **65→65**；`kb_doctor` `danger=0`；评测 v1.7（36 用例）**不回退**——R@k ≥0.9412、拒答 1.0、`refusal_indomain` 6/6。**注意**：`qa-08`（未命中关键词「一周」）是 T10 时代即存在的轮换波动用例，历史统计 **8 轮中 7 轮全过**，单轮 35/36 不算回归，但请如实记录你跑的轮次与失败项。

**取证先于清理（我这次自己踩的坑，你别踩）**：做导入回归测试会往 KB 写文档。测之前先把要引用的数字/特征落盘，再删测试文档；`documents` 计数最终必须回到 65。

**不要做的事**：**不要顺手动 `RERANK_MIN_SCORE`、不要实现查询改写或分级阈值**（那是 P4d 的活，我已把两处待裁决移交 P4d）；不要动 SYSTEM_PROMPT 文案；不要合并 master；不要开 P4b-0；不要动 WorkBuddy 工作树；不要把 `E:\<internal-affairs-dir>\` 真实数据或 `corpus/*/affairs/` 带进代码/文档/网络。

**交付**：commit 前缀 `P4a-1:`；完成后回填「交接回执」（分支/提交/diff 摘要/自测输出/C1~C5 逐条自评/误伤清单/遗留），把 P4a-1 置 `IN_REVIEW`、`当前持棒=Qoder`。

=== PROMPT 结束 ===
