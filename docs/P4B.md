# P4b 会话与上下文管理:多轮 + 65% 压缩 + 左侧会话列表

> 分支 `task/P4b-conversation-context`,持棒 Zcode。规格见 `docs/TASKS.md` P4b 条目(C1~C10)。
> 定位:P4 反馈 A3 的落地——多轮对话、上下文占用实时检测、65% 预算压缩、左侧会话栏。

## 一、架构

```
POST /api/chat(/stream) body.conversation_id?
  └─ agent.chat_for / chat_stream_for(..., conversation_id)
       ├─ 会话解析: 传入→校验属主(404 同"不存在");缺省→自动新建(title=首问前 20 字)
       ├─ build_conversation_context(cid, model)        # C2/C3/C4
       │     hist = db.get_conversation_history(cid)     # 时间正序,含消息 id
       │     budget = MODEL_CANDIDATES.ctx * 0.65        # qwen-flash/plus: 131072*0.65=85196 tok
       │     used = Σ(ceil(chars/1.6)+4)                 # ⚠ 估算值(见 §四.1),非精确分词
       │     used ≤ budget → 完整注入(时间正序)
       │     used > budget → 较早消息分块压缩(每 40 条一块,asyncio.gather 并发,
       │        逐块保数字/日期/条款号/未决事项/对象代称)→ 摘要拼接注入 + 整体落
       │        conversation_summary(covered_until);压缩失败 → 降级截断(truncated=true)
       │        摘要缓存: covered_until ≥ 本次 older 末条 id → 复用,不重复压缩
       ├─ P4a 门控: 首问(无历史)检索不达标 → 硬拒答模板(不变);
       │   追问轮(有历史)检索不达标 → 不硬拒,注入代码拼装的「依据历史回答/如实说明
       │   未覆盖」指令(refusal.py 未改动,判定结果透传)——C2/C4 的前提,见 §三.1
       ├─ SSE 增事件 {"type":"context","used","budget","compressed","truncated",...}
       └─ 本问与答案落库到该会话(add_message 带 conversation_id)

会话栏(前端 conversations.js): 列表(默认未归档+「显示归档」开关)/新建/切换(加载
/api/conversations/{id}/messages)/重命名/归档/删除;切换即 AbortController 中止进行中 SSE;
占用条按 context 事件更新,切换/新建时清空。
```

## 二、C1~C10 逐条自评(证据对照见 §三)

- **C1** ✅ 三表落地 + `messages.conversation_id` 加列;迁移走 `db.py` 启动迁移代码(未脚本改库);
  **幂等**:第二次重启 messages 2594 / conversations 28 / no_cid 0 全不变;`persona_id` 留列。
- **C2** ✅ before:第二问「那它需要导师签字吗?」→ 无前文可指代(BEFORE no_history_proof.txt,
  实测被门控拒答);after(同名配对 `after/c2_c6_probe.json`):**「是的,研究生申请休学需要导师签字。」**
- **C3** ✅ ctx=131072、budget=85196;实测:C2 会话 used=48/budget=85196(未超,完整注入);
  C4 会话 119935 est tok > 预算 → 触发压缩。`ceil(chars/1.6)` 为**估算**,docs/P4B.md 本节标注。
- **C4** ✅ `after/c4_compress_fidelity_v2.json`(**必改 ④ 的可追溯新版**;v1 版
  `c4_compress_fidelity.json` 因"会话已删 + `planted_sources` 只记消息 id +
  `conversation_summary` 被清成 0 行"被 Review 判为**无法核对数字语义归属**,已弃用):
  - 规模:60 轮 ×3500 字种植 → 会话 **324** 共 **126 条消息**(user 63 / assistant 63);
    **会话保留不删**(`kept_for_review=true`),复核可直连查库/API 对账(见 §六)。
  - 触发:种植第 31 轮 used=66042(每轮 +2202)→ 第 **40** 轮超 budget **85196** 触发压缩:
    `compress_blocks=2`(= `ceil(N_older/40)`,`history_count=78`)、**compress_ms=4872**;
    压缩后 used=33306。共 22 个压缩轮,`compress_ms` 区间 **2585~8312**。
  - 保真:摘要 **854 字**,**4/4 埋点数字在摘要中且语义归属逐条正确**——
    `7341`=2026 年本科生学费标准、`958823`=学平险 24 小时报案电话、`17340`=国家奖学金
    专项特别奖额度、`川校发〔2026〕88号`=本专科生奖学金评审依据文件编号,
    **逐字对应埋点原文**(v1 那种"数字保住但归属被改写成另一字段"的存疑已消除)。
  - 召回:3 个追问(`turns_ctx` 第 61/62/63 轮)在 **`followup_no_new_sources=true` +
    `history_gate=hit`** 下 **4/4 数字全部出现在答案里**(`numbers_in_answers` 全 true)。
  - 证据自含:埋点数字**特意选 KB 里无碰撞的值**(7341/958823/17340/川校发〔2026〕88号),
    答案中的数字只可能来自历史;每条事实的埋点消息原文**内嵌 17 条**(id/role/content_head)
    + 摘要全文内嵌,`covered_until_message_id=8571`。
- **C5** ✅ context 事件 + 占用条(实测「上下文 0%(0/85196 tok 估算)」新会话/切换后清空,
  事件驱动重建);切换/新建即 `abortInflight()`;实测中止后回到原会话消息数不变
  (1406→1406,连 user 消息都未落——中止发生在压缩阶段,`after/c5_switch_abort.json`)。
- **C6** ✅ `after/c2_c6_probe.json`:重命名/归档-恢复/默认列表过滤/分页(total+limit)/
  删除级联(conv_x 删 2 条消息+0 摘要,conv_y 计数不变)/**越权=不存在**(student 访问
  counselor 会话与 id=999999 的 404 响应体逐字节一致)。
- **C7** ✅ run_evals 每用例独立会话(不传 conversation_id → 自动新建),3 轮断言全过:
  「首用例 qa-01(会话 41,2 条)与末用例 rind-06(会话 72,2 条):message id 交集为空,
  首问逐字匹配」;断言结果写入报告 `eval_isolation` 字段。
- **C8** ✅ 修复轮 3 轮(**v1.8 = 40 用例**口径,`reports/eval_report_20260930_{105755,111259,112603}.json`):
  **逐轮 39/40、39/40、40/40**(第 3 轮全过);R@k **0.9412 ×3**、拒答 **1.0 ×3**、
  refusal_indomain 6/6、kb_hidden 3/3;忠实度 0.9706/0.9706/0.9412(**中位 0.9706**)= v1.7 已裁决
  口径(C8 声明句 judge 盲区,低分项 qa-07/02/11 轮换),**未做任何"优化"**。
  失败项:`mt-01`(第 1 轮,门控 `history_gate=miss` → 触发①追加"回指命中"判据,r2/r3 均 hit 通过)、
  `qa-08`(第 2 轮,未命中「一周」,T10 时代即记录在案的关键词轮换波动)。
  ⚠ **口径已升级**:评测集 36 → 40(新增 `multiturn`/`context_compress`/`refusal_followup`/
  `history_false_premise` 各 1 条),**40/40 是正常满通过**,记账见 `docs/EVAL_BASELINE.md` 第十二节。
- **C9** ✅ SMOKE TEST PASSED(GBK exit 0)、**documents 65→65、chunks 487→487**;
  会话/消息不入 KB(独立表)。
- **C10** ✅ 见 §五对账。

## 三、两处设计决策(需 Qoder 知悉/裁决)

1. **追问轮的门控分支(P4b-fix ① 按 Review 裁决重做,判定回到代码)**:原实现
   `if do_refuse and hist_msgs: do_refuse = False` 把无据判定从代码退回给一句 prompt,
   被 Review 实测击穿(假前提洗白成建议、出口自拟"游泳馆管理办公室")。修复后:
   - **可采信历史证据池(admissible)只有两类**:a) 此前 **assistant 且带有效 sources**
     的回答(`messages.sources_json` 快照,`db.py` 迁移幂等加列);b) 会话压缩摘要。
     **user 消息与拒答模板(无来源)一律不进池**——用户自述的金额/缴费渠道/办理地点
     没有任何通道被当作事实依据;模板回答不进池,故"turn1 假前提→硬拒"之后追问的
     可采信池为空,必然落到确定性拒答。
   - **判据(确定性,零新依赖)**:问句与每条可采信文本做去标点字符 n-gram 覆盖匹配,
     命中任一即放行(`agent.history_gate_hit`,阈值常量
     `_GATE_MIN_BIGRAM_COVER=0.15/_GATE_MIN_UNIGRAM_COVER=0.30`):
     a) **细节命中**:2-gram 不同命中 ≥2 且覆盖率 ≥0.15(显式主题追问,如摘要数字回忆);
     b) **回指命中**:问句含回指/承接标记(它/该/上述/此/其/这个/那些…)且(2-gram ≥1
        或单字 ≥2)——回指问句离开上下文即语义不完整,须有先行语才可答;
     c) **主题命中**:2-gram ≥1 且单字 ≥3 且单字覆盖率 ≥0.30(显式主题、无回指标记)。
     b) 是评测第 1 轮实测后追加的:同一问句在 temp=0 下出现「需提交/应当提交」两种
     答案措辞,单字命中在 2~3 之间波动,纯覆盖率阈值无法同时稳住"代词指代命中"
     与"游泳馆类搭车问句拒绝"(两者字面统计几乎重合);回指结构是两者的本质差异。
   - **命中** → 注入 `HISTORY_GATE_NOTE`(代码拼装):只准基于带来源的助手回答与摘要
     作答并注明「依据此前对话」;用户自述内容不得作为事实复述,确需提及必须显式标注
     「用户自述、未经核实」;建议出口只能用知识库/模板中出现过的部门名。
   - **未命中(含池为空)** → 维持硬拒,走 `refusal.build_refusal` 确定性模板,
     出口一律 `contacts.json` 白名单,禁止自拟。
   - **首问(无历史)硬拒路径零改动**(`refusal_indomain` 6/6 为既有证明)。
   - **标定与边际**:代词追问 3/9=0.333 命中;游泳馆 0.222 / 天气 0 / 空池 拒绝
     (`followup_gate_v2.json` 六场景全过)。已知边际:校医院门诊类问句(4/13=0.308)
     会走历史提示路径——但池内并无该主题内容,模型按注入约定仍应如实说明未覆盖,
     不存在编造/洗白通道(`followup_gate_v2.json` F 场景实测即此表现)。
2. **分块压缩(C4 实测修正)**:单次压缩 1029 条消息 → 摘要 1.3k 字,埋点数字全部丢失;
   改为每 40 条一块、`asyncio.gather` 并发压缩、逐块摘要拼接。**块数与调用次数关系式**:
   块数 = `ceil(N_older/40)`,LLM 调用次数 = 块数(一次性并发)。**首超预算轮实测**
   (评测 cc-01,报告 `reports/eval_report_*.json` turn_contexts 与 v2 探针):
   触发于种植第 40 轮,N_older=48 → 2 块,compress_ms=**4495**;增长期后续轮因 older
   边界随新消息后移、covered_until 缓存未命中而逐轮重压缩(2 块,4403~5434ms,实测
   4/40/41/42/43 轮),这是"摘要+原文可回溯"口径下的已知代价;摘要缓存仅在边界不动时
   复用(§四.3 的说法据此修正)。

## 四、口径与限制(如实)

1. **token 为估算值**:`ceil(chars/1.6)` 中文经验值,未引 tokenizer(零依赖约束)。真实 token 数与
   估算可能有 ±20% 级偏差;预算的意义是"防失控注入"而非精确计费。
2. **预算口径**:budget=ctx*0.65 只约束"历史注入部分";system(检索上下文)与当前问题不计入
   ——system 随检索结果浮动,把三者一起算会使 budget 语义模糊。超长 system(检索 7 块×500 字
   ≈2.2k tok)远小于预算,风险可控。
3. **每轮全量重建上下文**:当前实现每次回答都重建历史/摘要;covered_until 缓存只在
   older 边界不动时复用——**会话增长期每轮边界后移,会逐轮重压缩**(cc-01 实测
   4403~5434ms/2 块,见 §三.2),千条级会话的注入构造为 O(n) 字符串操作。增量压缩
   (只压新增段)留后续优化。
4. **旧扁平端点语义变更**(坑 30):`GET /api/conversations` 由"扁平最近消息"改为"会话列表";
   消费端 chat.js/loadHistory 已同步改造;`/api/conversations/{id}/messages` 承接分页消息。
5. **中止语义(P4b-fix ⑤:代码保证,口径以实测为准——abort 会回滚本轮 user 消息,
   不再残留"1 条无回复的 user 消息")**:
   客户端 abort → SSE 连接断开 → 服务端生成器被取消。**实测口径**(证据
   `after/stream_abort_v2.json`,v2 探针):
   - **真 token 流阶段中止**(读满 3 个 chunk 后切断)→ `roles_after=[]`、
     `nothing_persisted=true`,**该会话 0 条**;
   - **完整流对照** → `roles_after=["user","assistant"]`,正常落 2 条。
   即:**任何阶段中止,本轮 user 消息都不会留在会话里**。两段机制、同一结果:
   - **构建/压缩阶段**:user 消息在 `build_conversation_context` + 检索之后才落库
     (`agent.py` 的 `chat_for`/`chat_stream_for`),中止发生在落库之前 → 天然无痕;
   - **真 token 流阶段**:user 消息已落库 → `except (asyncio.CancelledError, GeneratorExit)`
     分支执行 `db.delete_message(user_msg_id)` **回滚本轮 user 消息**;assistant 已落库
     则视为完整轮次不回滚;回滚失败只 `logger.warning`,不吞取消异常。
   - 前端:切换即 `abortInflight()` + 重新拉取会话消息,悬空轮次随服务端回滚自然消失
     (注释已同步)。
   - ⚠ 口径提示:本单口径是"**中止 = 该轮未发生**";若产品要求"问出去就保留",需产品裁决
     后改落库时序(把 user 落库提到构建之前并改保留语义),不是本单默认行为。

## 五、证据对账(C10)

文档引用的证据全集(`docs/p4b/evidence/`):
- `before/`:db_schema.txt(2588/5 列/无 conversations)、no_history_proof.txt(失守现场+复现命令)、
  api_calls.txt(20 调用点)、01~06 五路径截图/DOM(非空探针:42 链接/SSE 来源 0.9971/弹窗 3398 字)
- `after/`:c2_c6_probe.json(C2 指代成功+C6 级联对账+越权同表现+域外追问)、
  **c4_compress_fidelity_v2.json(④ 必改后的可追溯新版:60 轮种植→会话 324/126 条消息、
  第 40 轮触发压缩 blocks=2/4872ms、摘要 854 字 4/4 数字且语义归属逐条正确、3 个追问
  gate=hit 下 4/4 召回、埋点原文×17 条与摘要全文内嵌、会话保留可查库对账)**、
  c4_compress_fidelity.json(v1 旧版,已被 Review 判为不可核对归属,**仅作对照留存**)、
  c5_sidebar_ctxbar.json/png、c5_switch_abort.json/png、
  **stream_abort_v2.json(⑤ 实测:真 token 流阶段读满 3 chunk 切断 → 会话 0 条;
  完整流 → 2 条)**、followup_gate_v2.json(① 六场景门控标定)
- `git diff --name-status master...HEAD` 逐条对上;`git check-ignore -v` 无静默排除(本单证据无 .log)。

## 六、运行态与清理

- 评测/探针产生的会话:测试会话已删(C2/C4/C6 探针 6 个),评测会话已归档(7 个,数据保留);
  迁移历史会话 28 个保持 archived=1。counselor 侧栏默认 0 条(干净),开「显示归档」可见全部。
- **④ 例外(按 Review 必改 4 要求保留)**:C4 v2 探针会话 **id=324**(`archived=0`、126 条消息、
  `conversation_summary` 1 行 `covered_until_message_id=8571`)**保留到 Review 通过再清理**——
  复核可直接对账:
  ```bash
  cd novaagent && ./.venv/Scripts/python.exe -c "
  import sqlite3; db=sqlite3.connect('file:data/agent.db?mode=ro', uri=True)
  print(db.execute('SELECT COUNT(*) FROM messages WHERE conversation_id=324').fetchone())
  print(db.execute('SELECT covered_until_message_id, length(summary_text) FROM conversation_summary WHERE conversation_id=324').fetchone())"
  ```
  或 `GET /api/conversations/324/messages`(student token)。**清理时请连同本文件 §五 的引用一起更新。**
- 服务运行态:NovaAgent :8900(评测温度)供 Review。
