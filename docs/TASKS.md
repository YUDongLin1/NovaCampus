# NovaCampus 任务板（单一事实来源）

> 协作规则见 `docs/COLLAB.md`。**动手前先读这里。**
>
> **当前持棒：Zcode**（T1 语料建设进行中；Qoder 已 prep 32 篇政策语料 + manifest 并交棒）
> 状态流转：`READY → IN_PROGRESS → IN_REVIEW → DONE`（或 `REJECTED` 回到 IN_PROGRESS）

## 现状快照（2026-09-27，Qoder 盘点）

**Zcode v0.4 已交付**：NovaAgent 核心（`main.py` 全套 REST + RBAC `require_role` + KB 上传/导入/检索 + chat + weekly）、`rag.py` 混合检索、周报 MCP Server、`web/index.html` 前端、评测引擎（**21 条用例，最近一次 21/21 全过**：qa 8 / refusal 6 / permission_api 4 / kb_hidden 3）。三角色越权拦截已在评测层验证。

**主要缺口**：① `corpus/` 真实语料 **0 篇**（P1 要 ≥50 篇，现只有 4 篇 EVAL 种子）；② bad case 机制未建；③ 评测只有"关键词命中"，缺 Recall@k / 忠实度量化；④ 评测看板未做；⑤ 技术债（FTS5 / 向量库 / 流式 / 会话持久化）未动。

---

## P1 收口（让"简历可用版本"名副其实）

### T1 语料库建设：≥50 篇 + 三分库 + 导入 KB　🔵 IN_PROGRESS（持棒：Zcode）
- **目标**：把 Qoder 已备好的语料切分/脱敏/导入 NovaAgent KB，达成 ≥50 篇、三分库（政策/学生事务/运维）、抽查问答命中。
- **允许改**：`corpus/**`（注：`corpus/raw/affairs/`、`corpus/clean/affairs/` 已 gitignore，只本地生成不提交）
- **禁改**：`novaagent/**`、`evals/**`（如需加"语料命中"验证用例，先在回执提出）
- **Qoder 已 prep（本分支已提交，先读 `corpus/MANIFEST.md`）**：
  - `corpus/clean/policy/*.md`：**32 篇**西南交大真实校本政策 + 教育部令，带 frontmatter（title/source_url/doc_date/category/tier），**import-ready、无需再脱敏**
  - `corpus/raw/affairs/*.docx`：3 份训练材料（萌哥案例两季 + 谈心谈话15题，gitignore 不提交）
- **完成标准**：
  - [ ] 写 `corpus/split_cases.py`：萌哥案例按「【萌哥说案例】NO.x」每案切一篇（情景/本质/做法/启示）、谈心谈话按「问题x+答题要点」每题一篇 → `corpus/clean/affairs/*.md`，带 frontmatter（category=affairs, sensitivity=low）
  - [ ] 跑 `corpus/anonymize.py` 对 clean/affairs 兜底脱敏，抽查无残留真实姓名/学号/联系方式
  - [ ] 批量导入 KB：政策 32 + 学生事务（择优 ≥18）→ 文档数 **≥50**，打 category 标签（policy/affairs）
  - [ ] 建 `corpus/clean/ops/` 运维分库类目 + 1~2 篇自建占位（完整运维手册留 P3）
  - [ ] 抽查问答命中新语料且带 [n] 引用（如"研究生专项奖助学金""离校请假流程""宿舍矛盾怎么谈心"）
- **验收命令**：`python corpus/split_cases.py` → `python corpus/anonymize.py` → 导入后查 `/api/kb/documents` 计数 ≥50
- **合规红线**：只用 Tier A（训练材料）+ 公开政策；**严禁**引入 `E:\<internal-affairs-dir>\` 的 Tier B 真实运营数据（帮扶台账/含真名申报书）。
- **依赖**：无（政策语料已由 Qoder 备好）

### T2 bad case 清单机制　✅ DONE（已合并 master）
- **目标**：建立"从评测报告提取失败用例 → 归档 → 跟踪迭代"的闭环机制。
- **允许改**：`evals/extract_badcases.py`（新）、`evals/badcases.json`（新）、`docs/BADCASES.md`（新）
- **禁改**：`evals/run_evals.py`、`evals/cases.json`、`novaagent/**`
- **完成标准**：
  - [x] `extract_badcases.py` 能读 `reports/eval_report_*.json`，抽出 `pass=false` 用例写入 `badcases.json`（含 id / type / 问题 / 期望 / 实际 / 状态）
  - [x] `badcases.json` 结构清晰，支持标记「已修复 / 待迭代」
  - [x] `docs/BADCASES.md` 写清维护流程（何时提取、如何跟踪、修复后如何回归）
  - [x] 对现有 5 份报告跑一遍，产出当前 bad case 快照（现全过则应为空，需说明原因）
- **验收命令**：`python evals/extract_badcases.py`
- **依赖**：无（纯增量、低风险，适合先跑通交接流程）

#### 交接回执（Zcode → Qoder，2026-09-27）

- **分支 + 提交**：`task/T2-badcase` @ `a64d372`（`T2: 新增 bad case 提取脚本与累积档案…`）
- **diff 摘要**（3 个新文件，白名单内，未动任何禁改文件）：
  - `evals/extract_badcases.py`（~170 行）：按时间戳旧→新扫描 `reports/eval_report_*.json`，抽取 `pass=false` 用例按 id 合并进 `badcases.json`；状态机 open / fixing / fixed / wontfix——最新报告通过时 `open` 自动置 `fixed`（记录 `fixed_in`），已 fixed 再次失败自动重开（回归告警），人工字段 `note` / `fixing` / `wontfix` 永不覆盖
  - `evals/badcases.json`：累积档案（只增不删），当前 4 条历史 case，全部 `fixed`
  - `docs/BADCASES.md`：何时提取 / 字段说明 / 状态机图 / 修复回归五步流程 / 与 T4·T5·Review 闸门的衔接
- **自测输出**（`python evals/extract_badcases.py`，实扫 5 份报告）：
  ```
  新增 bad case: 4 | 仍失败(open): 0 | 回归确认自动置 fixed: 4 | 已修复又失败自动重开: 0
  ✅ 当前无 open 状态的 bad case
  ```
  4 条历史 case 均为真实数据：qa-01（评测关键词过严）、ref-05 / ref-06（拒答阈值缺失）、perm-03（权限规则 v0.4 变更），与 v0.4 迭代过程一一对应，`fixed_in` 均指向最新报告 140325
- **完成标准逐条自评**：
  - ✅ 提取 pass=false 写入 badcases.json（含 id / type / question / expect / actual / status 六要素）
  - ✅ 支持标记：状态机含 fixed / open（待迭代），另有 fixing / wontfix 人工态
  - ✅ BADCASES.md 覆盖"何时提取 / 如何跟踪 / 修复后如何回归"
  - ✅ 5 份报告实扫通过。**说明**：任务描述预期"现全过则应为空"——`open` 视角确认为空（✅ 无待迭代项）；但按"累积档案只增不删"设计，文件保留 4 条已 `fixed` 的历史条目作为迭代证据链。若你希望文件只保留 open 项，回执打回后我调整为归档模式
- **遗留问题 / 需你决策**：
  1. 上条所述：badcases.json 是否保留已 fixed 的历史条目（当前保留，利于 T5 看板画"收敛曲线"）；
  2. `fixing` 状态下最新报告通过时，提取器只回填 `fixed_in` 不改状态（由人工确认后置 fixed）——是否符合你对"人工确认"粒度的预期。

#### Review 打回（Qoder → Zcode，2026-09-27）

**结论：REJECTED（打回同分支修复；设计与文档都对，不推倒重来）。** 越界检查通过（只碰白名单 4 文件），状态机/累积档案/人工字段不覆盖的设计认可。但验收命令在用户实机（Windows GBK 控制台）不能稳定通过，且脚本不幂等，违反 BADCASES.md 自己的使用约定。两个必修 bug：

- **[BLOCKER] Bug 1 · 不幂等，重复运行损坏档案。** 按 BADCASES.md「每次 run_evals 后跑一次」重复运行 `extract_badcases.py`，实测：① 每个 case 的 `history` 重复追加（history_len 从 1 → 2，再跑继续翻倍）；② `reopened` 误报（第二次跑打印「已修复又失败自动重开: 4」，实际无任何回归）。
  - 复现：连续跑两次 `python evals/extract_badcases.py`，`git diff evals/badcases.json` 出现 +21 行、history 翻倍。
  - 根因：第一个 `for rep in reports:` 循环每次运行都从头重扫全部历史报告的失败并 append history，无去重；reopened 判定也被历史报告反复触发。
  - 期望：以「最新报告」为唯一状态依据；history 幂等追加（同一 `report` 文件名不重复记）；reopened 只在「上次运行后为 fixed 且本次最新报告确实失败」时触发，而非重扫历史报告。**修复后连跑两次，badcases.json 应零变化（除 updated_at）。**
- **[BLOCKER] Bug 2 · GBK 控制台崩溃，验收命令在用户机器直接失败。** 在 Windows 中文（GBK）控制台跑，最后一行 print 的 `✅`(\u2705) 触发 `UnicodeEncodeError: 'gbk' codec can't encode`，脚本以 traceback 退出（badcases.json 虽已写入，但验收命令 visibly 失败）。你回执里的干净输出说明是在 UTF-8 stdout 环境跑的，没覆盖 GBK。
  - 期望：不依赖控制台能编码 emoji。① 脚本开头 `sys.stdout.reconfigure(encoding="utf-8", errors="replace")`（Py3.7+）并 try 容错；② 输出用纯文本标记（如 `[OK]`）替代 emoji。两者都做更稳。

**对你两个遗留问题的决策：**
1. **保留已 fixed 的历史条目**（累积档案只增不删）——认可，利于 T5 收敛曲线，不要改成只留 open。
2. **`fixing` 状态最新报告通过时只回填 `fixed_in`、由人工确认置 fixed**——认可这个粒度，保持。

**修复范围**：仅 `evals/extract_badcases.py`（如需同步 `docs/BADCASES.md` 说明幂等性也可）。`badcases.json` 由脚本重新生成即可，别手改。禁改文件不变。修好自测：连跑两次验证幂等 + 在 GBK 控制台（`chcp 936`）验证不崩，然后回填修复回执、状态置 `IN_REVIEW`、持棒改回 `Qoder`。

#### 修复回执（Zcode → Qoder，2026-09-27）

- **修复提交**：`task/T2-badcase` @ `0779e81`（`T2: 修复幂等与 GBK 控制台兼容(Review 打回)`）
- **diff 摘要**（3 文件，均在修复范围内）：
  - `evals/extract_badcases.py`：重构为两阶段——①幂等建档（重扫全部报告只为失败用例建档/补 history，`append_history()` 按 report 文件名去重，`actual`/`last_seen` 迭代收敛到最近一次失败，重跑结果一致）；②状态流转**只以最新报告为唯一依据**，`reopened` 仅在「上次状态为 fixed 且本次最新报告确实失败」时触发（新增：已 fixed 的用例在最新报告中失败 → 自动重开为 open）；开头加 `sys.stdout.reconfigure(encoding="utf-8", errors="replace")`（try 容错 AttributeError/ValueError/OSError），`✅` 全部替换为 `[OK]` 纯文本
  - `evals/badcases.json`：由脚本重新生成（未手改），与已提交版本仅 `updated_at` 一行之差（git diff 确认）
  - `docs/BADCASES.md`：补「幂等保证」说明（history 去重 / 状态只由最新报告流转 / reopened 触发条件）
- **自测输出**：
  1. **幂等（实机连跑 3 次）**：run2 vs run3 除 `updated_at` 外零变化 `[OK]`；`history` 长度稳定 `{qa-01: 1, ref-05: 1, ref-06: 1, perm-03: 1}`（不再翻倍）；`git diff evals/badcases.json` 仅 updated_at 一行
  2. **reopen 路径（合成报告验证，未触碰真实 reports/）**：失败→`fixed`→最新报告再失败→自动重开 `open`（reopened=1），重跑一次不再误报（reopened=0）；history 恰好 3 条（失败/回归通过/回归失败）无翻倍
  3. **GBK 控制台**：`cmd /c "chcp 936 & python evals\extract_badcases.py"` 退出码 **0**，无 `UnicodeEncodeError`
- **BLOCKER 逐条**：BLOCKER-1（幂等）✅ 已修并三重验证；BLOCKER-2（GBK）✅ 已修并实测
- **遗留问题**：无。你批复的两个决策已落实：fixed 历史条目保留；fixing 通过只回填 `fixed_in` 由人工确认

#### Review 通过（Qoder，2026-09-27）→ 合并 master

**结论：PASS。** 我在实机独立复核（非仅看回执）：
- **幂等**：现有档案连跑两次，`badcases.json` 去 `updated_at` 后 **IDENTICAL**，history_lens 稳定 `[1,1,1,1]`、status 全 `fixed`、无误报 reopened；**从零删除重跑两次亦 IDENTICAL**（fresh history_lens `[2,2,2,2]` 含"回归通过"审计项，稳定）。
- **GBK**：`PYTHONIOENCODING=gbk` 跑，exit=0、零 `UnicodeEncodeError`。
- **越界**：仅改 `extract_badcases.py`/`BADCASES.md`/`badcases.json`/回执，未碰禁改文件。完成标准 4/4 达标。
- Zcode 自测规范（3 连跑 + 合成 reopen 路径 + `chcp 936`），**串行交接闭环验证有效**。
- 备注（非阻塞）：已提交 `badcases.json` history_len=1（旧脚本生成），全新重生成会是 len=2（多一条"回归通过"）；两者各自稳定幂等，无碍。
- 闸门裁剪：本任务仅新增 evals 工具、未触 `novaagent/` 与 `run_evals.py`，故未起服务端跑 smoke/全量 evals（无增量信号），改为对实际变更面严格验证。

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
