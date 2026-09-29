# P4b-0 开单指令（粘进 Zcode 新会话）

> 由 Qoder 于 2026-09-29 生成。规格正文以 `docs/TASKS.md` 的 P4b-0 条目（C1~C6）为唯一事实源。
> **本单是纯重构**：行为与视觉零变化是硬门，任何"顺手改进"都算缺陷。

=== PROMPT 开始 ===

你是 **Zcode**，NovaCampus 项目（`E:\AILearn\NovaCampus`）的实现者。**当前持棒=Zcode**，现在下发 **P4b-0：前端模块化拆分**。前三单已由 Qoder Review 通过并合并：P3b `2234fc8`、P4a `827e1ae`、P4a-1 `5399a5e`。

按序做：

1. 读 `docs/TASKS.md` 头部「当前持棒」确认是你，读 **P4b-0 条目**（背景与决策 / 目标 / 建议结构 / 白名单 / 黑名单 / C1~C6 / 验收命令 / 依赖）。
2. 读 `docs/P4.md` §M4 与 §四（为什么要先拆——P4b/P4c/P4e/P4f 每一单都要改这个文件）、`HANDOFF.md` §六 踩坑清单（重点坑 4 heredoc、坑 5 GBK、坑 8 NO_PROXY、坑 17 落盘≠入库、坑 18 claim→字段、坑 23 smoke 污染 KB、坑 29 取证先于清理）。
3. 切分支：`git checkout -b task/P4b-0-frontend-split`（从 master 切）。

**第 0 步（先取基线，再动代码——坑 29 是我自己刚踩的，你别踩）**：起服务 `cd novaagent && NO_PROXY="127.0.0.1,localhost" .venv/Scripts/python.exe -m uvicorn novaagent.main:app --port 8900`，在**改动之前**把五条路径的现状留痕到 `docs/p4b0/evidence/before/`：
- 登录（成功/失败提示）
- 问答：SSE 流式增量、来源 `[n]` 渲染、工具轨迹显示
- 知识库：文件上传、网页导入（**含导入被质量门拒绝时的 `{code,reason,hint}` 提示文案**）、分块查看、分类筛选
- 周报：记录碎片、AI 扩充、生成周报、归档列表与详情
- 模型与自定义 API 设置（含"测试连通性"反馈）

每条至少一张截图或一段 DOM 断言输出，**外加**一份 `before/api_calls.txt`：`grep` 出 `index.html` 里所有 `fetch('/api/...')` 调用点清单（后续要证明一个都没少）。没有 before 基线，C1 就无法验收。

**本单性质**：纯重构。`novaagent/web/index.html` 现为 **887 行单文件**（HTML+CSS+JS 混写），P4b（会话栏）、P4c（文件夹树）、P4e（联网开关与来源分区）、P4f（辅导员入口）、P4g（文本框）**每一单都要改它**，不拆就会连续在同一文件上冲突、Review 也难定位。**所以本单的唯一目标就是"拆"，不是"改"。**

**建议结构**（可调整，但须在回执说明理由）：`web/index.html`（骨架）+ `web/css/theme.css`（水墨主题变量与样式，T3 建立的「学术水墨 × 朱砂印」设计语言必须原样保留）+ `web/js/{api.js, chat.js, kb.js, weekly.js, ui.js}`。**保持零构建**：不引 React/Vue/Vite/webpack/TS，不引任何**公网 CDN**（断网也要能用），FastAPI 现有 `WEB_DIR` + `FileResponse` 已托管页面，最多再加静态资源挂载。

**边界（越界即打回）**：
- **只准动**：`novaagent/web/**`、`novaagent/novaagent/main.py`（**仅限静态资源路由这一处**）、`docs/P4B0.md`（新）、`docs/p4b0/evidence/**`
- **禁改**：`novaagent/novaagent/{agent.py,rag.py,refusal.py,db.py,config.py,llm.py,main.py 其他部分}`、`evals/**`、`corpus/**`、`sims/**`、`mcp/**`、`weknora/**`、`novaagent/tests/**`
- ⚠ `main.py` 是本单最容易越界的文件：质量门、拒答门控、RBAC、周报路由**一行都不许碰**。改完请用 `git diff master...HEAD -- novaagent/novaagent/main.py` 自查，diff 里只应出现静态资源挂载那几行。

**完成标准要点（详见 TASKS.md）**：
- **C1 行为零变化**：五条路径 before/after 逐条一致（截图或 DOM 断言成对）
- **C2 三角色走查**：student / counselor / admin 可见范围不变；**前端不得新增任何权限判断**——RBAC 一律以后端为准，前端少显示≠权限，不要在本单"顺手"加隐藏逻辑
- **C3 零新依赖**：无框架/构建/公网 CDN
- **C4 可核对**：拆分后 `find novaagent/web -type f | xargs wc -l` 清单落盘；`index.html` 只剩骨架；`api_calls.txt` before/after 调用点集合**完全一致**
- **C5 零回归**：评测 v1.7（36 用例）不回退——R@k ≥0.9412、拒答 1.0、`refusal_indomain` 6/6。⚠ 忠实度中位 0.9706（逐轮有 1.0/0.9412/0.9118 摆动）属**已裁决移交 P4d 的 judge 学段声明盲区口径**，**不要当成回归去"优化"**，也不要为了让它变 1.0 而删掉学段声明
- **C6 冒烟守恒**：`novaagent/tests/smoke_test.py` 全过、跑完 `documents` 仍 **65→65**（P4a 已修自清理，别把它改回去）

**交付**：每完成一个可验证单元就 commit（前缀 `P4b-0:`）；回填「交接回执」（分支/提交/diff 摘要/**文件行数与字节数对照表**/五条路径 before-after 结论/自测输出/C1~C6 逐条自评/**结构偏离规格的理由**/遗留），置 `IN_REVIEW`、`当前持棒=Qoder`。

**不要做的事**：不要加任何新功能或新 UI 元素（会话栏、文件夹树、联网开关都属后续单）；不要顺手改样式观感；不要动 `RERANK_MIN_SCORE` 或 SYSTEM_PROMPT；不要合并 master；不要开 P4b；不要动 WorkBuddy 工作树；不要把 `E:\<internal-affairs-dir>\` 真实数据或 `corpus/*/affairs/` 内容带进代码/文档/网络。环境输出与已知事实矛盾 → **硬停上报**，不要绕过去。

=== PROMPT 结束 ===
