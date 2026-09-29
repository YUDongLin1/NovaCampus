# P4a 内容质量与 KB 卫生:拒答硬门控 + 导入质量门 + 语料复核

> 分支 `task/P4a-answer-quality`,持棒 Zcode。规格见 `docs/TASKS.md` P4a 条目(C0~C10)。
> 头号目标:把「知识库里没有,模型照样答还标引用」从**代码层**堵死(不加第 10 条 prompt 规则)。

## 一、修复架构

```
/api/chat(/stream)
  └─ agent.chat_for / chat_stream_for
       ├─ rag.search_with_quality()          # P4a 改:返回 (sources, quality 信号)
       │     quality = {top_score(原始rerank峰值), n_above_threshold(达标数), rerank_available}
       ├─ refusal.should_refuse(sources, quality)   # C1 硬门控(代码级判定)
       │     空 来源 → 拒 | top<0.3 → 拒 | 达标数<2 且 top<0.9 → 拒(实测修正,见 §三.1)
       ├─ [拒答] refusal.build_refusal()     # 确定性模板,不经 LLM(实测 ~1s vs 修复前 5~6.5s)
       │     = 暂无 + 缺口说明 + contacts.json 出口(按 scope_keywords 命中 1~3 条) + 需补充信息
       │     流式路径: 模板整体作为一次 delta;非流式: 直接返回 answer, sources=[]
       └─ [回答] LLM 生成后 → refusal.strip_invalid_refs()  # C2 [n] 越界硬剥离
             越界 → 剥离 + record_fabricated_ref() 写 evals/badcases.json(fabricated_ref 案)
             流式路径: _StreamRefFilter 逐 delta 过滤(缓冲疑似 "[12" 片段,补全后判定)
       └─ refusal.learn_stage_note()         # C8 学段声明(prompt 组装,不改 SYSTEM_PROMPT 文案)
             来源含「本科生」专项办法且未见研究生办法 → 注入声明要求(F3 场景)
```

导入侧(main.py):`kb_import_url` 抓取前拦禁抓 URL 与同 URL 重复 → 抓取后 `clean_body()`(原型移植)
→ `quality_gate_reject()`(kb_upload 共用,纯函数)→ 拒绝返回 `{code, reason, hint}`。

## 二、C0~C10 完成标准自评

- **C0** ✅ 修复前现场:`docs/p4/evidence/before_refusal_gate.txt`(commit e332ddb)。如实记录:F1 原文
  在语料入库后**已可无据性风险解除**(sources=2,[1][2] 合法)——C0 规格写于语料入库前,该漂移已注明;
  仍活的现场是 F1 短问/F2 原句(sources=0 时仍走 LLM 自由拒答,5.1~6.5s,且 F2 错指"计财处"出口)。
  历史现场(源 s=0+自有知识成篇+虚构[1])见 `docs/p4/evidence/feedback_probe.txt`(Qoder 存证)。
- **C1** ✅ `refusal.py should_refuse` + agent 双路径接入;确定性模板不经 LLM。
- **C2** ✅ `strip_invalid_refs` + `record_fabricated_ref`(badcases.json 机制,只增不删,历史上限 50);
  流式路径 `_StreamRefFilter` 逐段过滤;单测 U1(含「原文带 [1]」/〔2025〕/[2026] 不误伤)。
- **C3** ✅ `novaagent/novaagent/data/contacts.json` 7 条(≥6),全部官网原文
  (doc_id 113 校医院联系方式 / 114 学平险理赔须知 / lxwm 联系我们);含**保卫处**(学平险归口,
  非计财处)与校医院医保办;拒答时按 scope_keywords 命中数取 1~3 条。
  ⚠ 路径偏差:规格写 `novaagent/data/`——该目录被 .gitignore `data/` 规则整体忽略且 .gitignore
  不在本单白名单,故放包内 `novaagent/novaagent/data/`(`git add -f` 入库),refusal.py 两处兼容查找。
- **C4** ✅ `quality_gate_reject`(main.py,两端点共用):禁抓 URL(抓取前拦,不发请求)/登录类标题/
  正文<200 字/登录页特征≥2/**口令四样式**(①用户名/口令斜杠式 ②演示账号 ③admin123|counselor123|
  student123 字面量 ④密码均为——P3b Review 教训)/手机号/身份证(带出生日期合法性校验,防业务编号
  误报)/名单特征;拒绝返回 `{code, reason, hint}`。回归:重放 cwc.swjtu.edu.cn 与 127.0.0.1:8900
  必被拦(smoke 16a API 级 + U6 纯函数级)。
- **C5** ✅ smoke_test.py:上传 doc_id 全量登记,结束时删除并**断言 documents 计数守恒**(实测
  65→65);网页导入用例改**本地 fixture**(http.server 随机端口),自家前端首页改**回归用例**(必须被拦);
  `--cleanup` 清历史残留(实测清掉本单调试期残留 2 篇);`evals/kb_doctor.py` 输出
  `reports/kb_doctor_<ts>.json`(运行时产物,不入库——reports/ 在本单禁改清单),证据副本
  `docs/p4/evidence/kb_doctor_clean.json`:**danger=0**(重复标题/登录页/口令/孤儿分块/FTS 均无)。
- **C6** ✅ kb_doctor 复核 6 篇新语料(doc 110~115):无超短正文/无个人信息/chunks_fts MATCH 抽样正常;
  `gate()/DENY_URLS/clean_body()` 已移植进 main.py(运行时拦截);F1/F2/F3 复跑留痕
  `docs/p4/evidence/after_refusal_gate.txt`。红线遵守:未抓取任何页面、未用真实学工账号、未把
  LLM 摘要当语料。
- **C7** ✅ cases.json → **v1.7,36 条**(qa 17 / refusal 6 / refusal_indomain 6 / permission 4 /
  kb_hidden 3)。refusal_indomain 6 条含 F1 短问与 F2 原句等域内无据题;
  `judge_refusal_indomain` 断言:拒答语 + 无越界 [n] + expect_contact 出口 + 无 expect_absent_keywords;
  qa 3 条 = F1 原文/学平险短问/F3 短问(expect_keywords 取官网原文:「暂停」「学平险」「不可兼得」)。
  **口径说明**:C7 写"F1 原文进 refusal_indomain"——实测 F1 原文在语料入库后 sources=2(证据
  before_refusal_gate.txt),故 F1 原文进 **qa**、其同主题短问进 refusal_indomain,与"术语短问+口语
  长问配对建案"规则一致,漂移缘由已注明。
- **C8** ✅ `learn_stage_note`(代码级 prompt 组装):来源为本科生专项办法且未见研究生办法 → 注入
  声明要求;qa-17(研究生问荣誉称号)实测回答开头即「以下依据本科生办法…研究生…未在当前知识库中
  覆盖」;F3 原句实测同样声明。注意:该机制对 qa-02 也会生效(库内奖助学金办法本身即本科生办法),
  语义正确,见 §三.3 的 judge 影响说明。
- **C9** ✅ 拒答路径不经 LLM:**5153~6526ms → 912~1752ms(约 3.6~7 倍)**;正常问答 F1 原文
  13237ms → 5826~6784ms(不劣化)。出处:修复前 `before_refusal_gate.txt` 耗时字段 vs 修复后
  `after_refusal_gate.txt` 耗时字段(温度口径不同:前=产品 0.3,后=评测 0,已在文件头注明)。
- **C10** ✅ F2 原句 → 硬门控拒答 + **保卫处**出口(87600392/66366392,非计财处);
  `evals/query_variant_matrix.py` 复跑:`query_variant_matrix_after_p4a.txt` — **3/8 命中,与修复前
  一致**(检索层未动,符合"本单不修检索"边界)。**仍失败措辞清单(交 P4d 的输入,非本单失分)**:
  ①「学平险在哪里买」rerank 0.1007;② F2 学生原句 0.1136;③ 背景前置倒装 0.0311;
  ④ 口语加称呼情境 0.0528;⑤ 书面正式名「学生平安保险是否由学校统一办理?」0.0199。
  均为 rerank 对"意图与分块字面不严格对应"给极低分 + 一刀切阈值无回退所致(P4d M6 根治)。

## 三、关键数字 → 文件 → 字段对照

| # | 数字/事实 | 文件 | 字段/位置 |
|---|---|---|---|
| 1 | 修复前拒答耗时 5153/6526ms、F1 原文 13237ms | `docs/p4/evidence/before_refusal_gate.txt` | 各块「耗时: NNNN ms」行 |
| 2 | 修复后拒答 912/1007ms(smoke 外探针 1277~1752ms) | `after_refusal_gate.txt` / `demo` 同款 | 同上 |
| 3 | F2 出口=保卫处 87600392/66366392 | `after_refusal_gate.txt` | F2 块答案正文「保卫处(学平险/意外伤害保险归口)」 |
| 4 | F3/C8 声明「以下依据本科生办法」 | `after_refusal_gate.txt` | F3 块答案首句;qa-17 三轮 PASS |
| 5 | 评测 3 轮全 36/36、R@k 0.9412×3 | `reports/eval_report_20260929_{163526,163808,164042}.json` | `total_pass`/`summary.recall_at_k_avg` |
| 6 | 忠实度均值 0.9706/0.9412/1.0(中位 0.9706) | 同上 | `summary.faithfulness_avg`;低分项 qa-02(2/5 轮)、qa-17(1/5 轮) |
| 7 | KB 守恒 65→65、自清理 4 篇 | smoke 输出(回执引用) | `[18] 自清理 OK…KB 计数守恒: 65 → 65` |
| 8 | kb_doctor danger=0 warn=2 | `docs/p4/evidence/kb_doctor_clean.json` | `summary.danger`(warn=2 均为 EVAL 种子短正文,预期内) |
| 9 | 变体矩阵 3/8 | `docs/p4/evidence/query_variant_matrix_after_p4a.txt` | `[SUM]` 行 |
| 10 | 评测集 v1.7=36 条 | `evals/cases.json` | `version`/`cases[].type` 计数 |
| 11 | **C2 机制实弹验证:5 轮评测剥离 12 次真实越界引用** | `evals/badcases.json` | `fabricated_ref.history[]`:qa-01 同题 `[3]`(sources=1)×6、请假超7天 `[3]`(sources=2)×5、本科生离校请假 `[7,8,9]`(sources=5)×1——即 §2.3「句末仍带 [n]」现象在 v1.6 时代每轮都在发生,无人查证;剥离后关键词断言仍全 PASS,服务端 WARNING 日志同步留痕 |

## 四、已知限制与说明(如实)

1. **C1 门控的实测修正(对规格的偏离,已验证必要)**:规格字面「n_above_threshold<2 → 拒答」会把
   qa-01 误杀——实测其检索仅 1 块达标(0.9952,EVAL 种子),其余全 <0.27(贷款类噪声)。修正为
   「达标数<2 且 top_score<0.9(config.REFUSAL_SINGLE_SOURCE_MIN_SCORE)才拒」:单来源极强置信放行,
   单来源低分仍拒。修正前 2 轮实测 qa-01 稳定 sources=0(报告 20260929_162906/163123),修正后 5 轮
   全 36/36。若 Qoder 坚持字面规格,qa-01 将结构性失败,请裁决。
2. **忠实度中位 0.9706 vs v1.6 的 1.0——judge 盲区,非无据作答**:C8 学段声明句是系统注入的
   "关于检索结果的事实"(「知识库未覆盖研究生办法」),它不在 sources 正文里,而
   `evals/faithfulness.py`(禁改)只对 sources 拼上下文 → 声明句被判"缺乏依据"扣 0.5。
   低分项:qa-02(2/5 轮;其检索材料本身即《本科生奖助学金评审管理办法》,注入语义正确)、
   qa-17(1/5 轮)。T10 时代 qa-02 即有 0.5 倾向(`reports/eval_report_2026092*_15*.json`),
   非本单引入。**建议 P4d**:judge 的上下文拼装纳入系统注入说明,或 faithfulness 对"声明类句子"
   白名单——需先由 Qoder 裁决口径。
3. **qa-02 的学段注入是 C8 机制的正确副作用**:库内《本科生奖助学金评审管理办法》即该问题唯一
   材料,研究生提问时声明学段语义正确;qa-02 关键词断言仍 PASS。
4. **contacts.json 路径**:规格路径被 gitignore 吞,放包内并 `git add -f`(见 C3 自评)。
5. **kb_doctor 报告写 reports/**(规格指定),reports/ 在禁改清单 → 报告为运行时产物不入库,
   证据副本存 `docs/p4/evidence/kb_doctor_clean.json`。
6. **fabricated_ref badcase 为运行时写入**:extract_badcases.py 合并逻辑只增不删,该案可与之共存;
   本单未跑 extract(验收命令不含)。
7. **降级路径**(rerank 服务不可用)不做分数门控——阈值语义属 rerank 分,降级时仅按"来源为空"拒。
