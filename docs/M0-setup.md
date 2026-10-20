# M0 环境部署指引

> 状态(2026-09-27 更新):✅ WSL2 + Docker Desktop 已安装(引擎 29.8.0,镜像加速已生效);
> ✅ WeKnora v0.8.2 默认栈已部署且全部 healthy(前端 http://localhost,API 8080);
> ✅ `.env` 已配置并生效:Embedding/Rerank 走硅基流动(key 已验证有效),LLM 已切换为阿里云百炼 qwen-flash(OpenAI 兼容模式);
> ⏳ **唯一待办:`LLM_API_KEY` 当前粘贴的字符串无效,需回服务商控制台重新复制并确认已生效,再执行 `docker compose up -d app`(注意:改 .env 后不能用 restart,必须 up -d 重建才会重新读环境变量)**;
> ⚠️ 排错经验:文档"解析失败"但 docreader 阶段正常、embedding 阶段 401 = key 未加载进容器,先看 `docker exec WeKnora-app sh -c 'echo ${#EMBEDDING_API_KEY}'` 是否为 0。

## 1. 已就绪

| 项 | 结果 |
|----|------|
| Git | 2.54.0 ✅ |
| Python | 3.14.4 ✅(MCP Server 用) |
| Node | v24.15.0 + npm 11 ✅(前端定制用) |
| uv | 0.12.5 ✅(Python 依赖管理) |
| 内存 / 磁盘 | 15.6GB / E 盘剩余 1.7TB ✅ |
| GPU | 无(不影响:LLM 与 Embedding 均走云 API) |
| 网络 | GitHub 偶发超时(克隆需重试或开代理);DeepSeek API、DaoCloud 镜像加速可达 ✅ |
| WeKnora 源码 | `weknora/`,tag v0.8.2,4355 文件 ✅ |

## 2. 待办:安装 WSL2 + Docker Desktop(需要管理员权限)

以**管理员身份**打开 PowerShell,依次执行:

```powershell
# 1) 安装 WSL2(完成后需重启电脑)
wsl --install --no-launch

# 2) 重启后,安装 Docker Desktop
winget install Docker.DockerDesktop
# 或到 https://www.docker.com/products/docker-desktop/ 下载安装包

# 3) 启动 Docker Desktop,在 Settings → Resources → WSL Integration 勾选启用
```

**配置镜像加速**(国内拉取 WeKnora 镜像必需):Docker Desktop → Settings → Docker Engine,在 JSON 中加入:

```json
{
  "registry-mirrors": [
    "https://docker.m.daocloud.io",
    "https://docker.1ms.run"
  ]
}
```

然后 Apply & Restart,并用 `docker run --rm hello-world` 验证。

## 3. 配置模型 API

```bash
cd E:/AILearn/NovaCampus/weknora
cp .env.example .env
```

编辑 `weknora/.env`,至少填写以下项(模板内有逐项中文注释):

| 配置 | 建议值 | 说明 |
|------|--------|------|
| `LLM_MODEL_NAME` | `deepseek-chat` | 主力对话/推理模型 |
| `LLM_BASE_URL` | `https://api.deepseek.com` | 已测连通 |
| `LLM_API_KEY` | 你的 DeepSeek key | ⚠️ 不要提交到 git(.env 已被忽略) |
| `EMBEDDING_MODEL_NAME` | `BAAI/bge-m3` | 硅基流动免费档 |
| `EMBEDDING_BASE_URL` | `https://api.siliconflow.cn/v1` | |
| `EMBEDDING_API_KEY` | 你的硅基流动 key | |

> 备选:智谱 GLM(`LLM_PROVIDER` 支持智谱,v0.8.2 内置模型目录 27 家厂商),可在模型集成页并存,便于后续做"模型选型对比"的面试素材。

## 4. 启动与验收

```bash
cd E:/AILearn/NovaCampus/weknora
docker compose up -d          # 默认栈:frontend/app/docreader/postgres/redis/searxng/langfuse
docker compose ps             # 等待全部 healthy
```

验收清单(对应 PLAN.md P0):

- [ ] 浏览器打开 `http://localhost`(前端),注册管理员账号
- [ ] 上传 10 篇真实政策文档,解析完成
- [ ] 提问并得到**带引用来源**的回答
- [ ] Langfuse(`http://localhost:3000`,见 .env 中 LANGFUSE 段)中出现完整 trace
- [ ] `docker stats` 观察内存占用 <12GB(16GB 机器安全线)

## 5. 常见问题

- **GitHub 克隆慢/失败**:配置代理或重试;上游已克隆完成,后续同步用 `git -C weknora fetch --tags`。
- **镜像拉取超时**:确认第 2 节镜像加速已生效;仍失败可 `docker pull` 单个镜像重试。
- **内存不足**:确认 sandbox/neo4j/milvus/weaviate 等 profile 服务未启动(`docker compose ps` 里不该出现)。
