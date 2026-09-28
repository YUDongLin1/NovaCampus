# HANDOFF · NovaCampus 会话交接文档

> 写于 2026-09-28,供**零上下文新会话**接续。读完本文 + `docs/COLLAB.md` + `docs/TASKS.md` 即可接手。
> 你(Zcode/实现者)与 Qoder(负责人/Review)按 `docs/COLLAB.md` 协同:**单一事实源 TASKS.md、串行持棒、白名单禁改、Review 闸门**。

---

## 一、我们在做什么

**NovaCampus(智枢 Agent)**——个人简历项目,目标 AI 产品方向。双轨:
- **NovaAgent**(自研,`novaagent/`):FastAPI + SQLite 的校园智能体,三角色 RBAC(学生/辅导员/管理员)、RAG 问答(混合检索+rerank+拒答阈值)、流式 SSE、会话持久化、周报助手(经 MCP 调用)。
- **WeKnora**(腾讯开源,`weknora/`,git 忽略):评测基线,已部署但不开发。

**协作模式**:Qoder 下发任务规格到 `docs/TASKS.md` → Zcode 在 `task/T*` 分支实现 → 自测 → 回填交接回执 → IN_REVIEW 等 Qoder Review → 合并。**同一时刻只有持棒者能写工作区。**

## 二、必读文件(按序)

1. `docs/COLLAB.md` —— 协同规约(持棒/白名单/Review 闸门)
2. `docs/TASKS.md` —— 任务板(唯一事实源;含 T1-T10 全部条目与回执)
3. `docs/EVAL_BASELINE.md` —— 评测基线演进(v1.0→v1.4)
4. `docs/BADCASES.md` —— bad case 档案机制
5. `corpus/MANIFEST.md` —— 语料合规分层(Tier A/B;**严禁引入 E:\<internal-affairs-dir>\ 的 Tier B 真实数据**)

## 三、运行状态(接手先验)

| 项 | 值 |
|----|----|
| 仓库 | `E:\AILearn\NovaCampus`,git 身份 YUDongLin1 |
| NovaAgent | `uvicorn novaagent.main:app --port 8900`(在 novaagent/ 下跑,venv=`novaagent/.venv`) |
| weekly MCP | docker 容器(18080)或本地 `python mcp/weekly/server.py`;NovaAgent 启动时会连它,**连不上则服务起不来**(lifespan 致命) |
| WeKnora | docker compose,http://localhost(评测基线,不动它) |
| 演示账号 | admin / counselor / student,密码均 xxx123 |
| DB | `novaagent/data/agent.db`(SQLite);WeKnora 库 `novaagent/data/` 无关 |
| 模型 | 百炼 qwen-flash(内置默认)+ qwen3.7-plus(UI 配),key 在 `novaagent/.env` 与 `weknora/.env`(均 gitignore) |

## 四、任务台账(截至交接)

| 任务 | 内容 | 状态 |
|------|------|------|
| T1 | 语料库 75 篇(政策 32+事务 20+运维 2)+脱敏+导入 | ✅ DONE 合并 |
| T2 | bad case 档案机制(extract_badcases.py) | ✅ DONE 合并 |
| T3 | 前端校园化(水墨主题/登录页/三角色 UI) | ✅ DONE 合并 |
| T4 | 评测深化(Recall@k/忠实度 LLM-judge/26 用例) | ✅ DONE 合并 |
| T5 | 评测闭环整包(检索调优/对比/看板) | ✅ DONE 合并 |
| T6 | FTS5 检索层 + 措辞加固(any-of) | ✅ DONE 合并 |
| T8+T9 | 流式 SSE + 会话持久化 | ✅ DONE 合并 |
| **T10** | **检索相关性根治(qa-08 稳定性)** | **🟣 IN_REVIEW,部分达成——见下节** |
| T7/T11+ | 技术债(FTS5 已做)/看板等 | 未下发 |

## 五、T10 当前状态(交接重点)

**做了**:`rag.py` 落地杠杆 ③(RERANK_BLEND=0.6,rerank 分+RRF 秩 blend)+ ② (FINAL_TOP_K 7);杠杆 ① (MAX_PER_DOC=1) 实测有害已回退。检索诊断证明:"复学一周"块**确定性稳定 rank 2**(41号 rank 1 为真实相关度),检索层无波动。评测 6 轮:qa-08 逐轮 [T,T,F,T,F,T,T,F] 混合波动,中位 R@k 0.8846(↑)、忠实 0.9538、拒答 1.0、kb_hidden/refusal 全过。提交 `9f9bf94` + 回执 `59c45f9`,TASKS.md 状态 IN_REVIEW。

**卡点**:qa-08("休学期满怎么申请复学"答案漏"期满前一周")残余是 **LLM temperature 0.3 采样**(检索已确定性最优,上下文必含该细节)。根治需改 `llm.py`(评测路径 temperature=0)或 `agent.py`(答案构成指引)——**两者在 T10 均为禁改**,已在回执"遗留"向 Qoder 报批。

**下一步(按序)**:
1. 等 Qoder 对 T10 的 Review 裁决(通过合并 / 打回)。
2. 若批准越界修 qa-08:改 `llm.py` 评测路径 temperature=0(1 行)或 agent.py 答案指引,重跑 3 轮验证后合并。
3. 之后按 TASKS.md 技术债清单推进(T7 sqlite-vec / T8 已做 / T9 已做 / 看板聚合)。

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

## 七、快速验证命令(接手自检)

```bash
cd /e/AILearn/NovaCampus
git branch --show-current && git log --oneline -3   # 分支与最近提交
NO_PROXY="127.0.0.1,localhost" curl -s http://127.0.0.1:8900/api/health
PYTHONIOENCODING=gbk NO_PROXY="127.0.0.1,localhost" novaagent/.venv/Scripts/python.exe evals/run_evals.py
python evals/extract_badcases.py
```
