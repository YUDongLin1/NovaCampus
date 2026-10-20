# P3b 开单指令（粘进 Zcode 新会话）

> 由 Qoder 于 2026-09-29 生成。规格正文以 `docs/TASKS.md` 的 P3b 条目为唯一事实源，本文件只是开场指令副本，内容冲突时以 TASKS.md 为准。

=== PROMPT 开始 ===

你是 **Zcode**，NovaCampus 项目（`E:\AILearn\NovaCampus`）的**实现者**。Qoder 是负责人，已把 **P3b AIOps MCP Server** 下发给你，**当前持棒=Zcode**，此刻工作区只有你能写。

按序做，不要跳：

1. 读 `docs/TASKS.md` 头部「当前持棒」确认是你，然后**完整读 P3b 条目**（目标 / 第 0 步 / 白名单 / 黑名单 / 工具契约表 / 完成标准 C0–C8 / 验收命令 / 依赖）。
2. 读 `docs/COLLAB.md`（§2 执行模型、§5 Review 闸门）、`docs/P3A.md`（§二指标、§三注入原理、§四环境注记）、`HANDOFF.md` §六 踩坑清单（重点坑 4 heredoc、坑 5 GBK、坑 8 NO_PROXY、坑 17 落盘≠入库、坑 18 数字要成立出处）。
3. 切分支：`git checkout task/P3b-aiops-mcp`（Qoder 已从 master 建好，指向含 P3b 规格的提交；**不要**在 master 上写）。

**第 0 步（强制，先做再写代码）**：`docker ps` 确认 daemon 活着 → `docker compose -f docker-compose.sims.yml up -d` → `:9090/api/v1/targets` 双 up、`:9102/metrics` 可抓 → **实时复跑 `pool_exhaust 60s` + `cpu_spike 30s`**，CLI 留痕与 promql 逐项落盘到 `docs/p3b/evidence/step0_*`（这是补 P3a 因 daemon 停机欠的实时验证，数字必须来自本次运行）。另实测 `docker exec NovaCampus-weekly-mcp sh -c "which docker"`，把 aiops 能否在容器内取 `docker logs` 的结论写进回执。
**Qoder 预检基线（2026-09-29，只用于比对量级，不得当作你的证据）**：池耗尽 `in_use=10`、503 速率 0.0579/s、t+40s 自动归零；CPU 注入 `process_cpu_percent=1638.3`、`max_over_time[40s]=1657`、恢复 0.5；`/api/v1/rules` 与 `/alerts` **当前为空**（所以 C1 的 alerts.yml 是 `list_alerts` 的唯一真实数据源）；现有 CLI `[poll]` 行**确无 CPU 字段**。**环境输出与这些量级不符 → 硬停上报**，不要自行解释过去，更不得沿用旧截图下结论。

**边界（越界即打回）**：只准动白名单 `mcp/aiops/**`、`docker-compose.aiops.yml`、`sims/fault_inject.py`（仅 C2 的 CPU 取证改造）、`sims/prometheus/**`（新增 alerts.yml + prometheus.yml 加 rule_files）、`docker-compose.sims.yml`（仅挂载一行）、`.gitignore`（仅加 `!docs/p3b/evidence/*.log` 例外）、`docs/P3B.md`、`docs/p3b/evidence/**`。**`novaagent/**` 严禁改动**（接入是 P3c），`corpus/ evals/ reports/ web/ weknora/ mcp/weekly/ sims/common.py sims/jiaowu/ sims/ykt/ sims/Dockerfile sims/requirements.txt sims/grafana/` 也不许碰。

**工具集**：`get_service_status` / `list_alerts` / `query_metrics(promql)` / `query_logs` / `query_changes` / `run_playbook`，建议再加 `gather_diagnosis` 串成一次取证。全部**只读**；返回统一 `{ok:true,...}` / `{ok:false,error}` JSON；docstring 用中文写清"何时调用 + 返回字段"，P3c 的 ReAct 靠它选工具。`query_metrics` 必须做只读防护与输出裁剪（点数/series 上限、超时、时间转 `+0800` 可读串）。`run_playbook` **红线：不得执行 restart/rm/exec 等写操作**，需要恢复动作只输出"建议命令 + 需人工执行"。

**交付要求**：每完成一个可验证单元就 commit（`P3b: …`）；C0–C8 逐条自评；**C6 必做**——`git diff --name-status master...HEAD` 与文档引用的证据文件逐条对账，`git check-ignore -v` 确认 `.log` 没被全局规则静默排除；回执里每个关键数字都要写清"数字 → 哪个文件 → 哪个字段"。**基线口径已更新**：C8 的评测对照用 **v1.6（26 用例 / R@k 0.9231 / 忠实度中位 1.0 / 拒答 1.0，语料 documents=65）**，不是 0.8846/0.9615；若你跑了 `smoke_test.py`，它会往 KB 塞测试文档且不清理（已知问题，P4a 才修），跑完请复核 `documents` 计数并在回执说明。完成后回填「交接回执」（分支/提交 hash/diff 摘要/自测输出/逐条自评/遗留问题），把 P3b 状态置 `IN_REVIEW`、`当前持棒=Qoder`。

**不许做**：不要自行开 P3c、不要合并 master、不要动 `C:/Users/<user>/WorkBuddy/Worktrees/NovaCampus/`、不要把任何 `<内部学工数据目录>\` 真实学工数据或 `corpus/*/affairs/` 内容带进代码/文档/网络。

=== PROMPT 结束 ===
