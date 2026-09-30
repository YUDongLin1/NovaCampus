# P4D：LangGraph 检索编排 + 查询改写重试

> 分支 `task/P4d-graph-rewrite`（自 master `5611c16` 切出）· 实现者/持棒 **WorkBuddy** ·
> 交付状态见 `docs/TASKS.md` P4d 条目回执。
> 设计依据 `docs/P4.md` §M6；背景故事与教训 `docs/CASE_STUDY.md` §3。

---

## 一、一句话结论

**F2「检索崩塌」的根因不是问句长短、也不是向量层——向量层一直是好的；崩塌发生在 `rerank`
的绝对值标定上，而真正的解法是"把口语问法归一成材料里会出现的规范术语"。**

- 同一批问句里，失败者的**向量 top1 余弦 0.58~0.63**（与通过者同级），且**目标材料常已排在融合第 1 位**；
- 同一次检索里，`rerank` 把正确的候选整体压到 **0.03~0.19**，被 `RERANK_MIN_SCORE=0.3` 一刀切成"零来源"；
- 对照：能过的多子句书面问句 rerank **0.418**；纯域外问句（量子计算实验室）**0.0034**。
  也就是说 **rerank 夹在两个极端之间的一整段区间里失去了分辨力**，而这段区间正好装着全部
  口语化真实问法。

**修法（经四范式对照实验选定）**：确定性"术语展开 + 去噪"把问句归一到关键词式——
`学平险 学生平安保险 大学生意外伤害保险`——把同一批问句的 rerank 峰值从 **0.10~0.19 拉到 0.968~0.992**。
LLM 自由改写在实测中产出**更弱且更不稳定**，因此**降为辅助档**并加跑题护栏。

**矩阵（本单硬指标）：单遍 3/8 → 编排 8/8**，且包含学生原句；消融（`NOVA_MAX_REWRITE=0`）回落 3/8，
证明提升**全部**来自改写重试。

---

## 二、依赖（langgraph）

只用 LangGraph 做**状态机编排**：LLM 仍走 `llm.py`（httpx / OpenAI 兼容）、向量仍走 numpy 内存余弦，
**未引入** langchain 的模型 / 向量 / retriever 封装。

```
langgraph==1.2.12              # 直接依赖（pyproject: langgraph>=1.2,<2.0）
langgraph-checkpoint==4.2.0    # 传递
langgraph-prebuilt==1.1.0      # 传递
langgraph-sdk==0.4.5           # 传递
langchain-core==1.6.6          # 传递（仅被 langgraph 内部依赖，本项目不直接使用其任何抽象）
ormsgpack==1.12.2              # 传递
xxhash==4.0.1                  # 传递
jsonpatch==1.33                # 传递
langsmith==0.14.1              # 传递
pydantic==2.13.5 / tenacity==9.1.4  # 传递（pydantic 本已由 fastapi 引入）
```

安装方式：`novaagent/.venv/Scripts/python.exe -m pip install langgraph`（PyPI）。
**未升级任何既有包**（复跑 `pip install langgraph` 输出无 "Successfully installed"，即全部已满足）。

---

## 三、图结构

```
                    ┌─(chitchat)──────────────→ direct   ─┐
intent ─────────────┼─(time)──────────────────→ direct   ─┤   问时间/日期不调 LLM（正则+datetime）
                    └─(retrieval / 降级)──→ retrieve ─ grade ─┬─达标→ done（交回 agent 生成答案）
                                                              ├─有档位→ rewrite ─→ retrieve（≤2 轮）
                                                              └─否则→ refuse（交回 P4a 硬门控）
```

要点：

| 项 | 实现 | 为什么这么做 |
|---|---|---|
| `direct` 路径留痕 | trace 追加 `{"node":"retrieve","skipped":true}`，`context.retrieval_skipped=true` | C3 的 `intent` 用例要能**断言"检索确实被跳过"**，而不是只看"零来源"（坑 45：空集假通过） |
| 首轮必须用原句 | `node_intent` **不覆盖**检索用的 query，`normalized_query` 只入 trace | 让"本来能过的用例"逐字不变——零回归的第一道保险 |
| 意图判定失败 | 超时 / 非 JSON / 字段非法 → 降级 `intent=retrieval`（走检索） | 路由挂了不能不答 |
| 整图异常 | `run_pipeline` 捕获 → 降级单遍检索 + `logger.exception` | 编排是增强不是依赖；异常不再静默 |
| 改写档位 | `build_rewrite_plan(q)`：① 确定性归一 ② LLM（仅当问句含词典核心术语） | 主次分明，避免"乱枪打鸟" |
| LLM 跑题护栏 | `_topic_kept()`：候选式必须与问句共享 ≥2 个非停用 2-gram 或同一核心术语 | 防域外问句被改写成库内主题，把"该拒答"变成"答错题" |
| 用户级 LLM | `run_pipeline(base_url, api_key)` 透传 `effective_llm` | 否则自定义 API 用户会静默走全局 key |

### 踩坑记录（本单新增，已写进 `HANDOFF.md`）

1. **`StateGraph(dict)` 会丢键**。用裸 `dict` 作 schema 时 LangGraph 无法推导通道，
   `ainvoke` 的返回值只保留**最后一个节点**返回的键（实测 `{'y': 2}`），
   表现为节点里 `s['question']` 抛 `KeyError('question')`。
   **必须用 `TypedDict(total=False)` 显式声明每个通道。**
   本 bug 曾让整图 100% 走异常降级分支（=退化成 pre-P4d 行为），
   而 `retrieve_with_retry` 不走 LangGraph 所以矩阵仍显示 8/8——
   **"核心逻辑对"不等于"接线对"，服务路径必须端到端实测**。
2. **Prompt 里的 JSON 示例花括号会被 `str.format` 当占位符**。
   `INTENT_PROMPT.format(q=...)` 抛 `KeyError '"intent"'` → 意图判定**从未生效**
   （一直被 except 兜底成 `retrieval`）。修法：示例花括号写成 `{{ }}`。
   影响面：`chitchat` 快路径此前从未命中。

---

## 四、C1~C8 自评

### C1 图落地 + 延迟对照 ✅

`docs/p4d/probe_latency.py`（每例 3 次取中位，TTFD=SSE 首个 `delta` 到达毫秒数）：

| 场景 | 类型 | TTFD(ms) | E2E(ms) | 检索跳过 | 检索轮数 | intent |
|---|---|---|---|---|---|---|
| 时间类（正则直答） | 直答 | **381** | 451 | True | 0 | time |
| 闲聊 | 直答 | **905** | 870 | True | 0 | chitchat |
| 普通 qa（单遍达标） | 检索 | **2161** | 2898 | False | 1 | retrieval |
| 改写路径（2 轮） | 检索 | **3778** | 5440 | False | 2 | retrieval |

- 直答路径 TTFD 上界 **905ms** < 检索路径 TTFD 下界 **2161ms** → 快路径显著更快；
- 问时间类**零 LLM**（`intent` 节点 trace 的 `llm_called=false`，无网络往返）；
- 普通 qa 检索轮数 = 1，与 pre-P4d 完全同路径 → **不劣化**（代价只在"本来就会失败"的问句上）。

### C2 质量信号 ✅

`rag.search_with_quality()` 返回 `quality = {top_score, n_above_threshold, rerank_available, fused_candidates}`。

- `fused_candidates` 为 P4d 新增（融合候选条数），是"是否还有改写价值"的判据；
- `grade` 判定 `top_score ≥ 0.3 且 n_above_threshold ≥ 2`（`config.GRADE_MIN_SCORE/GRADE_MIN_ABOVE`，env 可配）；
- **返回结构形状未变**：`sources` 仍是 `[{ref,title,content,score,role_min}]`，`scope` 语义（P4c）
  在 `rag/db` 层原样保留，graph 只是把 `scope` 透传下去。

### C3 新评测类型 `intent` / `rewrite` ✅

- `intent-01`（现在几点了）：断言 `retrieval_skipped=true` + trace 含 `skipped` + `intent="time"` +
  零来源 + **intent 阶段未调 LLM** + 延迟 < 3000ms；
- `intent-02`（你好，你是谁呀）：断言同上（intent=chitchat）；
- `rewrite-01`（口语+称呼+情境，单遍 0.0514→0 来源）：断言**发生改写** + 最终有来源 +
  子集 2 轮 + 来源标题属目标材料（前缀匹配）+ 关键词；
- `rewrite-02`（学平险在哪里买，单遍 0.1008→0 来源）：同上。

**断言"能不能失败"的说明**：每个字段都是独立可失败的判据，且
①`intent` 类要求"零来源"**与**"检索确实被跳过"同时成立（防把检索失败当通过，坑 45）；
②`rewrite` 类要求"改写真的发生"**与**"最终召回达标"同时成立（改写没救回等于没改，坑 39）。
任何一条不成立即该用例 FAIL 并计入 `total_pass`，同时参与退出码。

### C4 矩阵硬指标 ✅ 3/8 → **8/8**

见 §一与 `docs/p4d/evidence/{before,after}/`。逐条改前改后见 §六。

### C5 三项书面评估 ✅

见 §五。

### C6 零回归 ⚠ 见 §七（**存在一处口径冲突，需裁决**）

### C7 冒烟与守恒 ✅ / C8 隔离 ✅

见 §七。

---

## 五、C5 三项书面评估

### 5.1 rerank 阈值取舍：**`RERANK_MIN_SCORE` 保持 0.3 不动**

评估过任务书列出的三个方向，结论与依据：

| 候选方案 | 实测/论证 | 结论 |
|---|---|---|
| **改"top1 与 top2 差值判定"** | 失败问句的 rerank 分布**整体压平**，差值比反而不可分：「术语+具体意图」top1/top2 = 0.1007/0.0998 = **1.009**；域外问句 0.0034/0.0012 = **2.8**。**域外的差值反而更大** → 该判据方向是反的 | ❌ 否决 |
| **"标题命中核心术语 → 保底候选"** | 能救回，但等于给"低分候选"开后门。而实测显示这些候选**在向量/融合层本来就排第 1~4 位**——说明问题不在"该不该放行低分候选"，而在"查询表述本身需要归一"。用归一修根因，不需要动门控 | ❌ 否决（治标） |
| **降低 `RERANK_MIN_SCORE`** | 归一后同一批问句的 rerank 峰值是 **0.968~0.992**，距 0.3 有 3 倍余量。**没有任何一条需要靠调阈值才能过** | ❌ 不需要 |
| **确定性术语展开（主力）** | 6/6 学平险问法：0.10~0.19 → **0.968~0.992**，`n_above` 0 → 3~4；域外问句**逐字不变**（无词典命中即不归一） | ✅ 采纳 |

**为什么保持 0.3 反而是正确的**：0.3 是在"查询已归一"的前提下的合理绝对门。实测给出明确的安全边界——
域外问句 top ≈ 0.003、归一后的域内问句 top ≈ 0.97，两者差两个数量级，0.3 落在中间且远离两侧。
**调低它只会减少拒答、增加幻觉风险，换不到任何本单需要的收益。**

`REWRITE_FLOOR`（原"rerank 峰值过低就不改写直接拒答"）**标为废弃**：
实测证实 rerank 绝对值不能当"库里有没有这个主题"的判据（正确候选只得 0.03~0.19），
改用"改写档位是否可用"来决定。

### 5.2 FTS 回退层停用词过滤：**采纳，但只过滤派生的 2-gram**

**第一次实现是空转的（如实记录）**：最初写法是"过滤后 `or {q}` 兜底"，实测 A/B
（`docs/p4d/evidence/after/fts_stopwords_ab.txt`）在 5 条查询上**逐条完全相同、零差异**——
因为 ① 短查询（≤4 字）词集只有整句本身；② `or {q}` 又把被过滤掉的整句加回来了。

**改正后的口径**：`整句永远保留，只过滤派生出的 2-gram`。理由：短查询的整句就是信号
（问"学校"本就应该能命中《普通高等学校学生管理规定》，过滤成空反而是退化），
而长查询里"我们/学校/这项"这类通用 2-gram 才是把无关块顶榜的原因。

**改正后的实测差异**（同一 corpus，开关 on/off）：

| 查询 | 过滤 开 | 过滤 关 |
|---|---|---|
| 请问我们学校这项事务应该怎么办理呢 | 国助学贷款 / 辅导员职业能力标准 / **离校请销假×2** / 学费缓缴（**教育部令 0 条**） | **教育部令×4** 霸榜 + 国助学贷款 1 条 |
| 我想知道学校对于这项工作的具体规定是什么 | 免研辅导员 / 困难生认定 / 辅导员队伍建设×3 | 免研辅导员 / **教育部令×2** / 困难生认定 / 辅导员队伍建设 |
| 我们学校这项规定是怎么说的 | 教育部令×4 + **纪律处分规定** 1 条 | 教育部令×5 |

→ 开启后"教育部令第41号"的霸榜显著减少，校本/办事类文档得以上浮。**影响面有界**：
该层仅在 FTS5 短语检索不可用时（短查询 / 零命中 / FTS 异常）才生效。默认开
（`NOVA_KEYWORD_STOPWORDS=0` 可关做 A/B）。

### 5.3 `qa-09`（离校请销假）处理结果：**已随根因一并解决**

诊断（本机实测）：

```
问句  本科生离校请假的手续是怎么规定的?
      top_score=0.9742  n_above=7  fused=8  src=5
      #1 0.9716 《西南交通大学学生离校请（销）假管理办法（试行）（西交校学生〔2018〕224号）》
      #2 0.9345 《西南交通大学学生离校请（销）假管理办法（试行）（西交校学生〔2018〕224号）》
```

`build_rewrite_plan("本科生离校请假的手续是怎么规定的?")` = **空**（无词典术语、无噪声前缀），
即**首轮原句就直接达标**——说明 `qa-09` 长期 R@k 0.0 与 F2 同源，属同一根因的不同表现，
随 F2 修复自然恢复。**未为它单独立规则、未改它的断言字段。** 最终结果见 §七集中评测。

---

## 六、矩阵逐条对照（改前 / 改后）

来源：`docs/p4d/evidence/before/variant_matrix_before.txt`（单遍语义，与 P4c 版本一致）
与 `docs/p4d/evidence/after/variant_matrix_after.txt`（双栏）。
消融：`docs/p4d/evidence/before/variant_matrix_singlepass_recheck.txt`（`NOVA_MAX_REWRITE=0`）。

| 措辞类型 | 单遍 rerank | 单遍命中 | 编排轮数 | 末次改写式 | 编排命中 | 判定 |
|---|---|---|---|---|---|---|
| 纯术语「学平险」 | 0.8875 | 2 | 1 | —（首轮即达标） | **2** | OK → OK |
| 术语+一般问「学校有学平险吗」 | 0.8456 | 2 | 1 | — | **2** | OK → OK |
| 术语+具体意图「学平险在哪里买」 | **0.1007** | **0** | 2 | `学平险 学生平安保险 大学生意外伤害保险` | **3** | 崩塌 → **OK** |
| 真实原句（学生口吻） | **0.1164** | **0** | 2 | `学平险 医保 学生平安保险 大学生意外伤害保险 大学生医疗保险 城乡居民基本医疗保险` | **2** | 崩塌 → **OK** |
| 背景前置倒装 | **0.0313** | **0** | 2 | （同上） | **2** | 崩塌 → **OK** |
| 口语加称呼情境 | **0.0526** | **0** | 2 | `学平险 学生平安保险 大学生意外伤害保险` | **3** | 崩塌 → **OK** |
| 书面正式名 | **0.1884** | **0** | 2 | `学生平安保险 学平险 大学生意外伤害保险` | **3** | 崩塌 → **OK** |
| 多子句书面全称 | 0.4114 | 1 | 2 | `学生平安保险 学平险 大学生意外伤害保险` | **3** | OK → OK |
| **合计** | **3/8** | | | | **8/8** | |

**消融对照**：`NOVA_MAX_REWRITE=0` → 编排列 **3/8**，与单遍列逐条一致 →
**提升 100% 来自改写重试**，无其它混杂因素。

**域外问句不在此矩阵的 8 条内，但已单独验证**：「我们学校有没有量子计算实验室开放日预约」
归一函数**逐字不变**（无词典命中），`build_rewrite_plan` 返回空 → 首轮不达标即拒答，
`mode=refuse`、`sources=0`（见 §七 `kb_hidden`/`refusal` 用例）。

---

## 七、集中验证（v2.0 = 47 用例）

**完整评测（单轮，`reports/eval_report_20260930_154710.json`，退出码 0）**

| 指标 | 实测 | 对照 v1.9 |
|---|---|---|
| 总通过 | **46/47（98%）** | 43/43 |
| Recall@k | **0.9412** | 持平 |
| 拒答准确率 | **1.0** | 持平 |
| 忠实度（llm） | 均值 **0.8824** / **中位 1.0** | v1.9 单轮均值 0.9412 |
| 隔离断言 | **ok**（40 个带会话用例全量核对） | ok |
| `intent` / `rewrite` | **2/2** / **2/2** | 新增 |
| `refusal_indomain` | **5/6** | 6/6 ← 口径冲突，见下 |

- `qa` 17/17、`refusal` 6/6、`permission_api` 4/4、`kb_hidden` 3/3、`scoped_qa` 3/3、
  P4b 四类新路径用例 4/4 —— **全部零回归**。
- **冒烟**：`SMOKE TEST PASSED`，退出码 0，`documents 65 → 65`；查库 **documents 65 / chunks 487 / folders 0**（自清理归零）。
- **忠实度下降不沉默**：均值 0.8824 由 `qa-12`、`qa-13` 两条 0.0 拉低，其余 15 条全 1.0（**中位数仍 1.0**）。
  与 `EVAL_BASELINE` 第十一节已裁决的 **judge 学段声明盲区**同源（P4a C8 强制注入的学段声明句不在
  `sources` 正文里 → judge 判为无据断言）。**未为指标删声明、未动 `evals/faithfulness.py`**，已记账。

**三项需裁决（详见 `EVAL_BASELINE.md` §十四，此处只列结论）**

1. ⚠ **`rind-02` 与 C4 硬指标互斥（最高优先级）**：`rind-02` 的问句就是矩阵要求的「学生原句」，
   评测期望**拒答**、硬指标要求**命中**。实测修复后该问句走 2 轮检索、top=0.981、4 条来源，
   答案**拒答了"现行规定"部分**（含「暂无」）、**未复述历史文件里的 95585**、并显式声明
   "2016 年文件属历史材料，不能作为现行规定依据" —— 但未给保卫处出口、且复述了用户自述的"计财处"，
   故按 `refusal_indomain` 判据 FAIL。**判断：该用例是基于 F2 缺陷的现场撰写的**（note 原文
   "F2 学生原句（sources=0 现场）"），其"库内无据"前提在 F2 修复后已不成立。
   **建议**把它迁移为 `qa` 型并重写断言（保留"95585 不得作现行"这条）。**未擅自执行**（`cases.json` 只准新增）。
2. **`qa-09` 的 R@k=0.0 是尺子缺陷**：KB 标题是「离校请（**销**）假」（全角括号），
   `expect_sources` 写的是半角「离校请销假」→ 子串永不相交。实测目标文档在来源**第 1、2 位**
   （0.9722/0.9347），检索完全正确。**这一条也解释了"R@k 长期 0.0"的历史遗留。**
   修法是 `compute_recall` 两侧归一括号/空白，但会使全套 R@k 0.9412 → 1.0（口径变更）→ **列出供裁决**。
3. **`cc-01` 埋点未改成"助手有据"**：摘要侧的修复（逐条标注来源 + 禁止升格）已完成且 `cc-01` PASS；
   把用例本身改成"助手有据"需要往 KB 加合成文档（语料 65→66，冲掉全部历史基线 + 撞冒烟 65→65 断言），
   或让评测装置伪造带 sources 的 assistant 轮（测的是装置不是产品）。**建议保留现状**。

**P4b 结转两条的落实情况**

- ①摘要来源标注：`COMPRESS_PROMPT` 新增第 6 条硬性要求——每条要点行尾必须标
  `[来源:助手有据]` 或 `[来源:用户自述·未经核实]`，同类并存按"用户自述"标，**禁止把用户自述升格为有据**。
  `cc-01` 本轮 PASS（4 个数字仍在摘要与答案中保留）。
- ②`history_gate_hit` 回指档**由"或"收紧为"且"**（原：含回指标记且「2-gram≥1 **或** 单字≥2」；
  现：**「2-gram≥1 **且** 单字≥2」**）。依据：改写上线后问句本身应能命中知识库，不应再靠更宽的回指档放行。
  回归证据：`mt-01`（多轮代词指代）仍 PASS 且 `history_gate=hit`，`rfol-01` / `hfp-01` 仍按确定性模板拒答（gate=miss）。

**硬要求 3 的专项断言（scope 不被旁路）**：`docs/p4d/probe_scope_passthrough.py` → **5/5 过**
（`docs/p4d/evidence/after/scope_passthrough.json`）：

| 断言 | 结果 |
|---|---|
| A 对照组：student 不带 scope 问「学平险出险后怎么报销？」 | 有 4 条来源（非空前置） |
| B 越权夹（counselor 私夹）→ HTTP 404 | `{"detail":"指定的知识库不存在或无权访问"}` |
| B2 不存在的夹（id=99999999）→ HTTP 404 | **响应体与 B 逐字节相同** |
| C 两者响应体相等 → 不泄露存在性 | ✅ |
| D 空夹 → 零来源 + `scope_empty=true`，明确提示"未做全库检索" | ✅ **无任何回落全库路径** |

---

## 八、复现命令

```bash
# 服务（评测温度 0）
cd novaagent && NO_PROXY="127.0.0.1,localhost" NOVAAGENT_EVAL_TEMPERATURE=0 \
  .venv/Scripts/python.exe -m uvicorn novaagent.main:app --port 8900

# 主指标：变体矩阵（双栏；含消融）
cd novaagent && NO_PROXY="127.0.0.1,localhost" \
  .venv/Scripts/python.exe ../evals/query_variant_matrix.py ../docs/p4d/evidence/after/variant_matrix_after.txt
cd novaagent && NO_PROXY="127.0.0.1,localhost" NOVA_MAX_REWRITE=0 \
  .venv/Scripts/python.exe ../evals/query_variant_matrix.py /tmp/ablation.txt   # 消融 → 3/8

# 逐层归因 / 阈值依据 / 延迟对照 / FTS A/B
cd novaagent && NO_PROXY="127.0.0.1,localhost" .venv/Scripts/python.exe ../evals/diag_retrieval.py
cd novaagent && NO_PROXY="127.0.0.1,localhost" .venv/Scripts/python.exe ../docs/p4d/probe_rerank_dist.py
cd novaagent && NO_PROXY="127.0.0.1,localhost" .venv/Scripts/python.exe ../docs/p4d/probe_normalize_variants.py
cd novaagent && NO_PROXY="127.0.0.1,localhost" .venv/Scripts/python.exe ../docs/p4d/probe_latency.py
cd novaagent && NO_PROXY="127.0.0.1,localhost" .venv/Scripts/python.exe ../docs/p4d/probe_fts_stopwords_ab.py

# 完整评测（v2.0 = 47 用例）+ 冒烟
cd novaagent && PYTHONIOENCODING=gbk NO_PROXY="127.0.0.1,localhost" .venv/Scripts/python.exe tests/smoke_test.py
cd . && PYTHONIOENCODING=gbk NO_PROXY="127.0.0.1,localhost" novaagent/.venv/Scripts/python.exe evals/run_evals.py
```

**环境开关**（全部可关，便于 Qoder 复现对照与消融）：

| 变量 | 默认 | 作用 |
|---|---|---|
| `NOVA_GRAPH_ENABLED` | 1 | 0 → 完全回退 pre-P4d 单遍检索路径 |
| `NOVA_MAX_REWRITE` | 2 | 改写档位上限；0 = 消融（退化为单遍） |
| `NOVA_GRADE_MIN_SCORE` / `NOVA_GRADE_MIN_ABOVE` | 0.3 / 2 | grade 判定 |
| `NOVA_INTENT_TIMEOUT_S` / `NOVA_REWRITE_TIMEOUT_S` | 8 / 10 | 意图/改写 LLM 超时 |
| `NOVA_KEYWORD_STOPWORDS` | 1 | 0 → 关闭 2-gram 停用词过滤（A/B 对照） |
