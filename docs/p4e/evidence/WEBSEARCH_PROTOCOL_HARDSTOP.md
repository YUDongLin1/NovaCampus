# P4e 硬停报告 · DashScope 联网协议复验（Task #17）

> **结论先行**：单据记录的协议契约在当前 DashScope 上**不成立**，已按「若与记录不符 → 硬停上报，
> 不要按猜测实现」停下。**未改动任何生产代码或配置**（`rag.py`/`graph.py`/`cases.json` 的改动全部属 C0 两条，与本报告无关）。
> 持棒人：Qoder。分支：`task/P4e-web-search`（未合并 master）。

---

## 一、单据要求复验的形态

> 「落码前先用一条最小请求复验 DashScope **原生协议**
> `POST /api/v1/services/aigc/text-generation/generation` +
> `search_options={forced_search, search_strategy:"turbo", enable_source:true, enable_citation:true, citation_format:"[<number>]"}`
> 是否真回 `output.search_info.search_results[{index,site_name,title,url}]`」

**复验结果：❌ 不回。** HTTP 200，但 `search_options` 被**完全忽略**。

---

## 二、四入口全矩阵实测（`probe_websearch_entrypoints.py`，退出码 0）

固定问句、只换入口与模型，扫 4 个模型 × 3 个入口。证据：
`docs/p4e/evidence/websearch_entrypoint_matrix.json`

| # | 入口 | 参数位置 | HTTP | 结构化来源 | 关键实测 |
|---|------|---------|------|-----------|---------|
| ① | 原生 `text-generation` | `parameters.search_options` | 200/400 | ❌ 无 `search_info` | `output` 只有 `['choices']`；`usage.plugins=None`；旧模型 `qwen-flash` 同样无 |
| ② | 兼容 `chat/completions` | `extra_body.search_options` | 200 | ❌ 无 | `message` 只有 `content/role`；`plugins` 无；`prompt_tokens` 仅 24~75（**检索未注入**） |
| ③ | 兼容 `chat/completions` | `enable_search=true` | 200 | ❌ 无 | ⚠️ `prompt_tokens` 29→**2092**（检索**真执行**）但来源被静默丢弃 |
| ④ | **兼容 `responses`** | **`tools=[{"type":"web_search"}]`** | 200 | **⚠️ 只回 `url`** | `output[].type=="web_search_call"` → `action.sources[]={"type":"url","url":...}` |

### 入口④ 的实测细节（唯一带回链接的入口）

| 模型 | sources | 唯一 host | 重复率 | 正文 `[n]` 角标 | 正文内联 URL | `annotations` | `usage.plugins` |
|------|---------|----------|--------|--------------|-------------|-------------|----------------|
| `qwen3.8-max` | 28 | 14 | 5.6% | **0** | **0** | **0** | `web_search.count=1` |
| `qwen3.7-flash` | 19 | — | — | 0 | 0 | 0 | 同上 |
| `qwen3-max` | 10 | — | — | 0 | 0 | 0 | 同上 |
| `qwen-flash`（现 `LLM_MODEL`） | 9 | 7 | 0% | 0 | 0 | 0 | 同上 |

---

## 三、三个必须裁决的阻塞点

### 阻塞点 1（**契约级·硬停**）：单据要求的四字段拿不齐

单据要求 `search_results[{index, site_name, title, url}]`。实测**唯一入口只给 `url`**：

```
入口④ source 元素实际字段 = ['type', 'url']
缺失 = ['index', 'site_name', 'title']     ← 三个字段全缺
```

- `index` 缺 → **没有上游编号**。这直接冲击 `[W1..Wk]` 分区设计。
- `title` 缺 → 联网条目无标题可显示。
- `site_name` 缺 → 单据要求「联网条目显示站点名」，但**官方 `site_name` 字段不存在**。

### 阻塞点 2：**`[W1]` 编号无法由上游给出**

正文侧三个可能的来源**全部为 0**：

| 载体 | 实测值 | 含义 |
|------|--------|------|
| 正文 `[n]` 角标 | 0 处 | 模型不吐角标 |
| 正文内联 URL | 0 个 | 不内联 |
| `content[].annotations` | 0 条 | 无引用锚点 |

实测正文长这样（`qwen3.8-max` 答「杭州明天天气如何？」）：
> 数据来源：中国天气网、中央气象台（NMC）。如需更精细的逐小时预报，可查询杭州气象局官网 hzqx.cn。

—— **来源站点名只以自然语言出现在正文里，与 `action.sources` 的 URL 列表之间没有任何可解析的对应关系**。
所以 `[W1]` 只能是「整个联网来源集合」的整体编号，**无法定位到具体某条断言**。

### 阻塞点 3：`search_strategy` 与模型代次已变

- 单据写的 `"turbo"`：在入口④ 下被接受（不报错），但 `agent` 同样工作，**两者无实测差异**。
- 单据隐含的旧模型（`qwen-plus`/`qwen-flash` 原生协议）**已彻底不返回 `search_info`**。
- 新模型族（`qwen3.8`/`qwen3.7` 系列）在原生 `text-generation` 端点直接 **HTTP 400 `url error`**（属多模态/端点不匹配类错误），只有 `qwen3-max`/`qwen-flash` 回 200 但仍无来源。

---

## 四、一个重要的正面结论

**入口④ 用现成的 `LLM_MODEL=qwen-flash` 就能拿到 9 条来源，无需换模型、无需改 `.env`。**
（代价：输入 token 从 ~24 涨到 1536，即检索注入的上下文成本；`qwen3.8-max` 为 3137。）

这意味着**实现路径是通的**，卡点全在「字段契约」而非「能力可用性」。

---

## 五、请 Qoder 裁决的三个选项

### 选项 A：接受降级契约，按入口④ 实现（**我倾向此项**）

- 来源字段：`url` 用官方值；`site_name` 由 `urlparse(url).netloc` **推导**（如 `www.stats.gov.cn`）；
  `title` 用 `netloc` 或 URL slug 兜底；`index` 由 NovaCampus 按 `action.sources` 原始顺序**自行分配** `[W1..Wk]`。
- 前端明确标注「站点名由 URL 推导」，避免误导。
- **代价**：偏离单据「回 `{index,site_name,title,url}`」的假设，需书面认可为口径变更。
- **收益**：能力可用、URL 真实可点、无需换模型。

### 选项 B：严格按单据原样实现，用入口④ 兜底出 `title`/`site_name`

- 即：只用 `url` 作断言落点，答案里的 `[W1]` 只标注「此结论来自公网检索」，
  **不声称**指向具体某条来源（避免假精确）。
- **代价**：`web_grounded` 评测「来源 URL 可点」可达成，但「分区编号」退化为单条。
- 这条路最能保住 P4e 的合规红线（不做无法验证的映射）。

### 选项 C：硬停到底，本单 P4e 主体挂起等平台/账号

- 若判定「四字段是硬要求、不可降级」，则 P4e 主体（#18~#20）全部不实施，
- 只交付已完成的 C0 两条收口 + 本报告，等 key 权限或平台能力变化后再开单。

**我未擅自选 A/B/C，按纪律停在此处等裁决。**

---

## 六、合规自查（红线 C 级）

| 条 | 状态 | 证据 |
|----|------|------|
| 出网仅发「当前问题文本」一个字符串 | ✅ | 探针只发构造公开问句：`Q_TIME="杭州明天天气如何？"`、`Q_FACT="中国国家统计局最新公布的GDP同比增速是多少？"`；未发任何库内 chunk/会话历史/系统提示词/个人信息/`contacts.json` |
| 日志不记录问题以外字段 | ✅ | `probe_websearch_entrypoints.py` 无 logging 配置，只落 HTTP 码/字段名/计数/URL 列表 |
| 证据含问句须为构造公开问句 | ✅ | 落盘 `text_head` 全是对上述公开问句的回答，**无任何真实学工问句** |
| `E:\<internal-affairs-dir>\` 不入库不上传 | ✅ | 全程未访问该目录 |
| 演示口令不入 KB 不进公网请求 | ✅ | 未读取、未发送 |

**未产生任何真实学生数据出网。**

---

## 七、可复验方式

```bash
cd E:/AILearn/NovaCampus
novaagent/.venv/Scripts/python.exe docs/p4e/probe_websearch_entrypoints.py
# 退出码 0 = 找到至少一条回 URL 的入口；1 = 一条都没有；2 = 缺 key
# ⚠ 耗时约 4 分钟（16 次真实调用）。取退出码不要接管道（坑 55 同源，本次已实测 SIGTERM）
```

证据落盘：`docs/p4e/evidence/`
- `websearch_entrypoint_matrix.json` ← **主证据**（四入口全矩阵 + 去重统计 + 判定）
- `dashscope_websearch_probe.json` ← 第一轮（单据指定形态，pass=false）
- `websearch_model_matrix.json` / `websearch_net_model_scan.json` / `websearch_compat_scan.json` ← 中间轮次
- `websearch_responses_api_probe.json` ← 入口④ 骨架深挖（`web_search_call` 全量 dump）
