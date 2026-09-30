# P4c KB 文件夹 + `@` 指定检索范围 + 学段元数据

> 分支 `task/P4c-kb-folders`（自 master 切出），实现者 **WorkBuddy**，规格见 `docs/TASKS.md` P4c 条目 C1~C9，设计见 `docs/P4.md` §M5。
> 测试节奏（用户 2026-09-30 指示）：实现期只做针对性最小检查，功能齐后集中跑一轮完整评测 + 冒烟。

## 一、架构

```
KB 页(C6)                        输入框(C4)
┌──────────────────────────┐    ┌────────────────────────────────────┐
│ 文件夹树(#folder-tree)    │    │ 键入 @ → #at-picker 多选(文件夹/分类)│
│ ├ 全部文档 / 根目录       │    │ 选中 → #scope-chips 芯片            │
│ └ 📁 子夹(缩进/计数/管理) │    │ 发送 → {question, scope} 分离传参   │
│ 筛选: 位置/分类/学段      │    │   question 永不含 @xxx(服务端 400 兜底)│
│ 批量: 勾选→移动/标学段    │    └────────────────────────────────────┘
└────────────┬─────────────┘                 │
             │ REST                          ▼
┌────────────▼─────────────────────────────────────────────────────┐
│ main.resolve_scope: 请求 folder_ids ∩ visible_folder_ids(用户,角色)│
│   全部不可见 → 404「指定的知识库不存在或无权访问」(不泄露存在性)    │
│   范围内可见文档数=0 → 200 明确提示「未做全库检索」(硬约束 3)       │
│   学段敏感+无学段词+库内本/研成对标注 → 追问学段(C5, 不猜)          │
└────────────┬─────────────────────────────────────────────────────┘
             ▼
┌──────────────────────────────────────────────────────────────────┐
│ agent.chat_for/chat_stream_for(..., scope) —— 仅透传(P4c 白名单)  │
│ rag.search_with_quality(query, min_rank, scope)                  │
│   └ db.all_chunks_for_search(min_rank, folder_ids, categories,   │
│                               audience)  ← RBAC 之上再收窄        │
│   └ db.fts_search(..., folder_ids, categories, audience)         │
│                              ← FTS 层同步收窄(防 scope 外占满 top_k)│
└──────────────────────────────────────────────────────────────────┘
```

## 二、C1~C9 逐条自评（证据对照见 §四）

- **C1** ✅ `folders(id,name,parent_id,owner_id,visibility,created_at)` + `documents.folder_id`(NULL=根) +
  `documents.audience`(undergrad/postgrad/common, DEFAULT 'common')。迁移只 CREATE IF NOT EXISTS / 幂等加列 /
  建索引，**不 UPDATE 任何既有行**。副本库对账（`.tmp` 探针 8/8）：documents 65→65→65、chunks 487→487→487（二次启动幂等）、
  folder_id 全 NULL、audience 全 common、两次启动 schema 一致。**真实库迁移走 `db.py` 启动代码，未脚本改库**。
- **C2** ✅ `POST/GET/PATCH/DELETE /api/kb/folders` + `PATCH /api/kb/documents/{id}` + `POST /api/kb/documents/move`。
  同层重名 409（只对请求者可见的重名拒绝，避免误伤他人 private 夹）；**非空删除默认 409** + hint 提示移动，
  `cascade=true` 级联删壳、**文档移回根目录（不删文档，KB 守恒）**；删除/重挂前做子树与环检查。
  实测 28/28（`after/c2_c3_c4_c5_api_checks.json`）。
- **C3** ✅ `rag.search(query, min_rank, scope=None)`、`rag.search_with_quality(..., scope=None)`（返回结构形状未变）、
  `db.all_chunks_for_search(min_rank, folder_ids=None, categories=None, audience=None)`。**scope 与 RBAC 取交集**
  ——folder/categories/audience 只会收窄候选集，文档自身 `role_min` 恒生效，文件夹可见性无法提权。
  db 层 9/9（指定夹候选=该夹文档全块、`folder_ids=[]` 直接空、audience 对全 common 库无操作、FTS 层同步收窄）。
  **三输入对照表**见回执（全库 / 指定正确夹 / 越权夹）。
- **C4** ✅ `@` 仅作唤起符号：键入 `@` 弹多选（文件夹+分类），选中进芯片；发送时 `question` 与 `scope` 分离。
  **断言**：选中后输入框无 `@` 残留（UI 探针实测 `q=''`）；服务端对 `@` 开头问句 400 兜底；C4 请求体实测见回执。
- **C5** ✅ 上传/批量标注 `audience` + 列表筛选；学段敏感清单（荣誉称号/奖学金/评优/学籍/请假/休学/复学/助学金）
  命中且问句未自带学段词、无 hint、**且库内确有本/研两段成对标注材料**（`db.audience_conflict`）→ 确定性追问
  （不猜）；问句自带学段词或带 `audience_hint` → 自动映射 `scope.audience`（`audience IN (学段,'common')`，
  未标注文档不受影响 → 存量库零回归）。编排式多轮留给 P4d。
- **C6** ✅ KB 页「表格+分类下拉」→「文件夹树 + 文档列表 + 批量条」；上传表单加学段/文件夹；零新依赖
  （无框架/构建/公网 CDN），样式沿用主题变量。UI 探针 8/8 + 截图（`kb_page_after.png`/`at_picker.png`），
  控制台零 error。
- **C7** ✅ 新增类型 `scoped_qa` 3 条：`sq-01`（指定夹后来源全属该夹）、`sq-02`（空库 → 提示 + 零来源，
  `expect_context.scope_empty=true`）、`sq-03`（越权夹与不存在同表现 404）。断言全部能失败且计入
  `total_pass`（坑 39）；用例自备夹、自清理（teardown 复位文档 folder_id + 级联删夹）。
- **C8** ✅ 集中评测（单轮,`reports/eval_report_20260930_140221.json`,退出码 0）：**43/43(100%)**、
  R@k **0.9412**、拒答 **1.0**、隔离断言 ok、scoped_qa **3/3**；忠实度 0.9412(llm) 低于 v1.8 中位 0.9706,
  属第十一节已裁决移交 P4d 的 judge 学段声明盲区方差,**未为指标删学段声明**。
  基线口径 **40 → 43** 已记账（EVAL_BASELINE 第十三节、HANDOFF 坑 40 同款纪律）——**43/43 才是满通过**。
- **C9** ✅ `smoke_test.py` GBK exit 0、`documents 65→65`；只读查库 `chunks 487`、`folders` 评测后归零（自清理）；
  证据入库对账见 §四。

## 三、三个硬设计约束的落地

1. **RBAC 优先于 scope**：解析只在 `main._resolve_scope` 做（`db.visible_folder_ids`），越权/不存在一律
   404 同文案（实测两请求响应体逐字节一致）；管理端点先撞角色闸（403，与 P4a permission_api 惯例一致），
   读路径才是「不可见=不存在」404。
2. **`@` 不进 question**：前端 `openAtPicker()` 先移除输入中的 `@`；选中即芯片；`buildChatPayload` 分离传参；
   服务端 `question.startswith('@') → 400` 兜底（邮箱类正文中的 @ 不受影响）。
3. **空库不回落**：`db.count_visible_documents` 判定范围内可见文档数为 0 → 200 明确提示
   （`context.scope_empty=true`），检索层 `folder_ids==[]` 直接返回空——**没有任何回落全库的路径**。

## 四、口径与限制（如实）

1. **scope 解析在 main 层**（不在 rag/db）：因为越权判定需要 user_id/role，而 `rag.search` 只有 min_rank；
   `agent.py` 因此保持"纯透传"（白名单边界）。
2. **文件夹可见性语义**：`visibility ∈ private/student/counselor/admin`（private=仅建者，admin 管全部）。
   这是规格 6 列之外的一个**内部语义选择**——用单列同时表达"私有"与"角色线"，避免再建关联表；
   `documents.role_min` 仍是文档级权限的唯一事实源（文件夹可见性永不放宽文档权限）。
3. **audience 过滤放行 common**：`audience IN (指定学段,'common')`——未标注文档不被误杀；
   代价是"学段专属问题"可能混入 common 噪声，靠 P4d 的 rerank 排序消化。
4. **F3 追问触发条件偏保守**：需要库内**同时存在**本/研两段成对标注材料才追问（`db.audience_conflict`）。
   当前库全为 common → 追问不触发，存量评测零回归；后续按学段标注出成对材料即自动生效。
   更激进的"命中清单即追问"会把 qa-07 等无学段词的存量用例全部打成追问（已否决）。
5. **scoped_qa 的 setup 移动真实文档**：sq-01 把学平险通知移入评测夹，teardown 复位；若评测中途崩溃可能
   留下 folder_id 残留（下次运行自愈，且不影响检索正确性——检索按 folder 过滤，文档本身不变）。
6. **追问/空库提示不落会话**：确定性响应不经 agent（不建会话、不落消息）——与 P4a 拒答落库行为不同，
   属实现取舍（提示类交互无需历史）。
7. **sq-01 问句措辞按坑 27 选型**：「学平险的参保方式和保费标准」实测触发 rerank 措辞崩塌（全库对照同样拒答，
   与 scope 无关），改用 BEFORE 基线实测 top 0.9527 的「学平险出险后怎么报销？」；根治属 P4d。

## 五、证据对账

`docs/p4c/evidence/`：
- `before/`：db_schema.txt（8 列无 folder_id/audience、无 folders 表、65/487）、search_signatures.txt
  （rag.py:129/135、db.py:402 改前签名）、no_scope_proof.txt/.json（4 问句全库来源与 top_score）、
  kb_page_probe.json + kb_page_before.png（kb_rows=63、分类选项 5、无文件夹树/@ 选择器、控制台零 error）
- `after/`：c2_c3_c4_c5_api_checks.json（28 步全过 + C4 请求体实测 + 清理守恒 63→63）、
  ui_checks.json + kb_page_after.png + at_picker.png（8 步全过、控制台零 error）
- 探针：`probe_before_{schema,no_scope,kb_page}.py`、`probe_after_{c2_c3_c4_c5,ui}.py`

## 六、遗留

1. r1 隔离断言 404（P4b 遗留，未复现）与本单无关，仍挂账。
2. audience 只做了元数据+筛选+追问，**检索编排（clarify 节点/按学段分列）属 P4d**。
3. `move_documents` 批量上限 100 条/次；文件夹树为平铺缩进渲染（深层级>3 层的视觉优化归 P4g）。
4. 前端 `importUrl()` 仍依赖内联 `event`（坑 31 既存，未顺手修）。
