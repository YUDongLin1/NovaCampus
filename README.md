# 智枢 Agent(NovaCampus)

面向高校的企业级智能对话与运维 Agent:基于开源 RAG 平台 [Tencent WeKnora](https://github.com/Tencent/WeKnora)(锁定 v0.8.2)落地,通过 MCP 协议扩展自研工具,构建"知识库问答 + AIOps 智能诊断 + 辅导员周报助手"三位一体的校园智能体。

## 功能全景

| 能力 | 说明 | 服务对象 |
|------|------|----------|
| RAG 知识库问答 | 校规校纪、奖助学金、请假流程等政策文档的混合检索问答,带引用溯源 | 学生 / 辅导员 |
| 多级权限 | 校管理员 / 辅导员 / 学生 三级角色映射 WeKnora RBAC(owner·admin·contributor·viewer) | 全员 |
| AIOps 智能诊断 | 对接模拟校园系统(教务/一卡通)的 Prometheus 指标与日志,告警→取证→根因→中文诊断报告 | 校管理员 |
| 周报助手 | 碎片工作记录 → 分类整理(谈心/事务/活动/异常)→ 结构化周报 → 归档回灌知识库 | 辅导员 |
| 质量闭环 | 人工校验评测集(含权限边界/拒答用例)、Recall@k / 忠实度 / 拒答准确率、bad case 迭代、评测看板 | 项目自身 |

## 架构

```
┌─ 用户 ──────────────────────────────────────────────┐
│  学生(咨询)   辅导员(问答+周报)   校管理员(运维)  │
└──────┬──────────────────────────────────────────────┘
       │  Web(校园化主题+模拟统一认证登录页)
┌──────▼──────────────────────────────────────────────┐
│  WeKnora v0.8.2(RAG 问答 · ReAct Agent · RBAC)     │
│  ├─ 混合检索 + rerank + 引用溯源(pgvector)          │
│  ├─ Langfuse 全链路追踪                             │
│  └─ MCP Client:按需发现并调用外部 MCP 工具           │
└──┬──────────────────────┬───────────────────────────┘
   │ MCP(Streamable HTTP) │ MCP
┌──▼──────────────┐  ┌────▼─────────────────┐
│ AIOps MCP Server │  │ 周报 MCP Server       │
│ 查指标/日志/变更/ │  │ 碎片→分类→结构化周报  │
│ 预案 4~6 个工具  │  │ →归档回灌知识库       │
└──┬──────────────┘  └──────────────────────┘
┌──▼──────────────────────────────────────────────────┐
│ 模拟环境:教务/一卡通 Docker 模拟系统 + 故障注入      │
│ + Prometheus + Grafana                              │
└─────────────────────────────────────────────────────┘
```

## 仓库结构

```
NovaCampus/
├── docs/            # 计划、评测报告、决策记录
│   ├── PLAN.md      # 实施计划 v1.2(自研路线)
│   └── M0-setup.md  # WeKnora(评测基线)部署指引
├── novaagent/       # ★ 自研校园智能体(FastAPI + 混合检索 + RBAC + Agent 工具)
│   ├── novaagent/   #   config/db/rag/llm/agent/weekly_client/main
│   ├── web/         #   单页前端:登录/三角色/聊天/引用/知识库/周报
│   └── tests/       #   冒烟测试(权限边界 + RAG 引用 + 周报)
├── mcp/weekly/      # 周报 MCP Server(Python,被 NovaAgent 复用)
├── evals/           # 评测集、评测引擎、bad case 清单
├── sims/            # 模拟校园系统 + 故障注入脚本
├── corpus/          # 语料 + 脱敏脚本(入库前必跑)
├── reports/         # 阶段验收记录、对比数据
└── weknora/         # 开源底座(评测基线,git 忽略)
```

## 快速开始(NovaAgent)

```bash
cd novaagent
uv sync                                  # 安装依赖
# 需要 weekly MCP:docker compose -f docker-compose.weekly.yml up -d
uv run uvicorn novaagent.main:app --port 8900
# 打开 http://localhost:8900(演示账号 admin/counselor/student,密码 xxx123)
```

功能:三角色 RBAC(学生/辅导员/校管理员)、文档上传解析(txt/md/pdf/docx)、混合检索问答(向量+关键词 RRF+rerank,带 [n] 引用溯源)、周报助手(碎片→分类→周报→归档,经 MCP 协议调用)、权限边界拦截。

## 当前进度

- [x] 技术选型评估与计划评审(v1.0 → v1.1)
- [x] M0:环境检查、WeKnora v0.8.2 源码克隆与能力验证(RBAC 四级角色 / MCP Client / Langfuse / 27 家模型厂商)
- [ ] M0:Docker Compose 部署 + 模型 API 配置 → 带引用的可用问答
- [ ] P1-MVP(第 8 周末,简历可用版本):50 篇文档 + 三角色权限 + 评测集起步 + 周报工具 v1
- [ ] P2 评测深化 / P3 AIOps / P4 周报完整版 / P5 部署收尾

## 数据合规

语料来源为学校公开政策文档(记录来源 URL 与抓取时间)与本人辅导员工作记录;工作记录经脱敏脚本去除姓名/学号/联系方式后方可入库;仓库公开发布前执行脱敏自查清单。
