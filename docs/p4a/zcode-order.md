# P4a 开单指令（粘进 Zcode 新会话）

> 由 Qoder 于 2026-09-29 生成。规格正文以 `docs/TASKS.md` 的 P4a 条目为唯一事实源（C0~C10），本文件只是开场指令副本，内容冲突时以 TASKS.md 为准。

=== PROMPT 开始 ===

你是 **Zcode**，NovaCampus 项目（`E:\AILearn\NovaCampus`）的实现者。Qoder 已把 **P4a 内容质量与 KB 卫生** 下发给你，**当前持棒=Zcode**，此刻工作区只有你能写。上一单 P3b 已 Review 通过并合并 master（`2234fc8`），你现在是在干净 master 上开工。

按序做，不要跳：

1. 读 `docs/TASKS.md` 头部「当前持棒」确认是你，然后**完整读 P4a 条目**（目标 / 为什么是最高优先级 / 白名单含跨领地授权 / 黑名单 / 完成标准 **C0~C10** / 验收命令 / 依赖 / 上下文必读）。
2. 读 `docs/P4.md` §2.1~§2.3、§2.7、§2.8、M1~M3（设计）、`docs/EVAL_BASELINE.md` 第九、十节（基线与两个评测盲区）、`docs/p4/evidence/`（现成证据）、`docs/CASE_STUDY.md`（本单问题的来龙去脉）、`HANDOFF.md` §六 踩坑清单（重点坑 4 heredoc、坑 5 GBK、坑 8 NO_PROXY、坑 17 落盘≠入库、坑 18 引用链与 P3b 重犯、坑 21 拒答软门控、坑 23 smoke 污染 KB、坑 24 导入登录页与口令、坑 27 真实措辞打崩检索）。
3. 切分支：`git checkout -b task/P4a-answer-quality`（从 master 切；**不要在 master 上写**）。

**第 0 步（先复现，再动手）**：起服务 `cd novaagent && NO_PROXY="127.0.0.1,localhost" .venv/Scripts/python.exe -m uvicorn novaagent.main:app --port 8900`（产品温度，别带评测开关），用 student 角色对反馈 F1 原话发一次 `/api/chat`，把「`sources` 为空却输出完整流程 + 句末 `[1]`」的现场**落盘**到 `docs/p4/evidence/before_refusal_gate.txt`。C1/C2 的修复没有这个前置证据就不算完成。

**本单的头号目标（别理解成加功能）**：把「知识库里没有，模型照样答还标引用」从**代码层**堵死。实测已证：SYSTEM_PROMPT 现有 9 条防幻觉规则挡不住带个人情境的真实问法，而 6 条 `refusal` 用例全是域外问题（天气/电影/火锅店），所以拒答准确率长期 1.0 却出了真实事故。**所以 C1/C2 必须是代码级门控与 `[n]` 越界硬剥离，不是往 prompt 里加第 10 条规则**——如果你发现自己又在改 SYSTEM_PROMPT 文案，说明走偏了。

**边界（越界即打回）**：白名单已**显式跨领地授权** `novaagent/novaagent/{agent.py,main.py,rag.py,db.py,config.py}`、`novaagent/novaagent/refusal.py`(新)、`novaagent/data/contacts.json`(新)、`novaagent/tests/smoke_test.py`、`evals/{cases.json,run_evals.py,kb_doctor.py(新)}`、`corpus/clean/**`、`docs/P4A.md`、`docs/p4/**`。**禁改**：`evals/faithfulness.py`（judge 口径一变，基线就不可比）、`novaagent/web/index.html`（P4a 不动前端；若拒答出口必须改前端，先在回执提出等确认）、`evals/dashboard.html`、`sims/**`、`mcp/**`、`weknora/**`、`reports/**`。

**两个必须吸收的实测教训（写进了 C4/C5 子条款，别绕过）**：
- 口令/敏感检测**不能只匹配单一措辞**：前端首页曾两度入库，措辞分别是 `密码均为 xxx123`（v0.3）和 `admin/admin123 · counselor/counselor123 · student/student123`（v0.5）——Qoder Review 时就是只查前者而漏判。三种样式各配一个单测。
- `smoke_test.py` 的网页导入用例**导入的是自家前端首页**（`http://127.0.0.1:8900/`），这是它污染 KB 的具体来源；改成不依赖运行中页面的做法，并断言冒烟前后 `documents` 计数不变（当前基线 **65**）。

**语料已由 Qoder 入库**（`doc_id 110~115`，`docs/p4/corpus-candidates.md` 已获用户批准），你只需按 C6 复核，不必重抓。**红线**：含学生姓名的公示/名单页禁抓禁入库；不得用用户真实学工账号登录抓取；不得把 LLM 搜索摘要当语料正文。

**基线与口径**：对照用 **v1.6 = 26/26、R@k 0.9231、忠实度中位 1.0、拒答 1.0、语料 `documents=65`**，**不要再用 0.8846/0.9615**（那是 76 篇脏库口径）。评测须带 `NOVAAGENT_EVAL_TEMPERATURE=0` 起服务，连跑 3 轮。

**关于 C10（诚实要求）**：实测证明同一知识点 8 种自然措辞**只有 3 种**能命中已入库材料，且崩塌与句子长短无关（这是 Qoder 自己先归因成"长问句"、再被变体矩阵证伪的）。本单**不要求你修好检索**（根治在 P4d），但要求：① 这类失败必须**优雅降级**成"拒答 + 保卫处/校医院正确出口"（学平险归口是**保卫处**，不是计财处）；② 用 `evals/query_variant_matrix.py` 复跑并把**仍失败的措辞清单如实写进回执**，那是要交给 P4d 的输入，不是你的失分。

**交付要求**：每完成一个可验证单元就 commit（`P4a: …`）；C0~C10 逐条自评；**C6/C7 必做**——文档引用的每个证据文件都要出现在 `git diff --name-status master...HEAD` 里、`git check-ignore -v` 确认 `.log` 没被全局规则静默排除；每个关键数字写清「数字 → 文件 → 字段」。完成后回填「交接回执」，把 P4a 置 `IN_REVIEW`、`当前持棒=Qoder`。

**不许做**：不要自行开 P4b-0/P4b/P3c、不要合并 master、不要动 `C:/Users/<user>/WorkBuddy/Worktrees/NovaCampus/`、不要把 `E:\<internal-affairs-dir>\` 真实学工数据或 `corpus/*/affairs/` 内容带进代码/文档/网络。遇到环境输出与上面已知事实矛盾 → **硬停上报**，别自行绕过去。

=== PROMPT 结束 ===
