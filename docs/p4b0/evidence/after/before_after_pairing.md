# P4b-0 before/after 证据配对(复核人独立取证)

> 生成:`/d/anaconda3/python.exe docs/p4b0/review_pair_evidence.py`。
> after 侧由复核人自写的 CDP 驱动脚本 `docs/p4b0/after_evidence.py` 产出
> (Chrome DevTools MCP 的 `filePath` 在两个会话都被工作区根限制拒绝,见 HANDOFF 坑清单)。

## 一、DOM/状态逐字段配对

| 项 | BEFORE | AFTER | 判定 | 说明 |
|---|---|---|---|---|
| 03 来源块文本 | ['引用来源 / [1] 《EVAL-研究生学籍管理规定》 · 相关度 0.9971'] | ['引用来源 / [1] 《EVAL-研究生学籍管理规定》 · 相关度 0.9971'] | **MATCH** | 相关度 0.9971 逐字一致(检索层确定性输出) |
| 03 bot_msgs | 17 | 33 | **DRIFT** | 会话历史随评测/走查累积,非渲染差异 |
| 04 弹窗标题 | 《西南交通大学2026年收费公示》 | 《西南交通大学2026年收费公示》 | **MATCH** |  |
| 04 弹窗可见 | flex | flex | **MATCH** |  |
| 04 弹窗正文头 | 分类
政策文件
可见级别
学生及以上
上传
counselor · 2026-09-29
分块数
6
AI 摘要
本公示 | 分类
政策文件
可见级别
学生及以上
上传
counselor · 2026-09-29
分块数
6
AI 摘要
本公示 | **MATCH** | 逐字一致 |
| 04 筛选值 | 政策文件 | 政策文件 | **MATCH** |  |
| 04 筛选后行数 | 0 | 3 | **BASELINE_DEFECT** | before 侧 rows 为空数组=探针未取到内容,不是页面为空(after 侧同一筛选有真实行) |
| 05 弹窗标题 | 设置 | 设置 | **MATCH** |  |
| 05 模型 radios | ['qwen-flash', 'qwen3.7-plus', 'on'] | ['qwen-flash', 'qwen3.7-plus', 'on', '', '', ''] | **MATCH** | after 侧探针把自定义 API 的三个文本框一并取到(多 3 个空值),前 3 项一致 |
| 05 自定义表单存在 | True | True | **MATCH** |  |
| 06 周报区可见 | block | block | **MATCH** |  |
| 06 归档按钮 enabled | True | True | **MATCH** |  |
| 06 周报标题行 | # 辅导员工作周报(2026-09-21 ~ 2026-09-27) | # 辅导员工作周报(2026-09-21 ~ 2026-09-27) | **MATCH** | 正文条目差异=工作记录随后续验证累积,属运行时数据 |
| 06 AI 扩充产出非空 | True | True | **MATCH** | 扩充文本由 LLM 生成,不可能逐字相同;此处只断言'有结构化产出' |
| 07 拒答模板头两行 | （缺口说明：知识库中未检索到与该问题相关的分块。为避免误导，本回答由系统模板生成，未采用模型自由发挥 | （缺口说明：知识库中未检索到与该问题相关的分块。为避免误导，本回答由系统模板生成，未采用模型自由发挥 | **MATCH** | 确定性模板(不经 LLM)逐字一致 |
| 07 拒答无越界引用 | False | False | **MATCH** | 两侧均无 [n] 引用 -> P4a 剥离/模板未含引用,前端渲染无截断 |
| 08 renderMeta 合成串 | 引用来源 / [undefined] 《SAMPLE-TITLE-A》 · 相关度 0.9 / [undefined] 《SAMPLE-TITLE-B》 · 相关度 0.8 / 已调用工具 add_fragment | 引用来源 / [undefined] 《SAMPLE-TITLE-A》 · 相关度 0.9 / [undefined] 《SAMPLE-TITLE-B》 · 相关度 0.8 / 已调用工具 add_fragment | **MATCH** | 同输入 -> 逐字节同输出(含既存 [undefined] 缺陷),这是跨拆分最强的一条 UI 层证明 |
| 01 登录失败提示 | 用户名或密码错误 | 用户名或密码错误 | **MATCH** |  |
| 02 student 标签可见性 | ['知识库(active)', '工作记录', '周报'] | ['知识库(active)[vis=shown]', '工作记录[vis=none]', '周报[vis=none]'] | **MATCH** | after 侧额外标注了 display 状态:工作记录/周报 = none(学生不可见),与 enter() 逻辑一致 |
| 02 student kb_rows | 0 | 42 | **BASELINE_DEFECT** | before 记 0;本次 DB 实测 role_min='student' 有 42 篇且 /api/kb/documents 返回 42 -> before 探针未取到真实行 |
| 01 登录页文案 token 覆盖 | 20 | 缺失 3 个(见 note) | **CHECK** | 缺失项均为登录后/main 区域元素或 placeholder,不在 login-box innerText 范围内 |
| 11 /css/theme.css | 磁盘 22102 B | HTTP 200 / 22102 B / text/css; charset=utf-8 | **MATCH** | 浏览器实际收到字节数 == 磁盘字节数,且 charset 显式 |
| 11 /js/api.js | 磁盘 1519 B | HTTP 200 / 1519 B / application/javascript; charset=utf-8 | **MATCH** | 浏览器实际收到字节数 == 磁盘字节数,且 charset 显式 |
| 11 /js/ui.js | 磁盘 4893 B | HTTP 200 / 4893 B / application/javascript; charset=utf-8 | **MATCH** | 浏览器实际收到字节数 == 磁盘字节数,且 charset 显式 |
| 11 /js/chat.js | 磁盘 3633 B | HTTP 200 / 3633 B / application/javascript; charset=utf-8 | **MATCH** | 浏览器实际收到字节数 == 磁盘字节数,且 charset 显式 |
| 11 /js/kb.js | 磁盘 3724 B | HTTP 200 / 3724 B / application/javascript; charset=utf-8 | **MATCH** | 浏览器实际收到字节数 == 磁盘字节数,且 charset 显式 |
| 11 /js/weekly.js | 磁盘 4893 B | HTTP 200 / 4893 B / application/javascript; charset=utf-8 | **MATCH** | 浏览器实际收到字节数 == 磁盘字节数,且 charset 显式 |

## 二、同名截图客观度量(缩放到 360x220 后)

| 文件 | 尺寸 before/after | 平均绝对差 | 直方图交集 |
|---|---|---|---|
| 01_login_fail.png | 1440x900 / 1440x900 | 1.49/255 | 0.926 |
| 01_login_page.png | 1440x900 / 1440x900 | 0.44/255 | 0.935 |
| 02_student_main.png | 1440x900 / 1440x900 | 15.57/255 | 0.909 |
| 03_chat_sources.png | 1440x900 / 1440x900 | 8.97/255 | 0.889 |
| 04_kb_chunks_modal.png | 1440x900 / 1440x900 | 5.46/255 | 0.869 |
| 05_settings_modal.png | 1440x900 / 1440x900 | 4.01/255 | 0.851 |
| 06_weekly_counselor.png | 1440x900 / 1440x900 | 16.22/255 | 0.852 |
| 06_weekly_report.png | 1440x900 / 1440x900 | 16.36/255 | 0.850 |
| 07_chat_tool_trace.png | 1440x900 / 1440x900 | 17.76/255 | 0.886 |

## 三、控制台

error=0 warning=0 exceptions=0(全流程:三角色登录 / SSE 问答 / 拒答 / KB 筛选+分块弹窗 / 设置 / 周报 AI 扩充+生成)

## 四、小结

- 配对项 27 条:MATCH 23,DRIFT 1,BASELINE_DEFECT 2
- BASELINE_DEFECT 两条都在 **before 侧**(Zcode 的第 0 步基线):student kb_rows 记 0、筛选后 rows 记空数组 —— 均被本次实测推翻(42 行 / 3 行)。**结论不受影响**(渲染与 RBAC 由 after 实测 + 后端 API/DB 交叉证明),但后续单子的 BEFORE 基线必须改成'取到非空才落盘'的探针。
