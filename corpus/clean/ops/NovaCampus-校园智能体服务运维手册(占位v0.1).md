---
title: NovaCampus 校园智能体服务运维手册(占位 v0.1)
source: Zcode 自建(P3 AIOps 前置占位)
origin_file: 本文件(corpus/clean/ops/)
category: ops
tier: Zcode 自建
sensitivity: low
status: 占位(P3 扩充完整版)
split_date: 2026-09-27
---

# NovaCampus 校园智能体服务运维手册(占位 v0.1)

> 本文为 P3 AIOps 前置占位手册,覆盖当前已部署服务的真实运维要点;模拟校园系统与故障注入的完整运维手册在 P3 扩充。

## 一、服务拓扑

| 服务 | 端口 | 说明 |
|------|------|------|
| NovaAgent(app) | 8900 | 自研智能体:REST API + 前端单页 |
| weekly-mcp | 18080(宿主机)/8000(容器内) | 周报 MCP Server(Streamable HTTP + SSE) |
| WeKnora(评测基线) | 80/8080 | 开源底座,frontend/app/docreader/postgres/redis 五容器 |

## 二、健康检查

- NovaAgent:`GET http://localhost:8900/api/health`,期望 `{"status":"ok","weekly_mcp":true}`;`weekly_mcp:false` 说明周报 MCP 长连接断开,重启 NovaAgent 进程即可重建。
- weekly-mcp:`docker compose -f docker-compose.weekly.yml ps`,容器应 Up;`curl http://localhost:18080/mcp` 返回 406 属正常(缺 Accept 头),说明 HTTP 层存活。
- WeKnora:`docker compose ps` 五容器应全部 healthy。

## 三、常见故障与处置

1. **NovaAgent 起不来/接口 500**:先看启动日志;缺配置项(LLM_API_KEY 等)会在 lifespan 直接报错;改过 `.env` 必须重建进程(环境变量仅在启动时读取)。
2. **对话报"per-response output limit"**:思考模式耗尽输出预算——会话关闭思考,或在智能体设置把"最大生成Token数"调大到 8192。
3. **文档解析失败但 docreader 阶段正常**:embedding 阶段 401 = key 未加载进容器,`docker exec WeKnora-app sh -c 'echo ${#EMBEDDING_API_KEY}'` 验证后 `docker compose up -d app` 重建(不是 restart)。
4. **weekly MCP 工具刷新失败**:WeKnora 走 SSE(`http://weekly-mcp:8000/sse`);404 说明容器还是旧镜像,`docker compose -f docker-compose.weekly.yml up -d --build` 重建。
5. **本机代理干扰**:系统代理(VPN)会把 Python 客户端访问 localhost 的请求转发出去返回 502;测试时设置 `NO_PROXY=127.0.0.1,localhost`。

## 四、升级与回滚

- NovaAgent:代码更新后重启进程;数据库为 SQLite(`data/agent.db`),升级前备份该文件即可回滚。
- weekly-mcp:镜像内仅 `server.py`,`--build` 重建即升级;数据卷 `./data/weekly` 持久化 SQLite 与归档周报。
- 回滚原则:配置(.env)与数据(卷)分离,任何升级先备份这两类。

## 五、日志要点

- NovaAgent:启动日志看 `weekly MCP connected` 与 `NovaAgent started` 两行;运行期关注 `tool call:`(工具调用)与 `ingested doc=`(入库)。
- weekly-mcp:uvicorn 访问日志;`Terminating session` 属正常会话回收。

> 完整版(P3):告警分级与响应、变更管理流程、值班与上报流程、与模拟校园系统故障注入联动的处置预案。
