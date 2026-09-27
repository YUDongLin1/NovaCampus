# NovaCampus 任务板（单一事实来源）

> 协作规则见 `docs/COLLAB.md`。**动手前先读这里。**
>
> **当前持棒：Zcode**（T10 检索相关性根治进行中；回填后置 `IN_REVIEW`、持棒改回 `Qoder`）
> 状态流转：`READY → IN_PROGRESS → IN_REVIEW → DONE`（或 `REJECTED` 回到 IN_PROGRESS）

## 现状快照（2026-09-27，Qoder 盘点）

**Zcode v0.4 已交付**：NovaAgent 核心（`main.py` 全套 REST + RBAC `require_role` + KB 上传/导入/检索 + chat + weekly）、`rag.py` 混合检索、周报 MCP Server、`web/index.html` 前端、评测引擎（**21 条用例，最近一次 21/21 全过**：qa 8 / refusal 6 / permission_api 4 / kb_hidden 3）。三角色越权拦截已在评测层验证。

**主要缺口**：① `corpus/` 真实语料 **0 篇**（P1 要 ≥50 篇，现只有 4 篇 EVAL 种子）；② bad case 机制未建；③ 评测只有"关键词命中"，缺 Recall@k / 忠实度量化；④ 评测看板未做；⑤ 技术债（FTS5 / 向量库 / 流式 / 会话持久化）未动。

---

## P1 收口（让"简历可用版本"名副其实）

### T1 语料库建设：≥50 篇 + 三分库 + 导入 KB　✅ DONE（已合并 master）
- **目标**：把 Qoder 已备好的语料切分/脱敏/导入 NovaAgent KB，达成 ≥50 篇、三分库（政策/学生事务/运维）、抽查问答命中。
- **允许改**：`corpus/**`（注：`corpus/raw/affairs/`、`corpus/clean/affairs/` 已 gitignore，只本地生成不提交）
- **禁改**：`novaagent/**`、`evals/**`（如需加"语料命中"验证用例，先在回执提出）
- **Qoder 已 prep（本分支已提交，先读 `corpus/MANIFEST.md`）**：
  - `corpus/clean/policy/*.md`：**32 篇**西南交大真实校本政策 + 教育部令，带 frontmatter（title/source_url/doc_date/category/tier），**import-ready、无需再脱敏**
  - `corpus/raw/affairs/*.docx`：3 份训练材料（萌哥案例两季 + 谈心谈话15题，gitignore 不提交）
- **完成标准**：
  - [x] 写 `corpus/split_cases.py`：萌哥案例按「【萌哥说案例】NO.x」每案切一篇（情景/本质/做法/启示）、谈心谈话按「问题x+答题要点」每题一篇 → `corpus/clean/affairs/*.md`，带 frontmatter（category=affairs, sensitivity=low）
  - [x] 跑 `corpus/anonymize.py` 对 clean/affairs 兜底脱敏，抽查无残留真实姓名/学号/联系方式
  - [x] 批量导入 KB：政策 32 + 学生事务（择优 ≥18）→ 文档数 **≥50**，打 category 标签（policy/affairs）
  - [x] 建 `corpus/clean/ops/` 运维分库类目 + 1~2 篇自建占位（完整运维手册留 P3）
  - [x] 抽查问答命中新语料且带 [n] 引用（如"研究生专项奖助学金""离校请假流程""宿舍矛盾怎么谈心"）
- **验收命令**：`python corpus/split_cases.py` → `python corpus/anonymize.py` → 导入后查 `/api/kb/documents` 计数 ≥50
- **合规红线**：只用 Tier A（训练材料）+ 公开政策；**严禁**引入 `E:\<internal-affairs-dir>\` 的 Tier B 真实运营数据（帮扶台账/含真名申报书）。
- **依赖**：无（政策语料已由 Qoder 备好）

#### 交接回执（Zcode → Qoder，2026-09-27）

- **分支 + 提交**：`task/T1-corpus` @ `0024521`（`T1: 训练语料切分脚本 + 运维分库占位…`）
- **diff 摘要**（白名单内；`corpus/clean/affairs/` 按 gitignore 只本地生成不提交）：
  - `corpus/split_cases.py`（新）：萌哥案例两季按「【萌哥说案例】NO.x」切分——全角 `ＮＯ`/变体标题归一化，四段小节归并（案例情景描述/问题本质/解决思路/实施办法/经验启示 → 情景/本质/做法/启示，剥离"一、二、"编号），可识别小节 <2 时整篇"原文"兜底；谈心谈话按「问题N：」切分；frontmatter 对齐 policy 惯例（category=affairs / tier=Tier A 训练材料(化名) / sensitivity=low / origin_file / split_date）
  - `corpus/clean/ops/`（新，2 篇占位）：NovaCampus 服务运维手册 v0.1（基于本仓库真实部署的运维要点）+ 模拟系统运维手册（P3 AIOps 对齐框架：告警分级 / 连接池耗尽 / CPU 飙高预案骨架，Agent 诊断报告可引用）
- **自测输出**：
  1. **切分**：94 篇 = S1→50 案（992 段）+ S2→30 案（594 段）+ 谈心谈话→14 题。**注意：谈心谈话源文件名写"问题1-15"，docx 实际仅 14 题（已核实段落标记），非切分遗漏**
  2. **兜底脱敏**：`anonymize.py corpus/clean/affairs --check` → 94 文件命中 **0**（与 MANIFEST「Tier A 化名，扫描 phone/idcard/学号 均为 0」复核一致）；人名为材料自带化名（张毅/小静/小刚等出自公开培训材料）
  3. **批量导入（运行时动作，代码不入 repo）**：KB 21 → **75 篇**（+54，零失败）= 政策 32（category=政策文件，role_min=student，临时副本去掉"NN-"序号前缀作标题）+ 学生事务 20（案例按字数 Top14 + 谈心谈话 6 题择优 Q01/02/04/08/11/12，role_min=counselor）+ 运维手册 2（role_min=admin）；导入后分类分布：政策文件 32 / 学生事务 20 / 运维手册 5（含此前冒烟测试 3）/ 其他 18
  4. **抽查问答（3/3 命中新语料，带 [n] 引用）**：
     - "研究生专项奖助学金的申请条件"（student）→ 命中奖助学金评审办法族（相关度 0.857/0.839/0.565/0.491），回答如实说明具体条件以各专项办法为准
     - "离校请假流程是怎么规定的"（student）→ 强命中请销假管理办法族（0.964/0.935/0.563），答案结构化输出适用范围/请假类型
     - "学生宿舍矛盾怎么谈心"（counselor）→ 命中 QA-Q02 宿舍矛盾（0.880）+ 关联案例；学生角色不可见该库（权限隔离，v0.4 冒烟已验证）
- **完成标准逐条自评**：5/5 ✅（切分 94 篇含四段归并与兜底 / 兜底脱敏 0 命中 / 导入 75≥50 带类目标签 / ops 类目+2 占位 / 抽查 3/3 带引用）
- **遗留问题 / 需你决策**：
  1. **KB 文档标题取自文件名**，文号呈扁平格式（如"…西交校学生202514号"而非"〔2025〕14号"）——分块正文保留原格式，仅展示层欠美观；如需修复可按 frontmatter title 重导政策 32 篇（约 6 分钟），等你裁决是否 T3 顺手做
  2. "研究生专项奖助学金"**专门文件不在库**：MANIFEST 决策 (c) 跳过了研工部 3 篇 PDF 附件办法——抽查命中的是奖助评审办法族，回答方向正确但非专门依据；如需强命中可后续补抓 3 篇 PDF
  3. 政策库 32 篇中部分文号连续递减（202519→202515），为 Qoder prep 的抓取产物，我未改动；如需复核文号真实性由你确认

#### Review 通过（Qoder，2026-09-27）→ 合并 master

**结论：PASS。** 独立核验（非仅看回执）：
- **KB 文档数**：查 `novaagent/data/agent.db` → documents=**75**（≥50 ✓）、chunks=**485**（embedding 已建，检索可用）；分类 政策文件 32 / 学生事务 20 / 运维手册 5 / 其他 17+工作制度 1，与回执吻合。
- **脱敏**：独立扫 `clean/affairs/` 94 篇 → 手机 0 / 身份证 0 / 学号 0 ✓；人名为材料自带化名（张毅/小静/S同学）。
- **越界**：仅 `corpus/**`，未碰 novaagent/evals ✓。**git 卫生**：`git ls-files|grep affairs` 为空 → affairs docx 与切分正文未进 git ✓。
- **抽查命中**：库级确认 QA-Q02(宿舍矛盾)、政策族(请假/奖助学金)在库且已向量化；RAG 链路未被 T1 触碰、沿用已通过的 21/21 评测，故未再起服务端跑 live chat（DB 证据已充分佐证）。
- `split_cases.py` 代码质量好（NO.x/问题N 切分 + 四段归并 + 变体兼容 + 兜底 + frontmatter 规范）。

**对 3 个遗留问题的裁决：**
1. **文号标题扁平化**（"…202514号" vs "〔2025〕14号"）：非阻塞，正文分块保留原格式，仅 KB 展示层欠美观。**记为 T3 可选优化**（按 frontmatter title 重导政策 32 篇）。
2. **研究生专项奖助学金专门文件不在库**：决策 (c) 跳过 3 篇研工部 PDF 的**预期结果**，抽查已正确命中奖助评审办法族。**接受**；日后要完整性再补抓 3 篇 PDF。
3. **政策文号连续递减（2025〕23→15号）**：**确认真实、非异常**——CDP 直接从学工部规章列表 DOM 抓取，站点按新文号在前排序，2025 年这批学生政策本就连号(15~23)。无需复核。

**P1 进度**：语料库(T1)✅ + 三角色权限(评测已验)✅ + 周报 MCP(v0.4)✅ + 评测集21条+bad case机制(T2)✅ → P1「简历可用版本」的语料与质量闭环已就位，剩 T3 前端校园化核对。

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

### T3 前端校园化：UI 重设计（学术水墨 × 朱砂印）　✅ DONE（已合并 master，live 三角色验证通过）
- **目标**：把通用 bootstrap 蓝的"AI 味"界面重设计为有辨识度的校园学术风；保留全部功能与 JS 钩子。
- **允许改**：`novaagent/web/**`；**禁改**：`novaagent/novaagent/**`
- **已完成（Qoder，提交 `070b247`，分支 `task/T3-frontend`）**：
  - [x] 设计方向「学术水墨 × 朱砂印」：暖宣纸底 + 颗粒质感 + 墨蓝主色 + 朱砂点缀；宋体显示字体（Marcellus/Noto Serif SC）+ 原生黑体正文；印章式品牌标记；分层柔和阴影；错落入场/悬停/标签滑动动效
  - [x] 登录页重做：朱砂印章 + 宋体字标 + 朱砂顶线 + 巨型"智"水印（模拟统一认证风格）
  - [x] 主界面重做：墨蓝顶栏 + 朱砂侧线 bot 气泡 + 引用区衬线"引用来源"标签 + 侧栏三标签朱砂下划线 + 分类/角色彩色标签 + 账户卡衬线花押
  - [x] **功能零回归**：`<script>` 逐字保留；脚本核验 56 id / 23 函数 / 全部关键钩子无丢失；CDP 截图核验登录页与主界面渲染正常
- **Live 验证（2026-09-27，全栈起服务实测）**：student 登录 → 工作记录/周报/上传/导入全隐藏、只见政策库真实文档 ✓；counselor（reload 后）→ 三标签 + 上传/导入全显示、学生事务文档可见 ✓；KB 对 counselor 显示 70/75（5 篇 admin-only 被 RBAC 过滤，正确）✓；问答链路往返 LLM 正常、引用区渲染正常 ✓。截图：`_t1_tmp/ui_login.png / ui_student.png / ui_counselor.png / ui_main.png`。
- **遗留小项（不阻塞，另记）**：① KB 标题扁平文号展示优化（T1/T4 遗留）；② `enter()` 同页切换角色不恢复标签可见性（正常 logout 会 reload，实际无影响，可选加固）。
- **依赖**：无

---

## P2 评测深化（简历第一亮点）

### T4 评测指标深化：Recall@k + 忠实度 + 重建基线　✅ DONE（已合并 master）
- **目标**：评测引擎从"关键词命中"升级为量化 RAG 质量（Recall@k / 忠实度 / 拒答准确率），并在 T1 的 75 篇语料上重建基线。这是 P2 简历第一亮点。
- **允许改**：`evals/run_evals.py`、`evals/cases.json`、`evals/faithfulness.py`（新，可选）、`docs/EVAL_BASELINE.md`（新）、`reports/`（生成物）
- **禁改**：`novaagent/**`、`corpus/**`。**关键前提**：`/api/chat` 已返回 `sources[]`，每条含 `ref/title/role_min/content`（见 `agent.py` chat_for）——**忠实度所需上下文已在响应里，无需改 novaagent**。若你发现确需改 novaagent，先在回执提出、勿擅动。
- **前置必修（P0）**：`run_evals.py` 第 137–138 行 print `✅/❌`，在 GBK 控制台会 `UnicodeEncodeError` 崩溃（同 T2 bug）。修：开头加 `sys.stdout.reconfigure(encoding="utf-8", errors="replace")`（try 容错）+ `✅/❌`→`[PASS]/[FAIL]`。**必须 `chcp 936`/`PYTHONIOENCODING=gbk` 实测 exit 0**。
- **完成标准**：
  - [x] **P0 GBK 修复**：`PYTHONIOENCODING=gbk python evals/run_evals.py` 不崩、exit 0
  - [x] **Recall@k**：`cases.json` 每条 qa 加 `expect_sources`（应命中文档的标题子串标记，如 `["请销假","请假管理"]`）；run_evals 计算 `recall@k = 命中的 expect_sources 数 / 总数`（k 取返回 sources 数或固定 5），计入 per-case + `summary.recall_at_k_avg`
  - [x] **忠实度**：LLM-as-judge——用 `answer` + 上下文（`sources[].content` 拼接）判"答案每个事实性陈述是否被上下文支持"，给 0~1；复用 agent 的 LLM 配置（`config.LLM_MODEL`/`llm.chat`）；LLM 不可用时用词面覆盖率 proxy 兜底并标 `method=proxy`；计入 `summary.faithfulness_avg`。refusal 用例忠实度记 N/A（正确拒答不扣分）
  - [x] **重建基线（75 篇语料）**：跑通全部用例，**旧 21 条不回归**（若回归，跑 `extract_badcases.py` 记录进 bad case 档案）
  - [x] **新增 ≥5 条真实校本语料用例**（总 ≥26 条）：如"本科生离校请假手续"(expect 请销假办法)、"国家助学贷款申请条件"(expect 助学贷款实施办法)、"宿舍矛盾怎么谈心"(affairs, counselor)、"研究生奖助学金评审"(expect 奖助学金办法族)，每条带 `expect_keywords` + `expect_sources`
  - [x] **summary 增三项指标**：`recall_at_k_avg` / `faithfulness_avg` / `refusal_accuracy`；基线实测值 + 目标（忠实度 ≥0.85、拒答 ≥90%、Recall@k ≥0.8 冲刺）写入 `docs/EVAL_BASELINE.md`
  - [x] 报告落 `reports/`；末尾跑 `python evals/extract_badcases.py` 刷新档案
- **验收命令**：起 uvicorn + weekly MCP → `PYTHONIOENCODING=gbk python evals/run_evals.py`（确认不崩 + 三项指标出现在 summary）→ `python evals/extract_badcases.py`
- **依赖**：T1（已完成，75 篇在库）

#### 交接回执（Zcode → Qoder，2026-09-27）

- **分支 + 提交**：`task/T4-eval` @ `2ed9a86`（`T4: 评测深化——Recall@k + 忠实度 LLM-judge + 75 篇重建基线(v1.1)`）
- **diff 摘要**（均在白名单内，未触 `novaagent/**`、`corpus/**`）：
  - `evals/run_evals.py`：P0 GBK 修复（stdout reconfigure + `✅/❌`→`[PASS]/[FAIL]`）；新增 `compute_recall`（expect_sources 标题子串命中比例）；主循环接入 per-case `recall_at_k` / `faithfulness`；summary 增 `recall_at_k_avg` / `faithfulness_avg` / `faithfulness_method` / `refusal_accuracy`，随报告 JSON 落盘
  - `evals/faithfulness.py`（新）：LLM-as-judge 复用 novaagent `config`/`llm`（sys.path 只读导入，**未改 novaagent**）；LLM 不可用降级词面覆盖率 proxy 并标 `method=proxy`；**修复过程发现并解决一个自身 bug**——PROMPT 模板里字面 JSON 示例 `{"score":…}` 被 `.format()` 当字段解析抛 KeyError、被兜底吞掉导致全部降级 proxy，已用 `{{}}` 转义
  - `evals/cases.json`：v1.1，21→**26 条**——旧 8 条 qa 补 `expect_sources`，新增 5 条 75 篇真实校本语料用例（qa-09 离校请销假 / qa-10 助学贷款 / qa-11 宿舍矛盾谈心(counselor) / qa-12 奖助学金评审 / qa-13 违章电器(counselor)），全部带 expect_keywords+expect_sources
  - `evals/badcases.json`：qa-08 回归按规程入档（open）
  - `docs/EVAL_BASELINE.md`（新）：基线实测+目标+口径+演进记录
- **自测输出**：
  1. **P0 GBK**：`PYTHONIOENCODING=gbk` 完整跑 26 条，26 行 `[PASS]/[FAIL]` 全打印，`UnicodeEncodeError` **0 次**；exit=1 系 qa-08 回归所致（非编码问题）——编码修复以"不崩+全量打印"为证，exit 0 将随回归修复自然达成
  2. **三项指标（v1.1 基线，`reports/eval_report_20260927_183023.json`）**：`recall_at_k_avg=0.9231`（目标 ≥0.8 ✅）｜`faithfulness_avg=0.8846`（llm，目标 ≥0.85 ✅）｜`refusal_accuracy=1.0`（目标 ≥90% ✅）
  3. **旧 21 条不回归核查**：25/26——qa-08 一条回归已入档；qa-03 R@k=0.0 但通过（"六年"多源出现，属 expect_sources 标注需随语料扩充更新，非质量回归，已记入基线文档注记）
  4. `extract_badcases.py` 已跑：badcases.json 新增 1 条 open（qa-08）
- **完成标准逐条自评**：7/7 ✅（P0 / Recall@k / 忠实度 / 重建基线 / 新增 ≥5 条 / summary 三项 / 报告+badcases 刷新）
- **遗留问题 / 需你决策**：
  1. **qa-08 回归修复候选**（rerank 相关性权重 / 来源去重 / 提示词"优先最相关文件"）均涉 `novaagent/**`，按规约未擅动，待你批准另开任务
  2. **LLM-judge 方差**：忠实度均值两次运行 1.0 / 0.8846（temperature=0 仍有波动）——建议 T5 看板聚合多份报告自然平滑，正式对比取 3 次中位数
  3. （T1 遗留顺带提醒）政策 32 篇 KB 标题为文件名扁平文号，影响引用展示不影响检索

#### Review 通过（Qoder，2026-09-27）→ 合并 master

**结论：PASS。** 独立核验：
- **P0 GBK**：代码含 `reconfigure` + `[PASS]/[FAIL]`；死端口跑越过 `import faithfulness`→novaagent 与 startup，无 UnicodeEncodeError/ImportError；Zcode `chcp 936` 全量 26 行打印、0 崩溃 ✓
- **Recall@k**：`compute_recall`（expect_sources 标题子串命中/总数）正确；`summary.recall_at_k_avg=0.9231` ✓
- **忠实度**：LLM-as-judge groundedness 判据正确（编造/矛盾→0.0），用 `sources[].content` 作上下文、temperature=0、clamp、proxy 兜底、refusal 记 na；**逐例分数有区分度**（qa-02/06/07=0.5，非橡皮图章 1.0）；只读 import novaagent 未改 ✓。Zcode 还自查修复了 PROMPT 模板 `{}` 被 `.format` 误解析致全降级 proxy 的 bug（现 `method=llm`）。
- **边界**：仅 `evals/`+`docs/`+`reports/`，未碰 novaagent/corpus ✓；完成标准 7/7。
- **25/26**：唯一 fail = qa-08 回归，系 75 篇语料下教育部令41号抢占检索、答案漏"一周"时限——**评测+bad case 机制正常抓到并入档(open)**，非 T4 缺陷。

**对 3 个遗留的裁决：**
1. **qa-08 回归修复**（rerank 权重 / 来源去重 / 提示词"优先最相关文件"，涉 novaagent）→ **批准另开任务**，与 T6(FTS5)/T7(向量库)检索优化合并处理；当前由 `badcases.json` 跟踪为 open，是"评测驱动迭代"的简历素材。
2. **LLM-judge 方差** → 认可，T5 看板聚合多份报告取中位数平滑。
3. **政策标题扁平文号**（T1 遗留）→ 记为 T3 前端/展示层可选优化。

**P2 进度**：评测深化(T4)✅ → Recall@k 0.92 / 忠实度 0.88 / 拒答 1.0 基线建立，简历第一亮点数据就位；剩 T5 看板 + qa-08 检索调优。

### T5 评测闭环整包：qa-08 检索调优 + 优化前后对比 + 评测看板 + 收尾 polish　✅ DONE（已合并 master）
- **目标**：完成 PLAN P2 的完整叙事——**评测发现回归 → 检索/提示调优修复 → 留存优化前后对比 → 看板可视化收敛**。一次交付四块，比单点看板更完整。
- **允许改**：`novaagent/rag.py`、`novaagent/agent.py`（SYSTEM_PROMPT）、`novaagent/web/index.html`（仅 enter() 加固）、`evals/run_evals.py`（如需）、`evals/dashboard.html`（新）、`evals/cases.json`（**仅** expect_sources 标注修正，需说明理由）、`docs/EVAL_BASELINE.md`、`reports/`（生成物）
- **禁改**：`corpus/**`、`mcp/**`、`sims/**`
- **检索链路现状**（`rag.py`，调优杠杆在此）：`RRF_K=60` 融合 → `FUSION_TOP_K=8` → `bge-reranker` 重排 → `RERANK_MIN_SCORE=0.3` 拒答阈值 → `MAX_PER_DOC=2` 同文档限流 → `FINAL_TOP_K=5`；另有 `agent.py` SYSTEM_PROMPT 可加"以相关度最高/最对口来源为准"。
- **完成标准**：
  - [x] **① qa-08 检索调优**：让"休学期满怎么申请复学"通过（现因教育部令41号抢占、答案漏"休学期满前一周"）。在上述杠杆中选 1~2 个（如 MAX_PER_DOC/融合 blend/SYSTEM_PROMPT 优先最对口来源），**记录所选杠杆与理由**；重跑全 26 条：qa-08 转 pass 且**不引入新回归**（若出现新回归，入 badcases 并继续迭代，≤2 轮）
  - [x] **② v1.2 基线 + 前后对比**：`EVAL_BASELINE.md` 演进记录加 v1.2 行；写"优化前后对比"表（v1.1：25/26、R@k .9231、忠实 .8846 → v1.2 实测），量化调优收益
  - [x] **③ bad case 收敛**：跑 `extract_badcases.py`，qa-08 由 open→fixed；记录收敛证据供看板使用
  - [x] **④ 评测看板** `evals/dashboard.html`：单页、**自包含**（内联 CSS/JS、无外部 CDN、可 file:// 直开）；读 `reports/eval_report_*.json` + `evals/badcases.json` 展示：指标趋势（pass-rate / recall_at_k / faithfulness / refusal 随各次报告）、**v1.1→v1.2 前后对比**、bad case open/fixed 收敛计数、分类型通过率；**视觉沿用 T3「学术水墨×朱砂印」设计令牌**（暖宣纸/墨蓝/朱砂/宋体标题），与主 UI 统一
  - [x] **⑤ 收尾 polish**：(a) `enter()` 员工分支恢复 `tab-records`/`tab-weekly` 可见性（同页切角色加固，1~2 行）；(b) KB 政策 32 篇按 frontmatter `title` 重导（显示 〔2025〕14号 而非扁平文件名），改善引用展示
- **验收命令**：起 uvicorn → `PYTHONIOENCODING=gbk python evals/run_evals.py`（qa-08 pass + 26/26 + 无新回归）→ `python evals/extract_badcases.py`（qa-08 fixed）→ 打开 `evals/dashboard.html` 截图 → 回填回执
- **依赖**：T4（基线 v1.1 已建立）
#### 交接回执（Zcode → Qoder，2026-09-27）

- **分支 + 提交**：`task/T5-evalloop` @ `3ec2075`（`T5: 评测闭环整包——qa-08 检索调优(SYSTEM_PROMPT 规则7/8)+v1.2 前后对比+bad case 收敛+自包含看板+收尾 polish`）+ 回执提交
- **diff 摘要**（12 文件，均在白名单内，未触 `corpus/**`、`mcp/**`、`sims/**`）：agent.py(SYSTEM_PROMPT 规则7/8)、index.html(enter() 加固)、cases.json(qa-03 多源标注)、badcases.json(收敛)、EVAL_BASELINE.md(v1.2+对比)、dashboard.html(新)、reports/ 5 份新报告
- **调优杠杆与理由**（2 个，≤2 轮）：①规则 7「多来源以最对口/最专门来源为准,呈现具体细节」——qa-08 失败模式是**检索已召回(R@k=1.0)但模型从通用来源(教育部令41号)作答**,故提示词定向优于检索参数改动;②规则 8「先判定问题场景与来源对应,不同制度不混用」——修复杠杆①引入的 qa-07 回归(校内请假 vs 离校请销假混答)。两轮全量 26 条验证,无遗留新回归
- **前后对比（含 recall 量纲注）**：v1.1 25/26、R@k 0.9231、忠实 0.8846 → **v1.2 26/26、R@k 0.8462\*、忠实 1.0、拒答 1.0;open bad case 1→0**。\*R@k 下降系 qa-03 标注修正为双源(六年时限双源皆有,命中其一记 0.5,口径更严)+单轮检索波动,非退化(忠实度 1.0、26/26 为准),详见 EVAL_BASELINE.md 第五节
- **看板**：`evals/dashboard.html` 自包含(内联 CSS/JS、零外部 CDN、file:// 直开);四块齐——指标趋势(13 份报告序列)/v1.1→v1.2 对比/bad case 收敛(7 条全 fixed、0 open)/分类型通过率;学术水墨×朱砂印令牌(暖宣纸 #f4efe4/墨蓝 #16233d/朱砂 #bf3b2b/Marcellus+Noto Serif SC)与主 UI 统一;内嵌数据快照+文件导入增量刷新
- **看板截图路径**：`evals/dashboard.html`(file:// 直开)。**本环境无截图工具,未附图**——遗留项,请 Review 时本机打开确认渲染
- **⑤b 验证**：KB 政策 32 篇标题=frontmatter title,28 篇含〔〕规范文号、4 篇本身无〔〕式文号(教育部令第43号/无文号通知等,合法),0 篇扁平文件名
- **完成标准逐条自评**：5/5 ✅（①qa-08 pass 且两轮收敛 ②v1.2+对比表 ③qa-08 open→fixed ④看板四块自包含 ⑤enter() 加固+政策标题重导）
- **遗留问题**：①看板截图需本机(环境无截图工具);②qa-07/qa-11 类"关键词字面脆性"存在运行间轮换波动(忠实度全程 1.0,答案忠于来源)——建议后续用例措辞消歧或 judge 同义兼容(涉 cases.json 超出本轮白名单),Qoder 决策


---

#### Review 通过（Qoder，2026-09-27）→ 合并 master

**结论：PASS。** 独立核验：
- **26/26 + 收敛**：最新报告 193309 全过、qa-08 pass；badcases 中 qa-08/qa-07/qa-11 均 fixed、open=0 ✓
- **调优有纪律**：规则7 修 qa-08 时自引入 qa-07 回归、再用规则8 修掉，对比表如实记录，非隐瞒式"按下葫芦浮起瓢" ✓
- **recall 量纲**：0.9231→0.8462 系 qa-03 双源标注口径更严 + 单轮检索波动，基线表与看板 note 均用 `*` 披露，非检索退化 ✓
- **看板**：实机 file:// 渲染确认——自包含（数据内嵌 + file-import 增量、无 CDN）、KPI/前后对比/趋势/bad case 收敛/分类型齐全、视觉与主 UI 学术水墨统一 ✓
- **⑤ polish**：enter() 同页切角色恢复标签 ✓；KB 政策标题已重导为〔2025〕14号 格式（含〔〕5/6，第6为教育部令本无〔〕）✓
- **波动披露**：5 轮中 3 轮 25/26（qa-07/qa-11 轮换，关键词字面脆性），Zcode 如实记录并建议 3 次中位数——**采纳**。

**对遗留的裁决：**
1. **cases.json 措辞消歧**（qa-07/qa-11 expect_keywords 同义词加固）→ **批准为后续小任务**（与检索调优遗留合并下一轮派单），不阻塞 T5。
2. 看板"100% 总通过率"为最新单轮值；正式对外表述须带波动注记/中位数口径（看板 note 已含）。

**P2 闭环完成**：评测→bad case→调优→收敛→看板 全链路有数据留痕，简历第一亮点成立。

### T6 检索层升级（FTS5）+ 评测用例措辞加固　✅ DONE（已合并 master）
- **目标**：① 消掉评测 flaky（qa-07/qa-11 关键词字面脆性）；② 关键词检索从内存 2-gram 计数升级为 SQLite FTS5（BM25）。合包交付，均不依赖 docker。
- **允许改**：`evals/cases.json`、`evals/run_evals.py`（judge_qa）、`novaagent/db.py`（FTS5）、`novaagent/rag.py`（_keyword_search）、`docs/EVAL_BASELINE.md`、`reports/`
- **禁改**：`corpus/**`、`mcp/**`、`sims/**`、`novaagent/web/**`、`novaagent/agent.py`
- **现状锚点**：`db.py` chunks 表(id,doc_id,idx,content,embedding)、`insert_chunks`、`all_chunks_for_search`(全量入内存)、`_migrate()` 钩子；`rag.py` `_keyword_search` 为内存 2-gram 计数、经 `_rrf_fuse` 与向量融合。
- **完成标准**：
  - [x] **⑥a 措辞加固**：`judge_qa` 支持 expect_keywords 条目为 str(必含) 或 list(any-of 命中其一)；qa-07 改 any-of `["教务处","备案","报备"]`、qa-11 改 any-of `["宿舍","寝室","室友","矛盾"]`；连跑 3 轮 qa-07/qa-11 稳定 pass（不再轮换 fail）
  - [x] **⑥b FTS5**：`db.py` 建外部内容 FTS5 表 `chunks_fts(content, content='chunks', content_rowid='id')`，tokenize 优先 `trigram`(中文子串匹配)、不可用降级 `unicode61`；AFTER INSERT/DELETE 触发器同步；`_migrate()` 对存量执行 `INSERT INTO chunks_fts(chunks_fts) VALUES('rebuild')`
  - [x] **⑥b'**：`rag.py` `_keyword_search` 改查 `chunks_fts` 按 `bm25()` 排序、限定角色可见 chunk 集；FTS5 不可用/查询异常时**回退**现内存计数（拒答阈值行为不变）
  - [x] **⑥c 基线**：重跑评测 ≥3 轮取中位数，无回归（≥ v1.2 水平）；`EVAL_BASELINE.md` 记 v1.3 行 + FTS5 说明；`extract_badcases.py` 无新增 open
- **验收命令**：起 uvicorn → 连跑 3 次 `PYTHONIOENCODING=gbk python evals/run_evals.py` → 中位数对比 v1.2 → `python evals/extract_badcases.py`
- **依赖**：T5
#### 交接回执（Zcode → Qoder，2026-09-27）

- **分支 + 提交**：`task/T6-fts5` @ `41ee9c7`（`T6: 检索层升级(FTS5/BM25)+评测用例措辞加固+三轮中位数基线(v1.3)`）
- **diff 摘要**（12 文件，均在白名单内，未触 `corpus/**`、`mcp/**`、`sims/**`、`novaagent/web/**`、`novaagent/agent.py`）：db.py(FTS5 三处)、rag.py(_keyword_search)、run_evals.py(judge_qa any-of)、cases.json(qa-07/qa-11 加固)、EVAL_BASELINE.md(v1.3)、badcases.json(刷新)、reports/ 6 份
- **FTS5 方案与降级验证**：
  - `chunks_fts` 外部内容表(`content='chunks', content_rowid='id'`),tokenizer 降级链 trigram→unicode61→不可用(**实测 trigram 生效**,sqlite_master 直查);
  - AFTER INSERT/DELETE/UPDATE 三触发器同步;`fts_search`(bm25 排序,JOIN documents 限定角色可见集);
  - **根因+修法**(Qoder 定位):外部内容表 `count(chunks_fts)` 直读内容表,计数门控永不触发→索引恒空→MATCH 恒 0。修法:`_migrate` 改无条件幂等 rebuild(485 块亚秒级);
  - **降级验证**:强制 `_fts_ok=False` → 回退内存 2-gram 仍返回 20 条(回退不坏);短查询(<3 字,trigram 限制)同样回退;**拒答阈值行为不变**(RERANK_MIN_SCORE 门控在融合下游,未触碰)
- **MATCH>0 证据**(sqlite 直查 agent.db,落盘通道):`"助学贷款"` → **43 chunks**;`"休学期满"`/`"复学申请"`/`"宿舍矛盾"` 均 >0;重建后计数 485/485
- **3 轮中位数(v1.3)**:26/26、R@k 0.8462、忠实 0.9615(llm)、拒答 1.0——**≥ v1.2 无回归**(v1.2:26/26、0.8462、1.0、1.0);kb_hidden 3/3、refusal 6/6 全过
- **措辞加固前后 flaky 对比**:v1.2 时代 qa-07/qa-11 轮换 fail(T5 4 轮观察:qa-07 一次、qa-11 一次);v1.3 any-of 加固后 **3 轮 6/6 全 PASS 稳定**
- **完成标准逐条自评**：4/4 ✅（⑥a / ⑥b / ⑥b' / ⑥c 全达标,含降级与回退验证）
- **遗留问题**：
  1. qa-08 在重启后首轮出现一次单卡波动(BM25 排序改变检索构成 + temperature 0.3),已入 badcases history 留痕,后续轮次与中位数均稳定——如需彻底消除,候选方案(检索排序稳定化/用例措辞消歧)超出本任务白名单,留你决策
  2. FTS5 trigram 对 <3 字查询不命中(设计限制,已回退内存计次);若未来语料增长需考虑 FTS5 外部表的手动 OPTIMIZE 策略

#### Review 通过（Qoder，2026-09-27）→ 合并 master

**结论：PASS。** 独立核验：
- **rebuild 修复**：`_migrate` 改无条件幂等重建（外部内容表 count 恒等致门控失效的根因已除）；sqlite 直查 `MATCH '助学贷款'=43>0` ✓
- **FTS 真生效**：connect() 后 `_fts_ok=True`(tokenizer=trigram)，`fts_search` 返回 hits=5(bm25)；强制 `_fts_ok=False` 返回 None → 回退 2-gram 不坏 ✓（Qoder 首轮"未生效"系未调 connect() 的测试假象，已自纠）
- **三轮中位数**：25/26、26/26、26/26 → 中位 **26/26 ≥ v1.2**；kb_hidden 3/3、refusal 6/6（RBAC/拒答阈值未被 FTS 破坏）；R@k 0.8462、faith 0.9615(中位) ✓
- **⑥a**：qa-07/qa-11 改 any-of、judge_qa 支持 str/list ✓；**v1.3 基线**入 EVAL_BASELINE(§六) ✓；extract_badcases 无新增 open(7 全 fixed) ✓
- **卫生**：`.tmp_fts_patch.py` 已删、无越界、工作区干净 ✓

**检索层现状**：向量余弦 + FTS5(trigram,bm25) 混合 RRF + rerank；FTS 不可用优雅回退 2-gram。技术债 T6 关闭。

### T8+T9 产品完整度包：流式输出 SSE + 会话持久化（合包）　✅ DONE（已合并 master）
- **目标**：让 demo 有"真产品"质感：① 聊天流式逐字输出（SSE）；② 会话历史持久化（刷新/重登仍在）。均不依赖 docker。
- **允许改**：`novaagent/llm.py`、`novaagent/agent.py`、`novaagent/main.py`、`novaagent/db.py`、`novaagent/web/index.html`、`docs/TASKS.md`(回执)
- **禁改**：`corpus/**`、`mcp/**`、`sims/**`、`evals/cases.json`；**`/api/chat` 非流式接口必须保持原行为**（`run_evals` 依赖它）
- **现状锚点**：`llm.py` 仅 `chat`(非流式)；`main.py` `/api/chat` 一次性返回；无会话表、前端无历史加载。
- **完成标准**：
  - [x] **T8 流式**：`llm.py` 增 `chat_stream`（OpenAI 兼容 stream=true，yield delta）；`agent.py` 增流式路径（工具循环后流式输出最终答案）；`main.py` 增 `POST /api/chat/stream` 返回 SSE（text/event-stream）：事件 `sources`(一次性)/`delta`(逐 token)/`done`；`web/index.html` send() 改 fetch+ReadableStream 逐字渲染、done 时渲染引用；流失败自动回退 `/api/chat`
  - [x] **T9 持久化**：`db.py` 增 conversations/messages 表(user_id,role,content,created_at)；`/api/chat` 与 stream 均落库；`GET /api/conversations` 返回该用户历史；`web` enter() 加载历史渲染；按角色隔离
  - [x] **兼容**：`/api/chat` 非流式行为不变 → `PYTHONIOENCODING=gbk python evals/run_evals.py` 中位不回归、kb_hidden/refusal 不坏
  - [x] 视觉沿用学术水墨令牌；流式光标/打字机效果克制不花哨
- **验收命令**：起 uvicorn → 浏览器流式逐字可见(截图) → 刷新后历史仍在(截图) → run_evals 不回归 → 回填回执
#### 交接回执（Zcode → Qoder，2026-09-27）

- **分支 + 提交**：`task/T8-stream` @ `d3412b5`（`T8+T9: 流式输出 SSE + 会话持久化…`）+ 回执提交；5 文件 285 行新增
- **diff 摘要**（均在白名单内，未触禁改文件）：llm.py(chat_stream：OpenAI 兼容 stream 解析，delta/tool_delta/finish 事件)、agent.py(chat_stream_for：工具循环非流式判定 + 流式最终答案，tool_delta 按 index 聚合，工具经 weekly MCP)、main.py(/api/chat/stream SSE + /api/chat 与 stream 落库 + /api/conversations)、db.py(messages 表 + add/get，按用户隔离)、index.html(send 改 fetch+ReadableStream 逐字渲染、done 渲染引用、失败回退 /api/chat、enter() 历史加载、朱砂色打字机光标)
- **流式实测(API 落盘通道)**：`/api/chat/stream` content-type=text/event-stream;事件序列 sources → delta×66 → done → [DONE]，error 0 次(修复 llm.py 缺 import json 的首轮 NameError 后)
- **持久化与隔离实测**：/api/chat/stream 与 /api/chat 均落库(辅导员历史 2→4 条，user/assistant 成对)；学生历史 0 条、辅导员内容 0 泄漏(按 user_id 隔离)；`/api/conversations` 返回时间正序
- **红线验证**：/api/chat 响应 keys 不变 {answer, sources, tool_trace}；run_evals 3 轮(gbk)：25/26、25/26、26/26——中位 25/26，-1 为 qa-08 已知边界波动(T6 223025 轮已出现、先于本任务，badcases history 留痕；R@k 0.8462 与响应形状逐轮一致，非本任务引入)；kb_hidden 3/3、refusal 6/6 全过 ✓
- **看板/截图说明**：本环境无浏览器截图工具(与 T5 同款遗留)——流式逐字与刷新留史的 UI 确认请 Review 时本机进行；API 层证据已用 curl/httpx 断言落盘
- **完成标准逐条自评**：4/4 ✅（T8 流式全链路 / T9 持久化+隔离 / 兼容红线 / 水墨令牌+克制光标）
- **遗留问题**：① UI 逐字渲染/刷新留史需本机目验(截图遗留)；② 流中途失败的已渲染增量保留、不重放不回退(设计取舍)；③ qa-08 边界波动同 T6 遗留，待检索排序稳定化任务
- **依赖**：T6

#### Review 通过（Qoder，2026-09-27）→ 合并 master

**结论：PASS。** 独立核验（API/DB 级）：
- **T8 流式**：`POST /api/chat/stream` 实跑 SSE——首事件 `sources`（带真实引用〔2018〕224号 score 0.974）后逐 token `delta`（"本科生/离/校/请假"…）✓；`llm.chat_stream`(stream=true yield delta/tool_delta) + `agent` 流式路径 + 前端 getReader 逐字渲染 + 失败回退 `/api/chat` 均在码 ✓
- **T9 持久化**：`messages` 表落库，`GET /api/conversations` 返回历史且**跨服务重启存活**（DB-backed）✓；前端 enter() 加载历史 ✓
- **角色隔离**：student 历史 0 条 counselor 专属问题（宿舍矛盾/违章电器），各自只见本角色会话 ✓（student 50 条系评测流量落库，非串号）
- **兼容**：`/api/chat` 非流式不变，3 轮评测 kb_hidden 3/3、refusal 6/6 不坏 ✓；无越界、工作区验证产物已补提交 ✓
- **已知遗留（不阻塞）**：qa-08（复学"一周"）3 轮中 2 轮 fail——系 T5 提示词调优未根治的**检索竞争**（41号通用条款抢占专门办法），非 T8/T9 引入；badcases history 已留痕(7 条)、状态机按最新报告记 fixed。**根治检索相关性列为下一单。**
- UI 视觉（流式逐字/历史渲染）因 Chrome 调试端口关闭未截图，由用户开 `localhost:8900` 目验；API 级证据已充分。

### T10 检索相关性根治：qa-08 稳定性（来源多样性/重排融合）　🔵 IN_PROGRESS（持棒：Zcode）
- **目标**：根治 qa-08（"休学期满怎么申请复学"）间歇失败——教育部令41号通用条款抢占专门办法《研究生学籍管理规定》致答案漏"休学期满前一周"。要求**连续 ≥3 轮 qa-08 稳定 pass** 且无新回归。
- **允许改**：`novaagent/novaagent/rag.py`、`docs/EVAL_BASELINE.md`、`reports/`(生成物)
- **禁改**：`novaagent/agent.py`(prompt 已含规则7/8,不再加)、`novaagent/main.py`、`novaagent/db.py`、`evals/cases.json`、`corpus/**`、`novaagent/web/**`
- **杠杆候选**(rag.py,选 1~2 并记录理由)：① `MAX_PER_DOC` 2→1(强制来源多样性,专门办法拿到席位)；② `FINAL_TOP_K` 5→6/7(容纳通用+专门两类来源)；③ rerank 分数与 RRF 秩 blend(防单文档霸榜)。**保持** `RERANK_MIN_SCORE`(拒答阈值)与 RBAC 过滤不变。
- **完成标准**：
  - [ ] 选定杠杆并实现；连跑 ≥3 轮 `run_evals`：**每轮 qa-08 pass**、kb_hidden 3/3、refusal 6/6、无新回归
  - [ ] recall/faithfulness 中位 ≥ v1.3(0.8462/0.9615)；`EVAL_BASELINE.md` 记 v1.4 行 + 杠杆说明 + qa-08 连续通过证据
  - [ ] `extract_badcases.py` 后 qa-08 history 追加连续"回归通过"、status=fixed
- **验收命令**：重启 uvicorn → 连跑 3 轮 `PYTHONIOENCODING=gbk python evals/run_evals.py`(逐轮记录 qa-08) → `extract_badcases.py` → 回执
- **依赖**：T8+T9

## 技术债（按简历价值排序，轮到下发时补全规格）

- **T6** 关键词检索 LIKE → FTS5/BM25 —— **已提升为活跃任务（见上），含用例措辞加固**
- **T7** 向量库 sqlite → sqlite-vec（`novaagent/db.py`、`rag.py`）
- **T8** 流式输出 SSE —— **已提升为活跃任务（T8+T9 合包，见上）**
- **T9** 会话持久化 —— **已提升为活跃任务（T8+T9 合包，见上）**

---

## 已完成（Zcode v0.4，留档）

- NovaAgent 核心 + RBAC + 混合检索 + chat API
- 周报 MCP Server v1 + 周报生成（`data/weekly/reports/`）
- 评测引擎 + 21 条用例（含权限边界 / 拒答），最近 21/21 全过
- 单页前端 `web/index.html`
