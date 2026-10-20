# 开源前隐私与敏感信息清理 —— 汇总清单

> 生成时间：2026-10-20
> 发布主体仓库：`E:/AILearn/NovaCampus/NovaCampus/NovaCampus`（独立 git 仓库，188 提交 / 710 文件）
> 外层 `E:/AILearn/NovaCampus` 为旧工作副本（186 提交 / 687 文件），已同步清理但**不作为发布主体**

---

## 〇、总体结论

| 检查项 | 状态 | 说明 |
|---|---|---|
| 工作区敏感信息 | ✅ 已清零 | 全仓扫描 0 命中 |
| 硬编码凭据 | ✅ 已改造 | 全部改为环境变量注入 |
| `.gitignore` 覆盖 | ✅ 已补全 | 内层 341 行 / 外层 357 行，误伤 0 |
| 知识库/数据文件 | ✅ 未入库 | 仅 45 个有意入库的公开语料与模板 |
| Git 历史 | ✅ 已重写 | 188 提交全部重写，敏感项 0 残留 |
| 仓库可发布性 | ✅ 可发布 | 结构完整，功能无损 |

---

## 一、需忽略的文件与目录清单

### 1.1 已在 `.gitignore` 中（内层 341 行 / 外层 357 行）

| 类别 | 规则 | 覆盖对象 |
|---|---|---|
| 环境变量 | `.env` / `.env.*` / `*.env.local` / `*.env.*.local` | 所有本地密钥载体 |
| 凭据命名 | `*.secret.yaml` / `*.secret.yml` / `.aws/` / `.netrc` / `.npmrc` / `.pypirc` / `.docker/config.json` | 工具链凭据 |
| 证书私钥 | `*.pem` / `*.key` / `*.crt` / `*.cer` / `*.der` / `*.csr` / `*.p7b` / `*.p8` | TLS/签名材料 |
| 向量索引 | `*.faiss` / `*.hnsw` / `*.pkl` / `*.npy` / `*.index` / `*.idx` / `*.vectordb/` | RAG 索引产物 |
| 数据库 | `*.db` / `*.sqlite*` / `*.dump` / `dump.sql` / `*.sql.gz` | 运行期数据 |
| 归档包 | `*.zip` / `*.tar` / `*.tgz` / `*.7z` / `*.rar` | 打包产物 |
| 依赖形态 | `.pnpm/` / `.yarn/cache` / `__pypackages__/` | 依赖缓存 |
| 工具链 | `.pyre/` / `.cache/` / `*.eslintcache` / `.mypy_cache/` / `*.pytest_cache/` / `*.ruff_cache/` | 各类缓存 |
| 密钥管理 | `.secrets-store/` / `*.age` / `*.sops.yaml` / `.trivy/` / `*.sarif` | 密钥与扫描报告 |
| 数据目录 | `data/` / `novaagent/data/` / `corpus/raw/affairs/` / `corpus/clean/affairs/` / `mcp/weekly/data-weekly/` / `weknora/` | 本地/受限数据 |

### 1.2 外层仓库专属

| 规则 | 作用 |
|---|---|
| `/NovaCampus/` | 排除嵌套的发布主体副本（含其 `.git`、`weknora/` 142MB、`.env`、运行数据） |
| `/NovaCampus-*/` | 排除同类嵌套副本 |
| `/*_worktree/` | 排除 linked worktree 目录 |

> 生效验证：`git ls-files --others --exclude-standard` = **0**；`git ls-files -i -c --exclude-standard` = **0**（无误伤）。

### 1.3 库内有意保留的数据（确认安全）

| 路径 | 数量 | 保留理由 |
|---|---|---|
| `corpus/clean/` | 40 篇 | 学校**公开发布**的政策文件，35 篇带 `source_url` 可核验 |
| `evals/seed_corpus/` | 4 篇 | 评测种子语料 |
| `novaagent/.env.example` | 1 | 纯模板，值为空 |

> 库内**无任何** `.db`/`.sqlite`/`.faiss`/`.npy`/`.pkl`/模型权重/私钥/证书文件。

---

## 二、需替换为环境变量的凭据位置清单

> 只标注文件与行号，不回显任何明文。

### 2.1 已完成的改造（提交 `3683a70` / `db74724` / `73b4c31`）

| 位置 | 类型 | 改造方式 |
|---|---|---|
| `novaagent/novaagent/config.py` — `demo_password()` / `demo_passwords()` | 演示账号口令 | 函数式读取 `NOVA_SEED_<ROLE>_PASSWORD` → 回退 `NOVA_DEMO_PASSWORD`；**调用时**求值，避免 import 快照 |
| `novaagent/novaagent/config.py` — `PASSWORD_HASH_ITERATIONS` | KDF 迭代数 | `env("PASSWORD_HASH_ITERATIONS", "200000")` |
| `novaagent/novaagent/config.py` — `PASSWORD_HASH_LEGACY_ENABLED` | 旧哈希开关 | `env("NOVA_LEGACY_PASSWORD_HASH") == "1"` |
| `novaagent/novaagent/db.py` — `seed_users()` | 建号口令 | 实时读环境变量；未配置则跳过并打印指引，**不创建默认账号** |
| `novaagent/novaagent/db.py` — `_hash_password()` | 口令哈希 | `pbkdf2_hmac("sha256", pw, salt, iterations)`，逐用户随机盐 |
| `novaagent/novaagent/db.py` — `_migrate()` | 盐列迁移 | 幂等 `ALTER TABLE users ADD COLUMN password_salt` |
| `docker-compose.sims.yml:52-56` | Grafana 管理口令 | `${GRAFANA_ADMIN_PASSWORD:?必须显式设置}`（未设置则容器拒绝启动） |
| `docker-compose.sims.yml:53` | 匿名 Viewer | `${GRAFANA_ANONYMOUS_ENABLED:-false}`（默认关闭） |
| `mcp/weekly/server.py:564` | MCP 监听地址 | `os.environ.get("WEEKLY_HOST", "127.0.0.1")` |
| `mcp/aiops/server.py:701` | MCP 监听地址 | `os.environ.get("AIOPS_HOST", "127.0.0.1")` |
| `sims/jiaowu/app.py:133-138` | 模拟栈监听 | `os.environ.get("SIMS_HOST", "127.0.0.1")`（本次新增） |
| `sims/ykt/app.py:132-137` | 模拟栈监听 | 同上（本次新增） |
| `corpus/fetch_public_pages.py` — `do_import()` | 抓取登录口令 | 读 `NOVA_SEED_COUNSELOR_PASSWORD` / `NOVA_DEMO_PASSWORD`，未配置则 `return 2` |
| 33 个脚本 | 演示口令字面量 | 统一改用 `novaagent/tests/_demo_creds.py` 的 `demo_password(role)` |
| `novaagent/.env.example:145-170` | 配置模板 | 追加演示账号、KDF 参数、Grafana、监听地址占位 |

**口令哈希强度**：由 `sha256(固定全局盐)` 升级为 **PBKDF2-HMAC-SHA256 + 16 字节随机盐 + 200000 轮**，逐用户独立。

### 2.2 ⚠️ 需你本人处理（涉及外部系统，报告不代做）

| 位置 | 操作 |
|---|---|
| `novaagent/.env` | **轮换**阿里云百炼 `sk-ws-…`、硅基流动 `sk-zak…`、OpenRouter `sk-or-v1-…` 三把 LLM 密钥 |
| `novaagent/.env.test` | **删除**（测试环境不需要真实密钥） |
| `weknora/.env` | **重新生成** `JWT_SECRET` / `SYSTEM_AES_KEY` / `SYSTEM_SIGNING_KEY` |
| `weknora/.env` | 修改 `DB_PASSWORD` / `REDIS_PASSWORD`（当前为上游示例默认值） |

> 这些文件均在 `.gitignore` 覆盖内、从未进入 Git 历史，但**本机磁盘上仍是明文**，且密钥一旦泄露需在服务商侧作废。

---

## 三、需从历史中清理的问题清单

### 3.1 已执行的历史重写

对**内层（发布主体）与外层（旧副本）双仓库**执行 `git filter-repo`，全部 186 + 186 提交完成重写。下表中的敏感项以**类型化描述**列出，命中数取自改写前备份库（`E:/AILearn/_prepublish_backup_20261020/git_pre_rewrite_inner.git`）的实测统计：

| 敏感内容（类型） | 清理结果 |
|---|---|
| 本机 Windows 账户名 | ✅ 0（200 处，覆盖 4 种路径形态 + 裸词兜底） |
| 真实内部学工数据目录 | ✅ 0（231 处，覆盖 3 种路径形态） |
| 官网联系块中的经办人姓名 | ✅ 0（3 处，全部构成"国际部"联系块） |
| 真实城市名 | ✅ 0（12 处） |
| 机构联络邮箱 | ✅ 0（8 处 → 掩码为 `xxx@swjtu.edu.cn`，保留域名可读性） |
| 第三方版权材料正文 | ✅ 0（替换为占位说明，保留可核验性） |
| 真实学生咨询原话 | ✅ 0（改写为脱敏版本） |
| 单位名 + 岗位 + 求职意图（7 种表述变体） | ✅ 0 |
| 独立求职表述（含"目标 + 求职 + 岗位"等变体） | ✅ 0（64 处） |
| 提交信息中的演示口令 | ✅ 0 |

> 替换采用**分层策略**：同一敏感词在「代码语义位置」（如质量门检测正则、测试夹具）保留，在「历史叙述位置」替换 —— 避免功能性回归。

### 3.2 重写过程中发现并规避的三个坑

1. **`literal:` 按原始字节匹配，不解释反斜杠转义**
   首轮规则写成了**双反斜杠**形态（两个 `0x5C` 字节），而历史中实际形态为：账户名 200 处中单反斜杠 47 / 正斜杠 92 / git-bash 57 / 双反斜杠仅 4；数据目录 231 处中单反斜杠 228 / 双反斜杠 2 / 正斜杠 1。
   → 首轮规则只匹配到双反斜杠那极小部分，绝大多数形态漏网；改用 Python `bytes([0x5C])` 显式构造真实字节，并为每种形态各写一条规则 + 裸词兜底。

2. **表达式文件中的 `#` 注释行会被当成替换规则**
   `get_replace_text()` **不跳过**注释行（只有 `get_paths_from_file()` 才跳），首轮把全仓 `#` 注释替换成 `***REMOVED***`，污染 98 处 `.gitignore` / 156 处 `README`。
   → 重写为**零注释行**的纯规则表。

3. **不可达对象不会自动清除**
   `git gc` / `git repack` 后旧 blob 仍物理存在于 packfile 中（因为 linked worktree 的 `index` 缓存了旧 sha）。
   → 最终用 `git init --bare` + `fetch --no-tags` 导出**纯可达对象**的新库并替换 `.git`。

4. **不可达 blob 需二次导出清除（本轮新增）**
   汇总清单本身在首次重写**之后**才提交，其正文若含真实字面量，等于把已清除的敏感词重新引入当前历史。
   → 本轮已泛化报告正文，并对该提交再次执行「纯可达对象导出」流程，物理清除含字面量的旧 blob。

### 3.3 有意保留（不构成泄露）

| 内容 | 位置 | 保留理由 |
|---|---|---|
| 4 个合成演示口令（`admin`/`counselor`/`student`/`simsadmin` 前缀 + 数字后缀） | `novaagent/novaagent/main.py:432`（质量门正则）、`novaagent/tests/smoke_test.py:156`（测试夹具）、`docs/p4b/evidence/`（复现命令） | 这些值是**合成演示口令**，且是**质量门检测规则的语义组成部分** —— 替换会直接破坏检测逻辑与单测断言（功能性回归）。已在提交信息中替换。 |
| 机构域名与校名 | `corpus/MANIFEST.md`、`THIRD_PARTY_NOTICES.md`、40 篇公开政策语料 | 学校公开域名，语料本身即公开发布文件，保留可核验性 |
| 2 个手机号占位符 | `novaagent/tests/smoke_test.py` | 质量门测试夹具（文档明确要求用"明显的占位符"） |
| 2 个身份证号串 | `novaagent/novaagent/main.py` 身份证检测用例 | **GB11643 校验位无效**，为合成数据（已用校验算法逐位验证） |
| 2 个 `sk-` 负样本串 | `novaagent/novaagent/main.py` | 密钥泄漏检测的负样本（故意构造） |

### 3.4 邮箱 / 手机号 / 身份证 / IP 深度扫描结论

> 扫描口径：`git cat-file --batch-all-objects --batch` 全对象流式扫描（blob + tree + commit + tag），正则加数字/字符边界，避免把长数字串误判为手机号或身份证。

| 模式 | 命中 | 结论 |
|---|---|---|
| 邮箱 | 389 处 / 5 值 | 377 = GitHub noreply（作者身份，安全）；9 = 机构邮箱（已掩码）；1 = 第三方平台文档示例地址；2 = 哈希片段误报 |

> 说明：上表为**本报告泛化后**的终态统计。首版报告曾直接写出机构邮箱原值与平台示例地址，导致这些字面量随报告重新进入历史 —— 这正是第 3.2 节第 4 条记录的"报告自身回归"问题，现已消除。
| 手机号 | 29 处 / 14 值 | **全部误报**：12 个值为 PyPI wheel URL 的 SHA256 片段，2 个值为测试夹具占位符 |
| 身份证 | 5 处 / 2 值 | 全部为质量门拦截测试夹具，**GB11643 校验位无效** |
| 非回环 IP:端口 | **0** | ✅ |
| 回环 IP:端口 | 60 个去重值 | 全部为 `127.0.0.1`（本地回环） |
| GitHub token / AWS key / 私钥块 / SSH 私钥 / JWT | **0** | ✅ |
| 真实 API Key（`sk-ws-`/`sk-zak`/`sk-or-v1-`） | **0** | ✅ 从未入库 |

### 3.5 作者身份

188 次提交的 author/committer **全部**为 `YUDongLin1 <155050346+YUDongLin1@users.noreply.github.com>` —— GitHub noreply 格式，**不泄露真实邮箱**。已附带 `mailmap` 固化。

---

## 四、建议的发布前验证步骤

### 第 1 步：本地最终验证（已执行，全部通过）

```bash
cd E:/AILearn/NovaCampus/NovaCampus/NovaCampus

# 结构完整性
git rev-list --all --count          # 期望 188
git ls-files | wc -l                # 期望 710
git status --porcelain              # 期望空（工作区干净）

# 敏感项归零（覆盖 blob + tree + commit + tag + 文件名）
# 词表放在仓库外，避免验证脚本本身把敏感字面量写回仓库
WORDS=E:/AILearn/_prepublish_backup_20261020/sensitive-words.txt
git cat-file --batch-all-objects --batch | grep -a -F -f "$WORDS" | wc -l   # 期望 0
git log --all --format='%B' | grep -a -F -f "$WORDS" | wc -l                # 期望 0

# 忽略规则无误伤、无遗漏
git ls-files -i -c --exclude-standard        # 期望 0（无误伤）
git ls-files --others --exclude-standard    # 期望 0（无遗漏）

# 库内无数据文件 / 私钥
git ls-files | grep -iE "\.(db|sqlite|faiss|pkl|npy|onnx|pt|pem|key|crt)$"   # 期望空
```

### 第 2 步：功能冒烟（必做）

```bash
# 1) 复制 .env.example 为 .env，填入自己的 NOVA_DEMO_PASSWORD
# 2) 启动
python -m novaagent.novaagent.main
# 3) 用 .env 中的口令登录，确认：
#    - 未配置 NOVA_DEMO_PASSWORD 时**不应创建任何账号**（安全默认值）
#    - 配置后按角色建号，且 NOVA_SEED_*_PASSWORD 优先级高于 NOVA_DEMO_PASSWORD
# 4) 跑测试
python -m pytest novaagent/tests -q
```

### 第 3 步：推送前的最后一道防线

```bash
# 用 GitHub 官方敏感信息扫描（建议先推到私有仓库试跑）
# 或本地用 gitleaks
gitleaks detect --source . --redact -v
```

### 第 4 步：推送与协作方同步

```bash
# 首次推送（历史已重写，无需 force）
git remote add origin <your-repo-url>
git push -u origin --all
git push origin --tags

# ⚠ 所有已有克隆必须重新克隆（历史 hash 全变，旧克隆仍含敏感内容）：
#    git clone --depth=1 <your-repo-url>   # 推荐浅克隆
```

### 第 5 步：发布后

- 在 GitHub 仓库设置里打开 **Secret scanning** 与 **Push protection**
- 提交 **SECURITY.md**（已存在）作为漏洞报告渠道
- 保留 `E:/AILearn/_prepublish_backup_20261020/`（46MB，含改写前 .git 备份 + 规则表 + 敏感词表 + worktree 备份）**至少 30 天**再删除

---

## 五、遗留提示

1. **`.gitignore` 规则不含 `corpus/raw/` 本身**（只忽略其下的 `affairs/`）。当前 `corpus/raw/` 只有空的 `affairs/` 子目录，安全；若将来放入原始抓取件，请确认不含真实学生数据。
2. **linked worktree**（位于本机用户目录下的 WorkBuddy 工作区，路径含本机账户名）已重新注册到内层仓库，但 `git worktree list` 会显示 `prunable`（Windows 路径分隔符导致的展示问题，不影响功能）。其历史未提交改动已完整备份至 `E:/AILearn/_prepublish_backup_20261020/worktree_backup_task-t10/`。
3. **外层旧副本**（`E:/AILearn/NovaCampus`，186 提交）已同步清理，但**不是发布主体**。建议：要么删除，要么明确标注为非发布仓库，避免误推。
4. **本报告自身曾引入回归**：首版报告正文为说明"清理了哪些内容"而写出了真实敏感字面量，且提交于首次历史重写之后。现已泛化并二次重写 —— 这也说明**清理报告本身必须自证不含敏感词**。

---

## 六、变更提交记录

| 提交 | 说明 |
|---|---|
| `3683a70` | chore(security): 开源前凭据改造 —— 口令改环境变量注入、哈希升级 PBKDF2、MCP 默认绑定回环、Grafana 强制外部注入 |
| `db74724` | chore(privacy): 开源前脱敏 —— 移除身份标识/本机路径/求职叙事/第三方版权正文 |
| `73b4c31` | chore(security): 模拟栈默认只监听回环地址 |
| `9cca1b4`（外层） | chore(ignore): 排除嵌套仓库与工作副本目录 |

> 上述 hash 为历史重写**之后**的 hash。重写前的 hash 已全部失效，不可用于 GitHub PR 链接。
