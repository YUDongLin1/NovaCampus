# 第三方组件与数据来源声明（Third-Party Notices）

本项目（NovaCampus / 智枢 Agent）以 MIT 许可证发布，本体代码版权归 © 2026 YUDongLin1 所有。
以下列出本项目**依赖、引用或分发**的第三方成果，以及各自的许可与来源。

---

## 1. 上游开源底座：Tencent WeKnora —— **不随本仓库分发**

| 项 | 说明 |
|----|------|
| 项目 | WeKnora |
| 版权 | Copyright (C) 2025 Tencent |
| 许可证 | **MIT License**，另含第三方组件声明 |
| 锁定版本 | **v0.8.2**（tag，commit `3e8b0bfc80b845b2d4b2ed683994748741450a97`，2026-09-24） |
| 上游地址 | <https://github.com/Tencent/WeKnora> |
| 上游许可文件 | `LICENSE`（含完整 MIT 正文 + 第三方组件条款）、`THIRD_PARTY_NOTICES.md` |

**分发说明**：本仓库**不包含** WeKnora 源码。`weknora/` 目录已被 `.gitignore` 完全排除，因此上游的 `LICENSE` 与 `THIRD_PARTY_NOTICES.md` **不在本仓库内**。如果你要使用 WeKnora 作为对比基线，请自行克隆并**同时遵守上游许可证与第三方组件条款**：

```bash
git clone --branch v0.8.2 https://github.com/Tencent/WeKnora.git weknora
```

WeKnora 的角色是**评测基线**（同语料对比「自研检索链路 vs 开源底座」），本项目不修改其源码，仅在本地通过 `docker-compose.override.yml` 挂载一份模型声明配置。

---

## 2. 语料与数据来源

### 2.1 高校公开政策文件（`corpus/clean/policy/`、`guide/`、`ops/`，共 40 篇）

- **来源**：西南交通大学官方网站及其各职能部门站点（`xg.swjtu.edu.cn`、`hospital.swjtu.edu.cn`、`bwc.swjtu.edu.cn`、`cwc.swjtu.edu.cn` 等）公开发布的通知、办法、规定，以及教育部公开规章。
- **可追溯性**：每篇 `.md` 的 frontmatter 均记录 `title` / `source_url` / `doc_date` / `category` / `tier`，可逐篇回溯到原始页面。
- **性质**：均为机构公开发布的行政规范性文件与办事指引，**不含个人信息**。经全量扫描，受控语料中手机号、身份证号、私人邮箱、真实个人姓名均为 **0 命中**。
- **版权态度**：机构公开文件通常不受著作权法保护或属于合理使用范围；若权利人对转载有异议，请联系我们，我们会立即移除对应文件。

### 2.2 部门联系表（`novaagent/novaagent/data/contacts.json`）

- **来源**：高校官网公开的「联系我们」类页面，**每条均带 `source_url`**。
- **内容**：7 个部门共 15 个**机构座机**与部门邮箱（如校医院医保办、保卫处值班、急救电话等）。
- **不含**任何私人手机号、私人邮箱或个人姓名。

### 2.3 第三方培训材料 —— **不随本仓库分发**

项目开发期曾使用以下已发表的辅导员培训材料作为本地演示语料：

- 《萌哥说案例分析》第一季、第二季
- 《谈心谈话训练题（辅导员职业能力培训材料）》

**这些材料不属于本项目，也不在本仓库内发行。** 其原文与切分产物位于 `corpus/raw/affairs/` 与 `corpus/clean/affairs/`，两个目录均已被 `.gitignore` 排除。

> ⚠ **已知待清理项**：上述材料的少量正文曾被复制进**受控的证据 JSON**（`docs/p4d/evidence/after/faithfulness_inputs.json`），这是 `.gitignore` 规则的漏口。清理方法与清单见 `PRIVACY-AUDIT.local.md` 的 P1-7 条目。

---

## 3. 运行时依赖

### 3.1 NovaAgent（`novaagent/pyproject.toml`）

| 包 | 版本约束 | 许可证 |
|----|----------|--------|
| FastAPI | `>=0.115` | MIT |
| Uvicorn | `>=0.30` | BSD-3-Clause |
| HTTPX | `>=0.28` | BSD-3-Clause |
| NumPy | `>=2.0` | BSD-3-Clause |
| pypdf | `>=5.0` | BSD-3-Clause |
| python-docx | `>=1.1` | MIT |
| mcp（官方 Python SDK） | `==2.2.0` | MIT |
| python-multipart | `>=0.0.9` | Apache-2.0 |
| LangGraph | `>=1.2,<2.0` | MIT |

传递依赖的完整清单与版本见 `novaagent/uv.lock`（锁文件已入库，保证可复现）。

### 3.2 MCP 服务与模拟系统

- `mcp/weekly/`：仅依赖 `mcp==2.2.0`（见其 Dockerfile 与 `pyproject`）。
- `mcp/aiops/requirements.txt`：`mcp==2.2.0`。
- `sims/requirements.txt`：`fastapi>=0.110,<1`、`uvicorn>=0.29,<1`、`prometheus-client>=0.20`、`psutil>=5.9`、`httpx>=0.27`。
- Docker 镜像：`python:3.12-slim`、`prom/prometheus:v2.53.0`、`grafana/grafana:11.1.0`，各自遵循其原始许可证。

### 3.3 前端

零构建，无 `package.json`、无第三方 JS 库。唯一的**外部资源**是 Google Fonts（`novaagent/web/index.html` 中引用的网页字体）。若你的部署环境无法访问 Google Fonts，页面会自动回退到系统字体，不影响功能。

### 3.4 模型服务（外部 API，非分发内容）

本项目通过 OpenAI 兼容接口调用第三方模型服务，默认指向：

- **阿里云百炼 DashScope**（对话模型 `qwen-flash`）—— <https://bailian.console.aliyun.com/>
- **硅基流动 SiliconFlow**（向量模型 `BAAI/bge-m3`、重排模型 `BAAI/bge-reranker-v2-m3`）—— <https://cloud.siliconflow.cn/>

模型权重与 API 均由上述服务商提供，适用其各自的服务条款。

---

## 4. 商标声明

「WeKnora」为腾讯公司的项目名称；「DeepSeek」「Qwen / 通义千问」「SiliconFlow / 硅基流动」「Grafana」「Prometheus」等为其各自权利人的商标或注册商标。

本项目仅为说明兼容性与数据来源而提及上述名称，**与这些权利人不存在隶属、赞助或背书关系**。

---

## 5. 免责声明

本项目为个人学习与作品集项目，**非任何高校的官方系统**，不代表任何机构的立场。仓库内出现的机构名称与联系信息仅用于演示检索与引用溯源能力，请以官方渠道发布的最新信息为准。
