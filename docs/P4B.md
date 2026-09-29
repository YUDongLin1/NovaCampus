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
- **C4** ✅ `after/c4_compress_fidelity.json`:1400 条/191895 字符(119935 tok est)→ compressed=true;
  追问「报案电话与文件编号」在**零新来源**(followup_no_new_sources=true)下答出 **95585、417号**,
  再问金额答出 **448、25000**——4 个历史数字全部只能来自压缩摘要;出处消息 id 见
  `planted_sources`(组 40/80/120 → 对应消息 id);原文 1406 条永久保留。
- **C5** ✅ context 事件 + 占用条(实测「上下文 0%(0/85196 tok 估算)」新会话/切换后清空,
  事件驱动重建);切换/新建即 `abortInflight()`;实测中止后回到原会话消息数不变
  (1406→1406,连 user 消息都未落——中止发生在压缩阶段,`after/c5_switch_abort.json`)。
- **C6** ✅ `after/c2_c6_probe.json`:重命名/归档-恢复/默认列表过滤/分页(total+limit)/
  删除级联(conv_x 删 2 条消息+0 摘要,conv_y 计数不变)/**越权=不存在**(student 访问
  counselor 会话与 id=999999 的 404 响应体逐字节一致)。
- **C7** ✅ run_evals 每用例独立会话(不传 conversation_id → 自动新建),3 轮断言全过:
  「首用例 qa-01(会话 41,2 条)与末用例 rind-06(会话 72,2 条):message id 交集为空,
  首问逐字匹配」;断言结果写入报告 `eval_isolation` 字段。
- **C8** ✅ 3 轮 **36/36 ×3**、R@k **0.9412 ×3**、拒答 1.0、refusal_indomain 6/6、kb_hidden 3/3;
  忠实度 0.9706/0.9412/1.0(中位 0.9706)= v1.7 已裁决口径(C8 声明句 judge 盲区,低分项
  qa-07/02/11 轮换),**未做任何"优化"**。
- **C9** ✅ SMOKE TEST PASSED(GBK exit 0)、**documents 65→65、chunks 487→487**;
  会话/消息不入 KB(独立表)。
- **C10** ✅ 见 §五对账。

## 三、两处设计决策(需 Qoder 知悉/裁决)

1. **追问轮的门控分支(agent.py,refusal.py 未动)**:实测发现 P4a 硬门控与多轮存在结构性冲突——
   代词/省略式追问(「那它需要导师签字吗」)与纯历史回忆问句按字面检索必然为空或不足
   (诊断:Q2 alone top=0.0111;含上一问的增强查询 top=0.0964;好短语「报案电话和评审文件编号」
   也只有单块 0.371 < 0.9 放行线),一刀切硬拒会让 C2/C4 无法达成。
   处置:**首问(无历史)维持硬拒答不变**(refusal_indomain 6/6 证明评测路径未受影响);
   **追问轮(有历史)检索不达标 → 不硬拒**,注入代码拼装指令「知识库未检索到新来源;能从历史
   找到答案就基于历史回答并注明;历史与知识库都不足以回答就明确说明,不得编造」——模型按已注入
   的证据回答,域外追问实测仍如实拒答(「那今天成都的天气怎么样?」→ 建议查权威气象网站,
   无编造,见 after/c2_c6_probe.json `C_domain_out_followup`)。**若 Qoder 认为这削弱了 P4a 门控,
   备选方案是维持硬拒+牺牲 C2/C4,请裁决。**
2. **分块压缩(C4 实测修正)**:单次压缩 1029 条消息 → 摘要 1.3k 字,**埋点的 448/95585/417号
   全部丢失**(主题式归并吞掉细项,实测 `after/c4_compress_fidelity.json` 第一版)。改为每 40 条
   一块、`asyncio.gather` 并发压缩、逐块摘要拼接——保留率随块数提升,实测 4/4 数字可召回。
   代价:首次超预算轮有 N/40 次 LLM 调用(并发,实测数秒);摘要缓存(covered_until)避免重复压缩。

## 四、口径与限制(如实)

1. **token 为估算值**:`ceil(chars/1.6)` 中文经验值,未引 tokenizer(零依赖约束)。真实 token 数与
   估算可能有 ±20% 级偏差;预算的意义是"防失控注入"而非精确计费。
2. **预算口径**:budget=ctx*0.65 只约束"历史注入部分";system(检索上下文)与当前问题不计入
   ——system 随检索结果浮动,把三者一起算会使 budget 语义模糊。超长 system(检索 7 块×500 字
   ≈2.2k tok)远小于预算,风险可控。
3. **每轮全量重建上下文**:当前实现每次回答都重建历史/摘要(有 covered_until 缓存挡重复压缩),
   未做增量;千条级会话的注入构造为 O(n) 字符串操作,实测无感(P4b 范围内可接受)。
4. **旧扁平端点语义变更**(坑 30):`GET /api/conversations` 由"扁平最近消息"改为"会话列表";
   消费端 chat.js/loadHistory 已同步改造;`/api/conversations/{id}/messages` 承接分页消息。
5. **中止语义**:客户端 abort → SSE 连接断开 → 服务端生成器被取消 → 该轮**什么都不落库**
   (含 user 消息——构建上下文/压缩先于落库)。实测 conv 39 中止后总数 1406 不变。
   若产品上希望"问出去的问题即使切走也保留",需把 user 落库提前——本单按"中止=未发生"处理。

## 五、证据对账(C10)

文档引用的证据全集(`docs/p4b/evidence/`):
- `before/`:db_schema.txt(2588/5 列/无 conversations)、no_history_proof.txt(失守现场+复现命令)、
  api_calls.txt(20 调用点)、01~06 五路径截图/DOM(非空探针:42 链接/SSE 来源 0.9971/弹窗 3398 字)
- `after/`:c2_c6_probe.json(C2 指代成功+C6 级联对账+越权同表现+域外追问)、
  c4_compress_fidelity.json(119935 tok→compressed=true→4 数字召回+planted_sources 出处)、
  c5_sidebar_ctxbar.json/png、c5_switch_abort.json/png
- `git diff --name-status master...HEAD` 逐条对上;`git check-ignore -v` 无静默排除(本单证据无 .log)。

## 六、运行态与清理

- 评测/探针产生的会话:测试会话已删(C2/C4/C6 探针 6 个),评测会话已归档(7 个,数据保留);
  迁移历史会话 28 个保持 archived=1。counselor 侧栏默认 0 条(干净),开「显示归档」可见全部。
- 服务运行态:NovaAgent :8900(评测温度)供 Review。
