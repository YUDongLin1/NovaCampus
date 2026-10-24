# 周报 MCP Server(P1)

辅导员碎片工作记录 → 分类聚合 → 结构化周报草稿 → 归档回灌知识库。
设计原则:**分类智能交给 WeKnora 里的 Agent(LLM),本服务只做确定性存取与渲染**,工具职责单一、便于评测。

## 架构

- 传输:Streamable HTTP(`http://<host>:8000/mcp`),mcp Python SDK 2.2.0
- 存储:SQLite(`$WEEKLY_DATA_DIR/weekly.db`),归档周报另存 Markdown 文件
- 分类体系:谈心谈话 / 事务办理 / 活动组织 / 异常突发 / 其他(PLAN.md P1 定义)

## 工具清单(7 个)

| 工具 | 用途 | 备注 |
|------|------|------|
| `add_fragment` | 记录一条工作碎片 | `category` 由 Agent 判断后传入,非法值回落"其他" |
| `list_fragments` | 按发生日期范围列出碎片 | 日期闭区间 |
| `delete_fragment` | 删除记错的碎片 | 软删除 |
| `render_weekly_report` | 渲染周报 Markdown 草稿 | `end_date` 缺省取同周周日 |
| `archive_report` | 归档定稿(SQLite + .md 文件) | 归档文件后续回灌知识库 |
| `list_reports` | 列出已归档周报 | 支持日期重叠过滤 |
| `read_report` | 读取归档周报全文 | 供前端查看与回灌 |

## 部署与测试

```bash
# 部署(加入 weknora 网络)
docker compose -f docker-compose.weekly.yml up -d --build

# 冒烟测试(宿主机调试端口 18080)
cd mcp/weekly && uv venv .venv && uv pip install mcp
NO_PROXY="127.0.0.1,localhost" .venv/Scripts/python.exe tests/smoke_test.py http://127.0.0.1:18080
```

## 在 WeKnora 中注册(一次性)

1. 确认 `weknora/.env` 已有 `SSRF_WHITELIST=weekly-mcp`(内网 MCP 主机名需过 SSRF 校验),且 app 容器已重建生效
2. WeKnora 前端 → 工具箱 → MCP 服务 → 添加:
   - **传输类型选 Streamable HTTP**,URL:`http://weekly-mcp:8000/mcp`(2026-07-28 协议无状态端点;
     旧 SSE 传输 `/sse` 已下线,不要再选 SSE)
   - 按向导完成工具发现与启用(建议 5 个工具全开)
3. 试用 prompt:"帮我记一条今天的碎片:和大二的小王谈了补考压力,已约心理中心" → "把本周的碎片整理成周报" → 确认后让它归档

## 排错

- 客户端 502/连不上:检查系统代理是否拦截了 localhost(本机代理需加 `NO_PROXY=127.0.0.1,localhost`);容器间访问不受宿主机代理影响
- 注册被拒:看 app 日志 `docker logs WeKnora-app | grep -i mcp`;确认 SSRF 白名单已生效(容器内 env)
- 归档文件在宿主机 `data/weekly/reports/`(volume 挂载),回灌知识库直接上传该目录
