# 贡献指南（Contributing）

感谢你愿意参与 NovaCampus（智枢 Agent）。本文档面向第一次给本项目提 PR 的人，尽量写成「照着做就行」。

---

## 一、先跑起来

提交之前，请先在本地把服务跑通一遍（完整步骤见 [README](README.md) 的「快速开始」）。最小闭环：

```bash
# 1. 装依赖
cd novaagent
uv sync

# 2. 配密钥（至少填 LLM_API_KEY 与 EMBEDDING_API_KEY）
cp .env.example .env

# 3. 先起周报 MCP（不启动它，NovaAgent 会启动失败）
cd ../mcp/weekly && uv venv .venv && uv pip install "mcp==2.2.0"
WEEKLY_PORT=18080 WEEKLY_HOST=127.0.0.1 .venv/Scripts/python.exe server.py

# 4. 另开一个终端起主服务
cd /path/to/NovaCampus/novaagent
uv run uvicorn novaagent.main:app --port 8900
```

打开 <http://127.0.0.1:8900> 能看到登录页即为成功。

---

## 二、改代码前请知道的几件事

### 1. 前端是零构建的

`novaagent/web/` 下是原生 HTML/CSS/JS，**没有打包步骤、没有 `package.json`**。改完刷新浏览器即可，不要引入构建工具链。

### 2. 密钥纪律（硬性）

- 不要把任何真实 API Key 写进代码、测试、文档、日志或提交信息。
- 新增需要密钥的测试时，用环境变量注入，并在报告里只写「来源标签」（例如 `llm_key_source=session_env`），**不要写值**。
- 仓库里已有这种做法的范例：`novaagent/novaagent/config.py` 的 `key_source()` 只返回值来自哪一层，永不返回值本身。请沿用。
- 提交前自查：`git diff --cached | findstr /i "sk- api_key"`（Windows）/ `git diff --cached | grep -iE "sk-|api_key"`。

### 3. 数据合规红线

- **不要**把真实的学生信息（姓名、学号、手机号、身份证号、家庭经济困难记录、心理咨询记录）写进仓库任何位置——包括测试用例、截图、日志与证据文件。
- 第三方已发表材料（培训案例、教材、公众号文章）**不得复制进仓库**，即使放在 `docs/` 或证据 JSON 里也不行。
- 演示数据请用明显的占位符（如 `姓名1`、`13800001111`）。

### 4. 改动要有证据

本项目的既有风格是「结论必须有可复现的证据」。涉及检索/问答/拒答逻辑的改动，请在 PR 描述里附上：

- 你跑的命令
- 实际输出（关键行即可）
- 改动前后的对比数字

---

## 三、开发流程

```bash
# 1. 从最新 master 切分支
git checkout master && git pull
git checkout -b feat/your-topic        # 或 fix/  docs/  test/

# 2. 改代码 —— 保证工作区只有一个写入者，避免与他人同时改同一批文件

# 3. 跑测试
cd novaagent
NO_PROXY="127.0.0.1,localhost" .venv/Scripts/python.exe tests/smoke_test.py          # 冒烟（需服务与周报 MCP 在跑）
NO_PROXY="127.0.0.1,localhost" .venv/Scripts/python.exe ../evals/run_evals.py --base http://127.0.0.1:8900

# 4. 提交
git add -A && git commit -m "feat(scope): 一句话说清做了什么"

# 5. 推送并开 PR
git push -u origin feat/your-topic
```

### 提交信息约定

采用 `type(scope): 摘要`，摘要用中文或英文均可：

| type | 用途 |
|------|------|
| `feat` | 新功能 |
| `fix` | 修缺陷 |
| `docs` | 只改文档 |
| `test` | 只改测试 |
| `refactor` | 重构，不改变行为 |
| `chore` | 构建、依赖、配置 |

### PR 检查清单

提交 PR 前请逐条确认：

- [ ] 本地能跑通（服务能启动、页面能打开、冒烟测试通过）
- [ ] 没有提交任何真实密钥或 `.env` 文件
- [ ] 没有引入真实个人数据或第三方版权材料
- [ ] 新功能有对应的测试或至少一段可复现的手工验证记录
- [ ] 改了环境变量 → 同步更新 `novaagent/.env.example`
- [ ] 改了用户可见行为 → 同步更新 `README.md`
- [ ] 提交信息符合上面的约定

---

## 四、报告问题

- 功能缺陷 / 使用疑问：用 GitHub Issues，附上你的操作系统、Python 版本、完整报错与复现步骤。
- 安全漏洞：**不要开公开 issue**，请按 [SECURITY.md](SECURITY.md) 的私密通道报告。

## 五、行为准则

参与本项目即表示你同意：保持友善与就事论事，不对他人做人身评价；不接受任何形式的骚扰与歧视言论。维护者有权删除不当内容并拒绝不合规的贡献。
