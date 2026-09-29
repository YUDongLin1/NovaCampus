# P3a 模拟校园系统 + 故障注入 + Prometheus/Grafana 监控栈

> 分支 `task/P3a-sims`,持棒 Zcode。规格见 `docs/TASKS.md` P3a 条目。
> 定位:P3 AIOps 地基——为 P3b(AIOps MCP Server 查询 Prometheus)/P3c(NovaAgent 诊断链)/P3d(注入→自动定位录屏)提供可观测的被诊断对象。**一卡通(ykt)是故障叙事主角**。

## 一、架构

```
docker-compose.sims.yml(仓库根,项目名 nova-sims)
├── jiaowu   教务系统(模拟)  sims/jiaowu/app.py   宿主 9101 → 容器 8000,池 size=8
├── ykt      一卡通系统(模拟) sims/ykt/app.py      宿主 9102 → 容器 8000,池 size=10(故障主角)
│     ↑ 两者共用 sims/common.py(指标埋点/模拟连接池/故障注入器)与 sims/Dockerfile(ARG SERVICE)
├── prometheus  prom/prometheus:v2.53.0  宿主 9090,抓 jiaowu:8000 / ykt:8000 的 /metrics(5s)
└── grafana     grafana/grafana:11.1.0   宿主 3000,预置数据源 prom-sims + 总览盘「SIMS 校园模拟系统总览(P3a)」(uid sims-overview)
```

- 两个服务**内置自压测**(每 2s 轮询一个业务端点),让指标有基线流量;
- 业务端点都经 `pool_connection()` 取连接:等待超时(`POOL_WAIT_SECONDS`,默认 2s)→ **HTTP 503**,错误率可观测;
- 故障注入走服务内 `/debug/fault/{mode}`(chaos-test API),`sims/fault_inject.py` 是宿主机 CLI(纯标准库),触发后轮询状态到自动恢复。

## 二、指标清单(两服务同款,`job` 由 Prometheus 注入,`service` 恒等)

| 指标 | 类型 | 说明 |
|---|---|---|
| `http_requests_total{method,path,status}` | Counter | 按路由模板计(path 是模板如 `/api/card/{card_id}/balance`,防基数爆炸;`/metrics` 自身不计) |
| `http_request_duration_seconds{path}` | Histogram | 请求耗时 |
| `app_db_pool_size{service}` | Gauge | 池容量(ykt=10,jiaowu=8) |
| `app_db_pool_in_use{service}` | Gauge | 当前占用连接数 |
| `app_db_pool_waiting{service}` | Gauge | 排队等待连接的请求数 |
| `app_db_pool_wait_seconds{service}` | Histogram | 获取连接等待耗时(含注入器自身获取;`_sum` 求速率=每秒消耗在等待上的秒数) |
| `process_cpu_percent` | Gauge | psutil 每 2s 轮询进程 CPU(多核 busy 可 >100%) |
| `fault_active{type}` | Gauge | 1=该故障注入活跃窗口(pool_exhaust / cpu_spike) |

业务端点:jiaowu `GET /api/courses`、`GET /api/grades/{sid}`、`POST /api/enroll`;ykt `GET /api/card/{cid}/balance`、`POST /api/card/pay`(持连接 0.3~0.6s 模拟对账写库,池耗尽的放大器)、`GET /api/card/{cid}/transactions`。另各有 `GET /health`、`GET /metrics`、`POST /debug/fault/{mode}`、`GET /debug/fault/status`。

## 三、故障注入(CLI)

```bash
# 连接池耗尽:服务进程内占满全部连接,持 60s 后自动归还(期间业务请求排队→等待↑→503↑)
python sims/fault_inject.py --target ykt --mode pool_exhaust --duration 60
# CPU 尖峰:进程内多线程 busy-loop(sha256 大缓冲释放 GIL,可吃满多核),到点自动恢复
python sims/fault_inject.py --target ykt --mode cpu_spike --duration 30
# 提前取消:--duration 0;仅触发不等待:--no-wait;目标服务地址覆盖:--base http://...
```

设计说明:`pool_exhaust` 必须在服务进程内执行(外部压测无法确定性地"持住"服务端池连接),CLI 只负责触发与观察;`cpu_spike` 同理(busy-loop 必须跑在被观测进程里)。这就是 `/debug/fault/*` 的存在理由——它是显式的 chaos-test API,不是后门:不写库、无状态、到期自恢复。

## 四、运行

```bash
docker compose -f docker-compose.sims.yml up -d --build   # 首次构建约 2~5 分钟
curl http://127.0.0.1:9090/api/v1/targets                  # jiaowu/ykt 应均 up
# Grafana: http://127.0.0.1:3000 → SIMS 文件夹 →「SIMS 校园模拟系统总览(P3a)」
# 登录 admin/simsadmin123(也开了匿名 Viewer)
```

**镜像/网络注记(国内环境)**:
- Docker Hub 镜像经 daemon.json 的 registry-mirrors 拉取(本机已配 docker.m.daocloud.io 等);若失败,改用可用的 mirror 前缀或代理后再 `docker compose pull`;
- 应用镜像内 pip 默认走清华 PyPI 镜像(`sims/Dockerfile` 的 `ARG PIP_INDEX_URL` 可覆盖,如 `--build-arg PIP_INDEX_URL=https://pypi.org/simple`);
- 端口占用:9090/3000/9101/9102 与 WeKnora 栈(80)、weekly MCP(18080)、NovaAgent(8900)无冲突。

## 五、验收记录(2026-09-28,证据在 `docs/p3a/evidence/`)

| 步骤 | 结果 | 证据 |
|---|---|---|
| compose up -d --build | 4 容器 Up | `docker ps`:`nova-sims-jiaowu-1/-ykt-1/-prometheus-1/-grafana-1` |
| targets 双 up | jiaowu up / ykt up | `prometheus_targets.json` |
| 基线 promql | 池 in_use=0、请求速率 ~0.45/s、**5xx 速率空**、CPU ~0.5%、等待 ~0 | `baseline_promql.txt` |
| 注入 `ykt pool_exhaust 60s` | CLI 逐 5s 轮询:in_use **恒 10**、waiting 0/1 交替,t+60s active=False、in_use=0 **自动恢复** | `fault_inject_ykt_pool_exhaust_60s.log` |
| 注入中 promql(t+25s) | `app_db_pool_in_use=10`(利用率 **100%**)、5xx 速率 **0.204/s**、等待速率 **0.56 s/s**、等待 P95 4.85s、`fault_active=1` | `fault_pool_exhaust_promql.txt` |
| 恢复后 promql | `fault_active=0`、in_use=0、**5xx 速率=0**、等待速率回落 ~0 | `recovery_promql.txt` |
| 注入 `ykt cpu_spike 30s` | CLI 留痕证明注入窗口:`active=True` 持续 t+3s~t+27s、**t+30s active=False 自动恢复**;CPU 峰值见 Grafana 截图 `process_cpu_percent{ykt}` 升至 **~1700%**(jiaowu 全程 ~0.5% 对照),恢复后回落 ~1% | `fault_inject_ykt_cpu_spike_30s.log`(窗口/恢复)、`grafana_overview_fault_spikes.png`(峰值)、`cpu_spike_recovery_promql.txt`(恢复后 jiaowu 0.5 / ykt 1) |
| Grafana 总览盘 | 6 面板全部呈现尖峰:两次 100% 池饱和平台、5xx 尖峰、P95 跳至 ~2.4s、等待 ~5s、CPU ~1700%、注入窗口标记;jiaowu 对照平坦 | `grafana_overview_fault_spikes.png` |
| 池饱和历史(query_range 12m) | `app_db_pool_in_use` 时间线两段 10 平台,前后为 0 | `cpu_spike_recovery_promql.txt` 尾部 |

## 六、实现纪要(Review 关注点)

1. **构建期修复的两个缺陷**:① Dockerfile CMD 的 `${SERVICE}` 运行时为空(只 ENV 了 SIM_SERVICE)→ uvicorn 收到 `.app` 相对导入崩溃——补 `ENV SERVICE=${SERVICE}`;② 业务端点 `pool.acquire()` 在 try 外,PoolTimeout 逃逸成 500 且 path 标签是原始 URL——抽 `pool_connection()` 上下文管理器统一转 **503** + finally 归还,中间件异常分支也改用路由模板。
2. **503 vs 500 语义**:池等待超时=资源型故障=503(错误率面板的 `status=~"5.."` 同时覆盖两者,细分看 status 标签)。
3. `app_db_pool_wait_seconds` 直方图含注入器自身的获取等待(exhaust 开始时占满 10 连接的过程),故注入起始有短暂高 P95,属真实等待数据,证据注记见第五节。
4. 自压测/指标埋点挂在 FastAPI lifespan 上(ykt/jiaowu 同构);`/metrics` 不计入请求指标以免抓取流量污染。
5. Grafana 面板 PromQL 与本文件第五节验收查询一致(错误率面板含 5xx 速率与总速率两序列;排队深度面板叠加 `fault_active` 注入窗口)。

## 七、Review 修正与已知缺口(Qoder 2026-09-28)

1. **证据入库缺口(已修)**:`.gitignore` 的 `*.log` 规则会静默排除 `docs/p3a/evidence/` 下两份 CLI 注入日志——本节表格引用它们,但新克隆仓库里没有。已加 `!docs/p3a/evidence/*.log` 例外并补提交。**教训:落盘 ≠ 入库,Review 必须 `git diff --name-status` 与文档引用逐条对账。**
2. **CPU 峰值出处修正(已改)**:原第五节把 `1650.5%` 归给 CLI 日志与 promql 文件,但该 CLI 只轮询 `/debug/fault/status`(返回池状态与 `active`,**不含 CPU**),promql 文件记的是**恢复后**值。峰值实际只有 Grafana 截图可证,故改为"~1700%(见截图)"。数字方向无误,引用链此前不成立。
3. **工具缺口(未修,留给 P3b 前)**:`sims/fault_inject.py` 无法自证 `cpu_spike` 效果——轮询循环应同时从 `/metrics` 抓 `process_cpu_percent` 打印,使 CPU 注入留下文本峰值证据。改动小但需 Docker 在跑才能验证,故未盲改。
4. **本机 Docker Desktop 未常驻**:Review 时守护进程已停,4 端口(9090/3000/9101/9102)不可达,故本次为**证据复核**而非实时复跑;实时复跑并入 P3b 第一步(反正要查 Prometheus)。

