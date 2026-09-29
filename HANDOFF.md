# HANDOFF · NovaCampus 会话交接文档

> 初版 2026-09-28(Zcode,T10 期);2026-09-28 由 Qoder 更新到 P3a 合并后状态;**2026-09-29 由 Qoder 更新:P3b 已下发(持棒 Zcode)、P4 用户反馈包已立项设计、KB 清理 17 篇、基线升 v1.5**。供**零上下文新会话**接续。读完本文 + `docs/COLLAB.md` + `docs/TASKS.md` 即可接手。
> **配合 `docs/NEXT_SESSION_PROMPT.md` 使用**:那份给"你是谁、先做什么"的开场指令,本文给事实与教训。
> 你(Zcode/实现者)与 Qoder(负责人/Review)按 `docs/COLLAB.md` 协同:**单一事实源 TASKS.md、串行持棒、白名单禁改、Review 闸门**。


---

## 一、我们在做什么

**NovaCampus(智枢 Agent)**——用户的简历项目(用户=某高校辅导员，个人项目)。三轨:
- **NovaAgent**(自研,`novaagent/`):FastAPI + SQLite 的校园智能体,三角色 RBAC(学生/辅导员/管理员)、RAG 问答(混合检索+rerank+拒答阈值)、流式 SSE、会话持久化、周报助手(经 MCP 调用)。
- **WeKnora**(腾讯开源,`weknora/`,git 忽略):评测基线,已部署但不开发。
- **P3 AIOps**(`sims/` + `mcp/aiops/`,进行中):模拟校园系统 + 故障注入 + Prometheus/Grafana,让 Agent 能"收到告警→查指标→定位根因→出中文诊断报告"。**这是简历第二亮点。**

**协作模式**:Qoder 下发任务规格到 `docs/TASKS.md` → Zcode 在 `task/T*` 分支实现 → 自测 → 回填交接回执 → IN_REVIEW 等 Qoder Review → 合并。**同一时刻只有持棒者能写工作区。**

## ⚠ 硬约束(违反即事故,不可协商)

1. **真实学工数据严禁入库/外发**:`E:\<internal-affairs-dir>\` 下的 Tier B 材料(一人一策帮扶台账、含真实姓名的申报书/发言稿/推荐表)**永不进 corpus、永不提交、永不上传**任何外部服务/知识库/网络。只允许已脱敏的 Tier A 政策文件入库。
2. **`corpus/raw/affairs/`、`corpus/clean/affairs/` 已 gitignore**(第三方「萌哥说案例」):只本地导入 KB 撑 demo,**不得提交、不得公开发布**。
3. **写权限**:TASKS.md 头部"当前持棒"不是你 → 只读不写。任务白名单外的文件(尤其 `novaagent/**`)一律不碰。
4. **不要动** `C:/Users/<user>/WorkBuddy/Worktrees/NovaCampus/`(用户另开的 workbuddy 工作树)和别人的未合并分支。
5. **操作用户真实学工账号**(CDP/浏览器登录爬取)有封号风险 → 动手前必须先给"温馨提示"并等用户确认。
6. 演示口令固定 `admin123 / counselor123 / student123`;Grafana 是 `admin/simsadmin123`。**均为本地演示用,不得用于任何真实系统。**

## 二、必读文件(按序)

1. `docs/COLLAB.md` —— 协同规约(持棒/白名单/Review 闸门)
2. `docs/TASKS.md` —— 任务板(唯一事实源;含 T1-T10 + P3a 全部条目与回执、Review 结论)
3. `docs/EVAL_BASELINE.md` —— 评测基线演进(v1.0→**v1.5**;第九节记 KB 清理与拒答门控盲区)
4. `docs/BADCASES.md` —— bad case 档案机制
5. `docs/P3A.md` —— **P3 地基**:模拟系统架构/指标清单/故障注入原理/验收证据(§七是 Review 修正记录)
6. `corpus/MANIFEST.md` —— 语料合规分层(Tier A/B;**严禁引入 E:\<internal-affairs-dir>\ 的 Tier B 真实数据**)
7. `docs/P4.md` —— **用户反馈驱动的产品升级设计**(M1~M9 模块划分、实测证据、排期、合规红线);任务规格在 `docs/TASKS.md` 的 P4a~P4g
8. `docs/p4/corpus-candidates.md` —— 医保/学平险/校医院/计财处语料候选(**已获批准并入库**,含禁抓清单)
9. `docs/CASE_STUDY.md` —— **简历叙事素材**:指标 1.0 之下的三类真实失败(无据作答+虚构引用 / rerank 措辞崩塌 3-8 命中 / 测试污染生产库)、归因过程、含我自己一次过早归因被证伪的记录与复现命令


## 三、运行状态(接手先验)

| 项 | 值 |
|----|----|
| 仓库 | `E:\AILearn\NovaCampus`,git 身份 YUDongLin1 |
| NovaAgent | `uvicorn novaagent.main:app --port 8900`(在 novaagent/ 下跑,venv=`novaagent/.venv`) |
| weekly MCP | docker 容器(18080)或本地 `python mcp/weekly/server.py`;NovaAgent 启动时会连它,**连不上则服务起不来**(lifespan 致命) |
| **aiops MCP(P3b 新增)** | **宿主机 venv 形态**:`mcp/aiops/.venv`,起 `python mcp/aiops/server.py` → `http://127.0.0.1:18081/{sse,mcp}`,7 个只读工具;依赖 Prometheus `:9090` + 宿主 docker CLI 取 `docker logs`(**容器内无 docker CLI、无 /var/run/docker.sock,实测已定论**)。**NovaAgent 尚未接入它——那是 P3c**(将以 `AIOPS_MCP_URL` 对齐 `WEEKLY_MCP_URL` 模式) |
| WeKnora | docker compose,http://localhost(评测基线,不动它) |
| 演示账号 | admin / counselor / student,密码均 xxx123 |
| DB | `novaagent/data/agent.db`(SQLite);**2026-09-29 KB 清理+语料增补后 documents=65 / chunks=487**(清理前 76/486,备份 `agent.db.bak-20260929-104207`);WeKnora 库 `novaagent/data/` 无关 |
| **评测基线** | **v1.7(2026-09-29 P4a 后)**:**36 用例**(原 26 + qa 3 + `refusal_indomain` 6 新类型 + kb_hidden 等)、R@k **0.9412**、拒答 1.0、忠实度中位 0.9706。**8 轮中 7 轮 36/36**,唯一失败为 `qa-08` 关键词「一周」轮换波动(R@k/忠实度均 1.0,T10 时代即有)——引用时**勿写成无条件 36/36**。忠实度较 v1.6 的 1.0 略降**已归因到 C8 强制的"学段声明句"不在 sources 正文而被 judge 扣分**(非能力退化,见 EVAL_BASELINE 第十一节)。**对照一律用 v1.7**,历史 0.8846/0.9615/0.9231 分别对应脏库 76 篇/清理后 59 篇/增补后 65 篇 26 用例口径 |
| 模型 | 百炼 qwen-flash(内置默认)+ qwen3.7-plus(UI 配),key 在 `novaagent/.env` 与 `weknora/.env`(均 gitignore) |
| **P3a 模拟栈** | `docker compose -f docker-compose.sims.yml up -d --build` → jiaowu :9101 / ykt :9102 / Prometheus :9090 / Grafana :3000(admin/simsadmin123,匿名 Viewer 也开) |
| ⚠️ Docker Desktop | **不常驻!** 2026-09-28 Review 时守护进程已停(pipe 不存在、4 端口全不可达)。任何 sims/P3b 工作**第一步先 `docker ps` 确认 daemon 活着**,别在 daemon 挂的情况下"验证"任何东西 |
| ⚠️ sims 依赖 | `prometheus_client`+`psutil` 只在 anaconda base 有、`fastapi`+`uvicorn` 只在 `novaagent/.venv` 有 → **宿主机直跑 sims 目前起不来**,须建 `sims/.venv` 装 `sims/requirements.txt`(未装,别静默改别人的 venv) |


## 四、任务台账(截至交接)

| 任务 | 内容 | 状态 |
|------|------|------|
| T1 | 语料库 75 篇(政策 32+事务 20+运维 2)+脱敏+导入 | ✅ DONE 合并 `ec1588e` |
| T2 | bad case 档案机制(extract_badcases.py) | ✅ DONE 合并 `58615f9` |
| T3 | 前端校园化(水墨主题/登录页/三角色 UI) | ✅ DONE 合并 `2f94a65` |
| T4 | 评测深化(Recall@k/忠实度 LLM-judge/26 用例) | ✅ DONE 合并 `ba3f031` |
| T5 | 评测闭环整包(检索调优/对比/看板) | ✅ DONE 合并 `a15281e` |
| T6 | FTS5 检索层 + 措辞加固(any-of) | ✅ DONE 合并 `170ee8d` |
| T8+T9 | 流式 SSE + 会话持久化 | ✅ DONE 合并 `4f2a6ce` |
| T10 | 检索相关性根治(FTS blend+TOP_K7)+生成侧规则9+评测温度开关 | ✅ DONE 合并 `1328168` |
| **P3a** | **模拟校园系统 + 故障注入 + Prometheus/Grafana 监控栈** | **✅ DONE 合并 `b8245c2`** |
| **P3b** | **AIOps MCP Server(mcp/aiops)** | **✅ DONE —— Review 通过并合并 master `2234fc8`(2026-09-29),附 1 项引用链修正** |
| **P4a** | **内容质量与 KB 卫生(拒答硬门控 + 导入质量门 + 语料复核)** | **✅ DONE —— Review 通过并合并 master `827e1ae`(2026-09-29),两处裁决批准,附 1 项规格缺口** |
| **P4a-1** | **质量门补口:识别导航/索引型页面** | **✅ DONE —— Review 通过并合并 master `5399a5e`(2026-09-29),附带修复我上轮合并的 RE_IDCARD 保单号误伤** |
| **P4b-0** | **前端模块化拆分(index.html 887 行,纯重构)** | **🟣 IN_REVIEW —— ⚠ 实现者是 Qoder 本人(Zcode 额度用尽后代做),未合并 master,待用户或 Zcode 独立复核** |
| P3c / P3d | NovaAgent 诊断链 / 注入→自动定位录屏 | 📋 排队(依赖前序) |
| **P4a~P4g**(含 **P4b-0** 前端拆分) | **用户反馈驱动的产品升级**(拒答硬门控/KB 卫生/语料扩充 → **前端拆分** → 会话与上下文压缩 → 文件夹与 @ 指定库 → LangGraph 编排 → 联网搜索 → 辅导员定制 → UI 收尾) | **📋 READY —— 设计与拆分已入库(`docs/P4.md`),用户决策 P3b 先做完,故排在 P3b 之后串行下发** |
| T7 | 向量库 sqlite → sqlite-vec | 回 backlog,**未下发**(曾误建的 `task/T7-vec` 分支已删) |

## 五、当前状态与下一步(交接重点)

**质量线已闭环并升到 v1.5**:评测 26 用例、R@k **0.9231**、忠实度 **1.0**、拒答 1.0、kb_hidden 3/3(2026-09-29 KB 清理后 3 轮完全一致);qa-08 经 T10 后稳定。看板 `evals/dashboard.html` 单页自包含。**P1/P2 全部完成。**

**P3 AIOps 是简历第二亮点**,拆为 P3a(地基,已完成)→ P3b(MCP Server)→ P3c(NovaAgent 诊断链)→ P3d(注入→自动定位+录屏)。

**P3a 交付**:`sims/`(common 共用层:MetricsMiddleware / SimPool 有界池 / FaultManager / psutil CPU 轮询 / 自压测)+ jiaowu/ykt 两服务 + `fault_inject.py` CLI + `docker-compose.sims.yml` + Grafana 总览盘(uid `sims-overview`,6 面板)。验收证据在 `docs/p3a/evidence/`(targets 双 up、池耗尽 in_use 恒 10→5xx 0.204/s→自动恢复、CPU ~1700%、Grafana 截图)。

**下一步 = P4b-0 独立复核**(⚠ **本单实现者是 Qoder 本人**——Zcode 额度用尽、用户指示代做;**实现者=审查者会失效,所以未合并 master**,分支 `task/P4b-0-frontend-split` 停在 IN_REVIEW)。**复核人=用户或 Zcode**,三条要点:① `python docs/p4b0/verify_invariants.py` 应全绿(CSS 逐行等价 / JS 行多重集 0 缺 0 多 / **顶层可执行语句 6 条顺序一致**——这是跨文件重排安全性的关键证明 / 标记等价 / 处理器 25→25 无未解析 / API 调用点 20→20);② `git diff master...HEAD -- novaagent/novaagent/main.py` 只应有 +25 行静态路由、删 0 行;③ **补拍 after 截图**与 `evidence/before/` 同名配对目视(本会话 Chrome DevTools MCP 工作区根不含 `E:` 盘,`filePath` 被拒 → after 截图缺失,是取证缺口不是没验)。通过后再开 P4b。

**P4b-0 结果**:`index.html` 887→168 行 + `css/theme.css` + `js/{api,ui,chat,kb,weekly}.js`;评测 2 轮 36/36、R@k 0.9412、拒答 1.0;冒烟 PASSED、`documents` 65→65;`kb_doctor` 0 高危;浏览器实测控制台 **0 error 0 warn**、SSE 与来源渲染与 BEFORE **逐项同值**(bot_msgs=17、相关度 0.9971)。两条既存缺陷刻意未修(见坑 30/31)。

**P4a-1 已完成(合并 `5399a5e`)**:`index_page` 结构判据(短行占比≥50% 且长行占比<15% 且总行≥20 护栏)——**不是靠字数**,因为导航页菜单本身 1600+ 字。我独立扫 40 篇公开语料 **0 误伤**、实站四 URL 全拒、评测 5 轮全过;并顺带修掉我上一轮合并进去的 `RE_IDCARD` 保单号误伤(双向验证过:保单号放行、真身份证样式仍拦、非法出生日期不误拦)。**待办**:P4c 须用**自造合成案例文体样本**补一条放行断言——`corpus/clean/affairs/` 为守红线双方都未读取,那 20 篇案例"重导零误伤"目前**未实测**,不得为此去读真实 affairs。

**P4a 已完成(合并 `827e1ae`)**:拒答硬门控(确定性模板,不经 LLM)+ `[n]` 越界硬剥离 + `contacts.json` 7 条官网出口 + 导入质量门 + `smoke_test` 自清理与 **KB 守恒 65→65** + 评测集 v1.7(36 条,新增 `refusal_indomain`)。**两处裁决已批准**:① 单来源 `top≥0.9` 放行线(我原规格 `n_above≥2` 过紧会结构性误杀 qa-01);② judge 对"学段声明句"的盲区移交 P4d(附三条约束:禁止为指标删声明、改口径须记版本、应以合法上下文而非白名单)。**新认知**:虚引**不限于零来源场景**——`badcases.json` 的 `fabricated_ref.history[]` 实测 `qa-01` 仅 1 个来源却标 `[3]`(详见 EVAL_BASELINE 第十一节)。P4a 头号目标不是加功能,是**把"无据也答 + 虚构 `[1]` 引用"从代码层堵死**:实测 SYSTEM_PROMPT 的 9 条规则挡不住带情境的真实问法,而 6 条 `refusal` 用例全是域外问题(天气/电影/火锅店/微信创始人)所以指标长期 1.0。Review P4a 时先查 **C0**(修复前证据是否真复现失守)、**C1/C2**(是否落在代码而非又加一条 prompt 规则)、**C10**(检索失败是否**优雅降级**为"拒答 + 保卫处/校医院出口"),并按坑 17/18 做证据对账与 claim→字段核查。

**P3b 已完成并合并 master `2234fc8`**:`mcp/aiops` 7 个只读工具(宿主机 venv,`:18081/{sse,mcp}`)、Prometheus 5 条告警规则(实测 health=ok)、`fault_inject.py` 自留 `cpu=`/`cpu_peak` 证据、C5 端到端 DEMO 由 Qoder 亲自复跑通过(`run_playbook` 实测不执行写操作)。Review 附 1 项引用链修正(见坑 18 的 P3b 重犯记录)。**P3c 起才会再碰 `novaagent/**`;P4a 也碰(白名单已显式授权)——两单严禁并行,顺序 P4a → P4b-0 → P4b…,P3c/P3d 待 P4 之后由用户定。**

**P3b 之后 = P4**(用户反馈驱动的产品升级,设计与拆分已入库):`docs/P4.md`(模块 M1~M9 + 实测证据)+ `docs/TASKS.md` 的 P4a~P4g。**用户 2026-09-29 决策:P3b 先做完,P4 排其后串行下发。**

**用户侧反馈已到达并已处理(2026-09-29)**:辅导员实测反馈原文在 WorkBuddy 工作树 `C:\Users\<user>\WorkBuddy\Worktrees\NovaCampus\task-t10-retrieval-d910a267\docs\使用反馈.txt`(**只读,本仓库不复制原文**;结论已归入 `docs/P4.md` §一)。Qoder 已做:①按用户授权清理 KB 脏数据 17 篇(含 `id=109` 登录页 student 可见、`id=22` 自家前端首页**含演示口令**、15 篇 smoke_test 残留)→ 基线升 v1.5;②实测出**拒答门控是软约束**:F1 长问句在 `sources=[]` 时仍用自有知识作答并**虚构 `[1]` 引用**,而现有 6 条 refusal 用例全是短问句,**测不出该漏洞**→ 立为 P4a 头号修复项(代码级硬门控 + 引用越界剥离 + 新增 `refusal_indomain` 用例);③语料候选清单 `docs/p4/corpus-candidates.md` **已获用户批准,Qoder 已抓取并入库 6 篇公开官网页**(`corpus/fetch_public_pages.py`,`doc_id 110~115`,`documents 59→65`)→ 基线 **v1.6 零回归**;红线:含学生姓名的公示/名单页禁抓禁入库(已写入脚本 `DENY_URLS`)、不得用真实学工账号登录抓取、不得把 LLM 搜索摘要当语料;④学生原话按用户要求**已匿名化**(本仓库文档与证据统一写作「某市」,两份实测证据已加匿名化标注);⑤实测发现**rerank 层检索崩塌**——F2 补齐语料后仍 `sources=0`,用 8 种自然措辞测得**仅 3 种能命中已入库的正确材料**(「学平险」0.8875 过、「学平险在哪里买」0.1007 归零),且**与问句长度不单调**(7 字崩、48 字过)→ 我最初"长问句导致崩塌"的归因**已被自己的变体矩阵证伪并全项目更正**;真正机制是 reranker 低分 + 一刀切 `RERANK_MIN_SCORE=0.3` 无回退(向量层本已排第 1~4)。工具 `evals/query_variant_matrix.py` / `evals/diag_retrieval.py`,证据 `docs/p4/evidence/query_variant_matrix.txt`,叙述版见 `docs/CASE_STUDY.md` → P4a 只做优雅降级,**根治归 P4d**(硬性验收:复跑矩阵,命中率目标 ≥6/8)。


## 六、踩坑清单(绝对不能再踩,全部真实发生过)

### 观测层(最危险,曾两次导致硬停)

1. **工具结果会被伪造/回放/污染**:git log 返回过 todo JSON、同一 commit 两次显示不同 hash、文件读取返回过期版本、eval 命令返回与命令无关的 traceback。**铁律:关键结论必须落盘交叉验证**——git 状态用 `git rev-parse`/`.git` 语义比对,评测结果读 `reports/*.json` 原文,badcases 读 `evals/badcases.json` 原文,FTS 用 sqlite 直查,KB/RBAC 用 /api 响应断言。stdout 只作参考。
2. **陈旧回放**:闸门脚本返回过上一任务的完整输出(连检查项名称都是旧的)。遇到"输出与本次命令不符"→ 换最小命令复测(如 `git branch --show-current` 单独跑),仍不符 → 硬停上报,勿提交。
3. **Edit/Read 工具对"外部修改过的文件"可能服务过期内容**:Qoder 或其他会话改过的文件(TASKS.md、index.html 等),先 Bash+python 打印磁盘真实内容再编辑;编辑用 python 内联精确替换(带 count 断言)而非 Edit 工具,改完 `git diff` 验证。

### 编码与转义(高频坑)

4. **Bash heredoc 会破坏含三引号/SQL(BEGIN...END)/`\n` 转义的 python 内联脚本**(多次翻车)。铁律:**文件内容修改一律用 Write 工具写补丁脚本再执行**,python 内联只做验证/小替换;字符串内的 `\n` 用 `chr(10)`、`chr(92)+'n'` 显式构造,杜绝转义歧义。
5. **GBK 控制台 emoji 崩溃**:print ✅/❌ 在 GBK 下 UnicodeEncodeError。所有脚本开头 `sys.stdout.reconfigure(encoding="utf-8", errors="replace")`(try 容错),标记用 `[PASS]/[FAIL]/[OK]` 纯文本。验收必须 `PYTHONIOENCODING=gbk` 实测 exit code。
6. **curl -d 传中文会编码错乱产生假报错**(硅基流动 20015 假失败),API 测试用 ASCII 或 python httpx。
7. **终端显示 UTF-8 中文常乱码但数据本身正常**——乱码≠数据坏,用文件/JSON 原文判断。

### 网络与代理

8. **系统代理(VPN)会把 Python 客户端访问 localhost 的请求转发出去返回 502**(curl 不受影响)。所有本地 HTTP 调用(评测/测试/服务间)必须 `NO_PROXY="127.0.0.1,localhost"`。
9. **GitHub 直连不稳**;Docker Hub 需镜像加速(docker.m.daocloud.io 等已配)。

### NovaAgent 代码行为(已修复过,别再犯)

10. **改 .env / 改代码后必须重建进程**:`docker compose up -d app`(容器)或杀进程重启 uvicorn——`restart` 不重读环境变量,"改了没生效"十有八九是这个。
11. **FTS5 外部内容表 count(*) 直读内容表**:计数门控永不触发、索引恒空。已改启动时无条件幂等 rebuild;**新会话若见 MATCH 恒 0 先查这条**。
12. **llm.py 曾缺 import json**(chat_stream 追加时漏)——追加新函数用到标准库时检查 imports。
13. **强制 _fts_ok=False 是回退验证标准动作**:FTS 路径与内存 2-gram 回退路径都要能出结果。

### 流程纪律

14. **串行持棒**:TASKS.md 的当前持棒不是你 → 只读不写;禁改文件列表绝对不碰(触碰=Review 打回)。
15. **每完成一个可验证单元就 commit**;提交信息 `T<id>: 开头`;**提交前用语义通道核对**(暂存区文件列表、路径集合比对——别信带前导空格的渲染)。
16. **qa-08 类边界用例会轮换波动**(LLM temperature 0.3):单轮 FAIL 先查 badcases history 与检索诊断(本地调 rag.search 打印来源排序),确认是检索问题还是采样问题——采样问题检索侧无解,别瞎调。

### 证据与 Review 纪律(P3a Review 时新踩,2026-09-28)

17. **落盘 ≠ 入库**:Zcode 的 `docs/p3a/evidence/` 有 8 份证据、文档逐条引用,但 `.gitignore` 的 `*.log` 让其中 2 份 CLI 日志**只在工作区、从未进 commit**——新克隆仓库会缺证据。铁律:凡文档引用的证据文件,必须 `git diff --name-status master...HEAD` 与引用清单**逐条对账**,并 `git check-ignore -v` 排查静默排除。已加 `!docs/p3a/evidence/*.log` 例外。
18. **数字要有成立的出处**:验收表把 CPU `1650.5%` 归给 CLI 日志 + promql 文件,但 CLI 只轮询 `/debug/fault/status`(**响应里根本没有 CPU 字段**),promql 记的是**恢复后**值——峰值只有 Grafana 截图能证。结论方向没错,但引用链不成立。**Review 要顺着"claim → 该文件是否真含此字段"追一遍**,不能只看文件在不在。
    - ⚠ **同类错误在 P3b 重犯(2026-09-29)**:P3B.md §三 行 5 写「注入中 `process_cpu_percent=1688.6`，出处 `step0_cpu_spike_promql.txt`」,实查该文件只有「恢复后 0.5」+ 一行落盘截断的残留 `ykt 1`,`1688.6` 在**所有**证据文件中都不存在(`grep -rln 1688` 空)。数值量级对,引用链不对。**结论:引用链核对不是"写过一次就完了"的规矩,是 Review 每单必做的固定动作**——写文档的人会凭屏幕记忆填数字,落盘文件会截断。
    - ⚠ **同时提醒 Reviewer 自己**:本次 Review 我有两处误判都被证据推翻——① 怀疑"Zcode 没加 .gitignore 例外",实际是我自己的 `git diff --stat | tail -25` 把首行截掉了(该例外确由他在 `968bb4c` 添加);② 怀疑"id=120 不含演示口令",实际含,是我的扫描模式只认旧措辞 `密码均为` 而实际是 `admin/admin123` 斜杠式。**用截断的输出下结论、用单一措辞做检测,都会产生假问题。**
19. **daemon 挂了不能假装复跑**:P3a Review 时 Docker Desktop 已停、4 端口不可达 → 明确定性为**证据复核**,写进文档,并把实时复跑推给 P3b 第 0 步。**别用旧截图冒充本次实测**。
20. **时间戳交叉是判真伪的利器**:`prometheus_targets.json` 的 `lastScrape` 10:32:44Z(+0800=18:32:44)与截图文件 mtime 18:32:20 吻合、与 CLI 日志采样窗口吻合 → 三方一致才判"真实运行留痕"。

### 产品与评测盲区(2026-09-29 处理用户反馈时新踩,全部有实测证据)

21. **拒答是软门控,长问句会失守**:SYSTEM_PROMPT 的 9 条规则挡不住"域内相关 + 情境丰富"的长问句——实测 `sources=[]` 时模型仍用自有知识给出完整流程/材料清单/APP 名,并**虚构 `[1]` 引用**;同主题短问句则拒答正确(但仍带 `[1]`)。铁律:**无据判定必须落在代码里**(sources 空 或 top_score < 阈值 → 确定性拒答模板,不经 LLM 自由生成),`[n]` 越界编号必须代码剥离并记 badcase。
22. **评测集会给你假安全感**:6 条 `refusal` 用例全是短问句/域外问题 → 拒答准确率长期 1.0,却仍发生真实事故。铁律:**新增能力必须配"能测出它失败"的用例**(域内无据 + 长问句 + 含个人情境),指标好看 ≠ 测到了。
23. **smoke_test 会持续污染生产库**:每跑一次冒烟上传 3~4 篇测试文档且从不清理,累积 15 篇重复标题,抢占 `MAX_PER_DOC=2` 名额稀释真实来源(`qa-03` R@k 因此只有 0.5)。铁律:**测试必须自清理 + 断言 `documents` 计数守恒**;基线异常先查库里有没有测试残留。
24. **网页导入别抓首页/索引页**:`cwc.swjtu.edu.cn/` 首页是登录框(入库正文只有"浏览器兼容性提示"),`infpub.swjtu.edu.cn/gksx/...` 是导航索引页(只有跳转链接);更糟的是曾把自家前端首页 `http://127.0.0.1:8900/` 导入库,**正文含演示口令**。铁律:导入必须有质量门(有效长度/登录页特征/title/URL 去重/敏感扫描),**口令与个人信息永不入库**;含学生姓名的公示名单页禁抓禁入库。
25. **DashScope 兼容模式拿不到联网来源**:`enable_search=true` 在 OpenAI 兼容模式下只回 `usage.plugins.search.count`,**没有 `search_info`**;要 title/url/角标必须走原生协议 `POST /api/v1/services/aigc/text-generation/generation` + `search_options{forced_search, search_strategy, enable_source, enable_citation, citation_format}`(2026-09-29 已实测可用,复用同一 `LLM_API_KEY`,turbo 策略不额外计费)。
26. **基线口径必须标清**:`EVAL_BASELINE.md` 历史行混用"3 轮中位"与"单轮均值"(v1.4.1 中位 0.9615 / 单轮均值 0.9231)。引用任何基线数字都要注明**口径 + 语料篇数**,否则验收对账会把改善误判成回归。

27. **真实措辞会把检索打崩,而评测用例测不出来(且原因不是"句子长")**:同一份已入库的"学平险"材料,用 8 种自然问法实测(`evals/query_variant_matrix.py`,两遍数值一致)**只有 3 种命中 = 37.5%**。「学平险」rerank **0.8875** 通过、「学校有学平险吗」0.8065 通过,但「学平险在哪里买」**0.1007** 归零、「学生平安保险是否由学校统一办理？」**0.0194** 归零、学生原句 0.1136 归零——全部低于 `RERANK_MIN_SCORE=0.3` 且**无候选回退**。⚠ 我最初把根因写成"长问句导致崩塌",**这个结论是错的且已被自己的变体矩阵证伪**:7 字崩、16 字崩、**48 字的多子句书面句反而通过**,崩塌与长度**不单调**。真正机制是 **reranker 对"问句意图与分块字面内容不严格对应"就给极低分 + 一刀切阈值放大成零来源**;而**向量层其实已把目标排到第 1~4 位**,所以别一失败就怀疑语料。另 `fts_search()` 整句短语匹配失败会回退 2-gram 计次,被"学校/我们/这项"等通用词顶榜(教育部令 5 块霸榜)。铁律:① 新知识点必须**术语式短问 + 口语式长问配对建案**,并保留真实用户原句;② 检索异常先用 `evals/diag_retrieval.py` 逐层打印(向量/关键词/融合/rerank)再下结论,**不要用"句子长短"这种没验证过的直觉当根因**;③ **不要单独调 `MAX_PER_DOC`**(T10 实测 =1 会挤出关键块)。与坑 21/22 同源:**评测用例的句式与材料现成表述高度对齐,真实用户按自己的说法问**。

28. **长度门拦不住导航/索引页(2026-09-29 P4a Review 实测)**:`kb_import_url` 用"正文 ≥200 字"判低信息量,但**整站菜单本身就超 200 字**——索引页 `infpub.swjtu.edu.cn/gksx/cw_zcjsfxx/sfxm_sfyj_sfbzjtsfs.htm` 导入成功(81 行 / 菜单式短行 62% / 正文式长行仅 9 条 / 1623 字)。铁律:低信息量判定必须看**结构特征**(短行占比 + 长行条数),不能只看字数;判据要配真实样本做单测(fixture 已留 `docs/p4/evidence/sample_index_page.txt`)。责任在规格未把"索引页不可入库"转成可执行判据,不在实现。
29. **取证先于清理——我自己又犯了一次**:Review 时我用同一批 URL 做导入回归测试,测试**污染了 KB(65→66)**;我第一次操作是"直接删掉污染文档",结果**删之前没把该页特征测完**,只好重新抓一次补样本。这与坑 17/18 是同一类:**动手清理/修复之前,先确保要引用的证据已经测完并落盘**。运行时数据由我处置没问题,但顺序错了会自找返工。

30. **后端返回结构化错误,前端却只会显示 HTTP 状态码(既存,转 P4g)**:P4a 把导入拒绝改成 `{code, reason, hint}`,但 `web/js/api.js` 的 `api()` 只在 `detail` 是**字符串**时渲染它,遇到 dict 就回退成 `HTTP 400`。实测 counselor 导入导航页 → 界面只显示 **"导入失败：HTTP 400"**,那句"请粘贴具体文章页 URL"的关键 hint **从未到达用户**。教训:**接口契约改了必须同时检查消费端**;`{code,reason,hint}` 设计再漂亮,前端不渲染等于没做。P4b-0 属纯重构故未顺手修。
31. **`importUrl()` 依赖内联事件的全局 `event`**(`const btn = event.target`):从浏览器控制台/自动化脚本直接调用会 `TypeError: Cannot read properties of undefined (reading 'target')`——**这不是回归**,拆分前后一字未动。要单测或自动化驱动,需改成显式传参。做 UI 自动化前先分清"我调用方式不对"与"代码坏了"。
32. **纯重构单的"行为零变化"要可机检,不能靠截图**:本次用六条不变量替代肉眼(CSS 逐行 / JS 行**多重集** / **顶层可执行语句相对顺序** / 去标签标记 / 内联处理器集合+标识符可解析 / API 调用点集合),工具 `docs/p4b0/verify_invariants.py`。其中**顶层语句顺序**那条最容易被忽略——函数声明有提升所以跨文件重排安全,但 `const`/`let` 初值语句重排会出事,必须单独证明。另记:我第一版校验脚本自己有两个缺陷(D 只扫骨架没扫 js、C 把骨架重复计入导致 25→42),**报 FAIL 时先怀疑尺子,再怀疑工件**。

## 七、快速验证命令(接手自检)


```bash
cd /e/AILearn/NovaCampus
git branch --show-current && git log --oneline -3   # 分支与最近提交
NO_PROXY="127.0.0.1,localhost" curl -s http://127.0.0.1:8900/api/health
PYTHONIOENCODING=gbk NO_PROXY="127.0.0.1,localhost" novaagent/.venv/Scripts/python.exe evals/run_evals.py
python evals/extract_badcases.py

# ---- P3 sims 栈(先确认 daemon 活着,再谈验证)----
docker ps                        # 报 dockerDesktopLinuxEngine 找不到 = Desktop 没开,停手上报
NO_PROXY="127.0.0.1,localhost" curl -s "http://127.0.0.1:9090/api/v1/targets" | grep -o '"health":"[a-z]*"'
NO_PROXY="127.0.0.1,localhost" curl -s http://127.0.0.1:9102/metrics | grep -E 'app_db_pool_(size|in_use)|process_cpu'
/d/anaconda3/python.exe sims/fault_inject.py --target ykt --mode pool_exhaust --duration 30
# 语法自检(不需要依赖):/d/anaconda3/python.exe -m py_compile sims/common.py sims/*/app.py sims/fault_inject.py

# ---- KB 卫生与规模(2026-09-29 清理+语料增补后应为 documents 65 / chunks 487)----
/d/anaconda3/python.exe -c "import sqlite3;c=sqlite3.connect('novaagent/data/agent.db');print('documents',c.execute('select count(*) from documents').fetchone()[0],'chunks',c.execute('select count(*) from chunks').fetchone()[0]);print('dup_titles',c.execute('select count(*) from (select title from documents group by title having count(*)>1)').fetchone()[0]);print('dirty',c.execute(\"select count(*) from documents where title in ('登录') or filename like 'http%'\").fetchone()[0])"
# 期望:documents 65 / chunks 487 / dup_titles 0 / dirty 0;不符先查是否有人跑过 smoke_test 未清理(坑 23)
# 评测(须先起服务,且必须带评测温度开关):
#   cd novaagent && NO_PROXY="127.0.0.1,localhost" NOVAAGENT_EVAL_TEMPERATURE=0 .venv/Scripts/python.exe -m uvicorn novaagent.main:app --port 8900
#   PYTHONIOENCODING=gbk NO_PROXY="127.0.0.1,localhost" novaagent/.venv/Scripts/python.exe evals/run_evals.py   # v1.5: 26/26 R@k 0.9231 忠实度 1.0
```

