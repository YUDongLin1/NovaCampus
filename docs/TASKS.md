# NovaCampus 任务板（单一事实来源）

> 协作规则见 `docs/COLLAB.md`。**动手前先读这里。**
>
> **当前持棒：Zcode**（T2 进行中；Zcode 回填交接回执后改回 `Qoder`）
> 状态流转：`READY → IN_PROGRESS → IN_REVIEW → DONE`（或 `REJECTED` 回到 IN_PROGRESS）

## 现状快照（2026-09-27，Qoder 盘点）

**Zcode v0.4 已交付**：NovaAgent 核心（`main.py` 全套 REST + RBAC `require_role` + KB 上传/导入/检索 + chat + weekly）、`rag.py` 混合检索、周报 MCP Server、`web/index.html` 前端、评测引擎（**21 条用例，最近一次 21/21 全过**：qa 8 / refusal 6 / permission_api 4 / kb_hidden 3）。三角色越权拦截已在评测层验证。

**主要缺口**：① `corpus/` 真实语料 **0 篇**（P1 要 ≥50 篇，现只有 4 篇 EVAL 种子）；② bad case 机制未建；③ 评测只有"关键词命中"，缺 Recall@k / 忠实度量化；④ 评测看板未做；⑤ 技术债（FTS5 / 向量库 / 流式 / 会话持久化）未动。

---

## P1 收口（让"简历可用版本"名副其实）

### T1 语料库建设：≥50 篇真实政策文档 + 脱敏 + 分库　⏳ READY（待用户定来源）
- **目标**：`corpus/` 从 0 → ≥50 篇真实高校政策文档，分 3 库（政策 / 学生事务 / 运维手册），全部脱敏，记录来源。
- **允许改**：`corpus/**`
- **禁改**：`novaagent/**`、`evals/**`
- **完成标准**：
  - [ ] `corpus/raw/` ≥50 篇原始文档
  - [ ] `corpus/clean/` 对应脱敏版
  - [ ] 每篇有来源元数据（URL + 抓取时间 + 分类）
  - [ ] `anonymize.py` 跑通无报错
  - [ ] 导入 KB 后文档数 ≥50，抽查问答能命中新语料
- **验收命令**：`python corpus/anonymize.py` → 导入后查 `/api/kb/documents` 计数
- ⚠️ **需用户决策**：语料来源（真实高校公开政策 URL 清单 / 用户自有工作记录 / 混合）
- **依赖**：无

### T2 bad case 清单机制　🔵 IN_PROGRESS（持棒：Zcode）
- **目标**：建立"从评测报告提取失败用例 → 归档 → 跟踪迭代"的闭环机制。
- **允许改**：`evals/extract_badcases.py`（新）、`evals/badcases.json`（新）、`docs/BADCASES.md`（新）
- **禁改**：`evals/run_evals.py`、`evals/cases.json`、`novaagent/**`
- **完成标准**：
  - [ ] `extract_badcases.py` 能读 `reports/eval_report_*.json`，抽出 `pass=false` 用例写入 `badcases.json`（含 id / type / 问题 / 期望 / 实际 / 状态）
  - [ ] `badcases.json` 结构清晰，支持标记「已修复 / 待迭代」
  - [ ] `docs/BADCASES.md` 写清维护流程（何时提取、如何跟踪、修复后如何回归）
  - [ ] 对现有 5 份报告跑一遍，产出当前 bad case 快照（现全过则应为空，需说明原因）
- **验收命令**：`python evals/extract_badcases.py`
- **依赖**：无（纯增量、低风险，适合先跑通交接流程）

### T3 前端校园化核对与补齐
- **目标**：确认 / 补齐主题、Logo、模拟统一认证登录页，三角色视角 UI 正确。
- **允许改**：`novaagent/web/**`
- **禁改**：`novaagent/novaagent/**`（如需改 API，先在回执提出）
- **完成标准**：
  - [ ] 登录页为"模拟统一身份认证"样式
  - [ ] 校园化主题 / Logo 到位
  - [ ] 三角色登录后 UI 按权限正确显示 / 隐藏功能
  - [ ] 附截图或录屏
- **依赖**：无

---

## P2 评测深化（简历第一亮点）

### T4 评测指标深化：Recall@k + 忠实度
- **目标**：`run_evals.py` 在现有关键词命中基础上，增加 Recall@k 和忠实度量化。
- **允许改**：`evals/run_evals.py`、`evals/cases.json`（加标注字段）
- **完成标准**：
  - [ ] 每条 qa 用例标注应命中的文档 / chunk，计算 Recall@k
  - [ ] 忠实度：答案是否有据（规则或 LLM-as-judge），给 0~1 分
  - [ ] 报告 summary 增加 `recall_at_k` / `faithfulness` 聚合指标
  - [ ] 目标基线记录进 docs（忠实度 ≥0.85、拒答准确率 ≥90%）
- **依赖**：建议在 T1 之后（语料越丰富，Recall@k 越有意义）

### T5 评测看板
- **目标**：聚合 `reports/` 多次评测结果，产出可视化看板（优化前后对比）。
- **允许改**：`evals/dashboard*`（新）、`reports/`
- **完成标准**：
  - [ ] 读取多份 `eval_report_*.json` 展示指标趋势
  - [ ] 单页 HTML 可直接打开
- **依赖**：T4

---

## 技术债（按简历价值排序，轮到下发时补全规格）

- **T6** 关键词检索 LIKE → FTS5/BM25（`novaagent/rag.py`、`db.py`）
- **T7** 向量库 sqlite → sqlite-vec（`novaagent/db.py`、`rag.py`）
- **T8** 流式输出 SSE（`novaagent/main.py`、`web/`）
- **T9** 会话持久化（`novaagent/db.py`、`main.py`）

---

## 已完成（Zcode v0.4，留档）

- NovaAgent 核心 + RBAC + 混合检索 + chat API
- 周报 MCP Server v1 + 周报生成（`data/weekly/reports/`）
- 评测引擎 + 21 条用例（含权限边界 / 拒答），最近 21/21 全过
- 单页前端 `web/index.html`
