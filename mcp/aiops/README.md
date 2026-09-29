# AIOps MCP Server(P3b)——SIMS 监控栈的只读取证工具集

NovaAgent(P3c)诊断链的"手":收告警 → 查指标 → 捞日志 → 查变更 → 跑预案。
全部工具**只读**;恢复动作只输出"建议命令 + 需人工执行"。

## 工具(7)

| 工具 | 作用 | 数据源 |
|---|---|---|
| `get_service_status` | up/连接池/CPU/uptime 全局一览 | Prometheus `/api/v1/query` |
| `list_alerts` | 收告警(rules 来自 `sims/prometheus/alerts.yml`) | `/api/v1/rules` + `/api/v1/alerts` |
| `query_metrics` | promql 即时/区间查询(只读防护+截断声明) | `/api/v1/query*` |
| `query_logs` | 容器日志命中行 + 状态码分布 | 宿主机 `docker logs --since --tail`(只读) |
| `query_changes` | 重启/注入窗口/注入触发次数(每条带 promql 出处) | `process_start_time_seconds` / `fault_active` / `http_requests_total` |
| `run_playbook` | 只读取证预案(`playbooks.yml`);mitigation 仅建议 | 上列只读工具 |
| `gather_diagnosis` | 一键串全链,带字段级证据链 | 上列只读工具 |

## 运行(宿主机 venv 形态,P3b 环境决策)

```bash
cd mcp/aiops
uv venv .venv && uv pip install "mcp==2.2.0"   # mcp 自带 uvicorn/starlette/sse-starlette
NO_PROXY="127.0.0.1,localhost" PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe server.py
# → http://127.0.0.1:18081  双传输 /sse 与 /mcp
```

前置:sims 监控栈在跑(`docker compose -f docker-compose.sims.yml up -d`)、Prometheus :9090
可达、宿主机 docker CLI 可用(query_logs 需要;容器形态不可行的实测见 docs/P3B.md)。

环境变量:`PROMETHEUS_URL`(默认 http://127.0.0.1:9090)、`AIOPS_PORT`(18081)、
`AIOPS_DOCKER_CONTAINER_MAP`(service→容器名映射,默认
`ykt=nova-sims-ykt-1,jiaowu=nova-sims-jiaowu-1`)。

## 验证

```bash
NO_PROXY="127.0.0.1,localhost" .venv/Scripts/python.exe tests/smoke_test.py http://127.0.0.1:18081
NO_PROXY="127.0.0.1,localhost" .venv/Scripts/python.exe tests/test_query_metrics_guard.py
NO_PROXY="127.0.0.1,localhost" .venv/Scripts/python.exe tests/aiops_demo.py   # 需 sims 栈在跑
```

## 排错

- **连不上 :9090**:sims 栈没起或系统代理拦截——加 `NO_PROXY="127.0.0.1,localhost"`。
- **query_logs 报"未找到 docker CLI"**:Docker Desktop 未启动;或你把 aiops 挪进了容器
  (容器内无 docker CLI/socket,weekly 容器实测 `NO_DOCKER_CLI`,见 docs/P3B.md 部署决策)。
- **list_alerts 返回"无告警规则"**:`alerts.yml` 未挂载或 prometheus 未重启加载;
  `curl :9090/api/v1/rules` 应非空。
- **fault_active 查不到注入**:容器重启后到首次注入前该序列不存在(已知限制,docs/P3B.md)。
