# P3b AIOps MCP Server——SIMS 监控栈的只读取证工具集

> 分支 `task/P3b-aiops-mcp`,持棒 Zcode。规格见 `docs/TASKS.md` P3b 条目(C0~C8)。
> 定位:P3c NovaAgent 诊断链的工具底座——收告警→查指标→捞日志→查变更→跑预案,全程只读;
> 恢复动作只输出"建议命令 + 需人工执行"。

## 一、架构与部署形态

```
P3c NovaAgent(计划) ──AIOPS_MCP_URL=http://127.0.0.1:18081/mcp──► aiops MCP server(宿主机 venv)
                                                                    │ 只读
        ┌───────────────────────────────────────────────────────────┤
        ▼ Prometheus :9090(HTTP API)                 ▼ 宿主机 docker CLI(只读 logs)
   /api/v1/query* /rules /alerts                 docker logs --since --tail nova-sims-{ykt,jiaowu}-1
        ▲ 抓取 5s                                     ▲ stdout/stderr
   sims 栈(docker-compose.sims.yml):jiaowu:9101 / ykt:9102 / prometheus:9090 / grafana:3000
   alerts.yml(C1,5 条规则,rule_files 挂载)→ list_alerts / run_playbook 的告警数据源
```

**部署形态决策:宿主机 venv(容器形态被实测否决)。** 依据(2026-09-29 实测,step0):
- `docker exec NovaCampus-weekly-mcp sh -c "which docker"` → 退出码 1、无输出(**NO_DOCKER_CLI**);
- `docker exec NovaCampus-weekly-mcp sh -c "ls /var/run/docker.sock"` → **No such file**(连 socket 都没挂);
- aiops 的 `query_logs` 依赖 docker CLI 读容器日志——若做容器形态必须挂 socket + 装 CLI,既扩大攻击面又
  与 weekly 既例不一致。故 aiops 跑**宿主机 venv**,暴露 `http://127.0.0.1:18081/{sse,mcp}`,与
  weekly 的 `WEEKLY_MCP_URL=http://127.0.0.1:18080/mcp` 接入方式对齐,P3c 以 `AIOPS_MCP_URL` 连接。
- 代价与边界:`query_logs` 依赖宿主机 docker CLI/daemon(缺失时报错并给排查提示,不返回空列表冒充"无异常")。

## 二、工具契约(7 个,全部只读;docstring 详见 server.py)

| 工具 | 作用 | 关键返回字段 | 数据源(可追出处) |
|---|---|---|---|
| `get_service_status` | up/池/CPU/uptime 全局一览 | `services[].pool_utilization_pct`、`uptime_seconds` | `up`、`app_db_pool_size/in_use/waiting`、`process_cpu_percent`、`process_start_time_seconds` |
| `list_alerts` | 收告警(规则=C1 alerts.yml) | `rules_count`、`alerts[].alertname/state/value` | `/api/v1/rules` + `/api/v1/alerts` |
| `query_metrics` | promql 即时/区间查询 | `mode/series_total/truncated/results[].values[].time(+0800)/value(4位有效)` | `/api/v1/query*`(只允许这两个) |
| `query_logs` | 日志命中行+状态码分布 | `command_used(只读命令原文)`、`status_code_counts`、`matched_lines(≤80)` | `docker logs --since --tail`(只读) |
| `query_changes` | 重启/注入窗口/注入触发(带出处) | `changes[].kind/source` | `process_start_time_seconds`、`max_over_time(fault_active[w])`、`increase(http_requests_total{path="/debug/fault/{mode}"}[w])` |
| `run_playbook` | 只读预案取证(mitigation 仅建议) | `signals[].fired/samples`、`steps[].result`、`mitigation.note` | `playbooks.yml` + 上列只读工具 |
| `gather_diagnosis` | 一键全链取证(P3c 快捷入口) | `evidence_chain[].{field,tool,value}` | 上列全部 |

**只读防护(query_metrics)**:仅允许 `/api/v1/query`、`/api/v1/query_range`(_prom_get 白名单,
另含 list_alerts 所需的只读 `/api/v1/rules`、`/api/v1/alerts`);promql 禁分号(多语句)、禁 >2000 字符;
超时 10s;序列 >200 / 单序列点数 >200 截断并在返回中**显式声明**(`truncated`/`truncated_note`);
service 名白名单校验防 promql 注入。**红线(run_playbook)**:steps 只允许五个只读工具,
不执行 restart/rm/exec 等任何写操作;mitigation 仅文字建议。

## 三、验收数字 → 出处对照表(全部来自本次开发周期实测)

| # | 关键数字/事实 | 出处文件 | 字段/位置 |
|---|---|---|---|
| 1 | targets 双 up | `docs/p3b/evidence/step0_targets.json` | `data.activeTargets[].health`="up"(jiaowu/ykt,lastScrape 2026-09-29T06:42Z) |
| 2 | C1 前 rules/alerts 为空 | `step0_rules_before_c1.json` / `step0_alerts_before_c1.json` | `data.groups=[]` / `data.alerts=[]` |
| 3 | pool_exhaust 60s 池饱和 | `step0_pool_exhaust.log` | `[poll]` 行 `pool_in_use=10`(t+5s~t+55s),`t+60s active=False pool_in_use=0` 自动恢复 |
| 4 | 注入中 promql(利用率/503/等待) | `step0_pool_exhaust_promql.txt` | `app_db_pool_in_use=10`、利用率=1、**503 速率 0.240009/s**(status="503" 分支)、等待速率 0.4803 s/s、`fault_active=1` |
| 5 | CPU 注入尖峰与恢复 | `step0_cpu_spike_promql.txt` | 注入中 `process_cpu_percent=1688.6`、`max_over_time[40s]=1688.6`;恢复后 **0.5** |
| 6 | CPU 注入 CLI 自留证据(C2 修成) | `step2_cpu_spike_cpu.log` | `[poll]` 行 `cpu=1535.3%…1712.9%`,结束 `cpu_peak=1712.9%`(来源标注 /metrics 的 process_cpu_percent) |
| 7 | pool_exhaust 期间 CPU 无关 | `step2_pool_exhaust_cpu.log` | 轮询行 `cpu=0.0%~1.0%`,cpu_peak=1.0% |
| 8 | 告警规则加载 5 条 | `step1_alerts_firing.json` 同源 `/api/v1/rules` | rules_count=5(注入前 smoke 输出 `[SSE] list_alerts OK: 规则 5 条`) |
| 9 | 注入现场 firing | `step1_alerts_firing.json` | `SimsDbPoolSaturated`(value 1)、`SimsDbPoolWaitP95High`(4.3625)、`SimsHttp5xxRateHigh`(0.16),state=firing,job=ykt |
| 10 | 端到端演示全链 | `demo_pool_exhaust.txt` | demo2 `SimsDbPoolSaturated` firing;demo3a 池利用率 **100.0%**@15:02:02+0800;demo3b 5xx **0.16/s**;demo4 503 计数 **16**(uvicorn 行原文);demo6 三信号命中(1/0.16/4.363);demo7 证据链 6 条 |
| 11 | 双传输 7 工具全过 | 终端留痕(下节 C3) | `SMOKE TEST PASSED`(SSE+StreamableHTTP 双轮) |
| 12 | 只读防护 13 项 | 终端留痕 | `GUARD TESTS PASSED`(含 401 点截断声明 points=401) |

> 坑 18 自查:表内每条"数字"都能点开对应文件逐字段复核;CLI 的 CPU 字段是 C2 改造**之后**的日志
> (step2_*),P3a 时代旧日志确无 CPU 字段——历史结论不回溯冒充。

## 四、C0~C8 完成标准自评

- **C0** ✅ `step0_targets.json`、`step0_pool_exhaust.log`、`step0_pool_exhaust_promql.txt`、
  `step0_cpu_spike.log`、`step0_cpu_spike_promql.txt` 全部落盘并入库(commit 968bb4c),数字来自本次运行
  (与 Qoder 预检量级一致:in_use=10、503>0、CPU ~1688、恢复 0.5)。
- **C1** ✅ `sims/prometheus/alerts.yml` 5 条规则(池饱和/等待P95/5xx/CPU>800%/up==0,`for:`≤10s),
  prometheus.yml 加 `rule_files`、compose 加挂载一行;`/api/v1/rules` 非空、注入现场 3 条 firing 落盘
  (`step1_alerts_firing.json`)。
- **C2** ✅ `fault_inject.py` 轮询行打印 `cpu=NNN.N%`、结束打印 `cpu_peak=`(纯标准库解析
  `{base}/metrics` 无 label 的 `process_cpu_percent`;解析失败降级 NA 且不改退出码);两种注入日志
  (`step2_pool_exhaust_cpu.log`/`step2_cpu_spike_cpu.log`)均见 CPU 数值。
- **C3** ✅ 7 工具在 `/sse` 与 `/mcp` 双传输下可见可调用,`tests/smoke_test.py` 输出 `SMOKE TEST PASSED`。
- **C4** ✅ `tests/test_query_metrics_guard.py` 13 项:空/多语句/超长 promql 拒绝、admin/写类路径拒绝、
  service 名注入拒绝、401 点区间截断声明、语法错误 ok=false、时间 +0800/数值 4 位、mini-yaml 回退解析。
- **C5** ✅ `tests/aiops_demo.py` 端到端跑通并落盘 `evidence/demo_pool_exhaust.txt`(DEMO PASSED)。
- **C6** ✅ 见第五节对账。
- **C7** ✅ 本文档。
- **C8** ✅ 越界对账 + evals v1.6 对照 + documents 计数复核,结果见第六节。

## 五、C6 证据入库对账(P3a 坑 17)

- 文档引用的 evidence 文件全集:`step0_targets.json`、`step0_rules_before_c1.json`、
  `step0_alerts_before_c1.json`、`step0_pool_exhaust.log`、`step0_pool_exhaust_promql.txt`、
  `step0_cpu_spike.log`、`step0_cpu_spike_promql.txt`、`step1_alerts_firing.json`、
  `step2_pool_exhaust_cpu.log`、`step2_cpu_spike_cpu.log`、`demo_pool_exhaust.txt`(11 份)。
- `git ls-files docs/p3b/evidence/` = 上述 11 份全部入库;`git diff --name-status master...HEAD`
  逐条对账一致。
- `.gitignore` 新增例外行 `!docs/p3b/evidence/*.log`(与 p3a/p4 同款);`git check-ignore -v` 对两份
  `.log` 返回**该例外规则本身**(negation 命中=未被忽略),且文件已在 commit 968bb4c 中可查。

## 六、C8 零回归记录

- 越界对账:`git diff --name-status master...HEAD` 无黑名单路径(novaagent/corpus/evals/reports/web/
  weknora/mcp/weekly/sims/common.py/sims/jiaowu/sims/ykt/sims/Dockerfile/sims/requirements.txt/sims/grafana)。
- 评测对照(v1.6 基线:26 用例/R@k 0.9231/忠实度中位 1.0/拒答 1.0,documents=65):本次实跑结果见回执。
- smoke_test 污染说明:`novaagent/tests/smoke_test.py` 会向 KB 上传测试文档且不自清理(P4a 修),
  跑后已复核 `documents` 计数并在回执写明。

## 七、已知限制与 P3c 接入点

1. **fault_active 序列缺失窗口**:容器重启后到**首次注入前**,`fault_active` 时间序列不存在——
   `query_changes` 在该窗口查不到注入记录≠没有注入(返回体 `limitation` 字段已如实声明);
   `http_requests_total{path="/debug/fault/{mode}"}` 计数器随注入次数累加、`fault_active` 注入后留存为 0
   (不消失),二者是变更认定的成立出处(Qoder 预检一致)。
2. **path 标签不区分注入模式**:`/debug/fault/{mode}` 是单一路由模板,`http_requests_total` 的 path 标签
   无法区分 pool_exhaust/cpu_spike——mode 归属以 `fault_active{type}` 窗口为准(工具内已注明)。
3. **query_metrics 的 window_s 语义**:`window_s: float | None = None`——None(缺省)=即时查询;传数值
   (如 300)=回看该秒数的区间查询。规格写"默认 300"指区间用法下的典型值;Python 无法区分"未传"与
   "传默认值",故用 None 表达"未传=即时"。
4. **P3c 接入点**:URL `http://127.0.0.1:18081/mcp`(Streamable HTTP)或 `/sse`;建议 env
   `AIOPS_MCP_URL=http://127.0.0.1:18081/mcp`(对齐 `WEEKLY_MCP_URL` 写法);admin 角色可见(可见性
   控制在 P3c 的 main.py 侧实现,aiops 本身无鉴权——只读+本机端口)。
5. **query_logs 依赖宿主 docker CLI**:aiops 为宿主机 venv 形态;若未来容器化,须挂
   /var/run/docker.sock 并安装 CLI(实测 weekly 容器两者皆无),或改由 Prometheus 侧取日志方案。
