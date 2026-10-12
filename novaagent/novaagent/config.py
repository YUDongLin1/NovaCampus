"""配置加载:从 novaagent/.env 读 KEY=VALUE(轻量实现,不引第三方 dotenv)"""
from __future__ import annotations

import os
from pathlib import Path

_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


def _load_env() -> dict[str, str]:
    values: dict[str, str] = {}
    if _ENV_FILE.exists():
        for line in _ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                values[k.strip()] = v.strip()
    return values


_ENV = _load_env()


def env(key: str, default: str = "") -> str:
    return os.environ.get(key) or _ENV.get(key) or default


# ---------- P4f C0-⑥: 额度来源可核验化(硬约束第 7 条的代码化) ----------
# 背景(用户 2026-10-01 指令):`novaagent/.env` 里的 key 是**用户本人付费的额度**,
# 实现者/复核方的任何测试与验证都不得落在它上面(见 HANDOFF 硬约束第 7 条、坑 65)。
# 上一轮的问题不是"用错了 key",而是**"我保证用对了"只是一句口头承诺**——上一轮
# 差点把一份 55/55 当成可复现结果,实际它依赖一个默认关闭的 env 钩子,报告里查不出来。
# 所以额度纪律必须做成**机器可读**:key_source 只回答"这个键来自哪一层",永不回答"值是什么"。
#
# ⚠ 硬性约束:本函数**只允许返回三个字面量之一**,不返回、不拼接、不记录 key 值本身。
#   报告是要提交进 git 的(坑 56 同源风险:入库文件里的敏感值永久留在历史里)。
#   任何调用方都不许把 key 值写进报告/日志/回执,只写 `llm_key_source=session_env` 这类来源标签。
SOURCE_SESSION = "session_env"   # 来自 os.environ(会话注入,合规:测试者自带额度)
SOURCE_REPO = "repo_dotenv"     # 来自仓库 novaagent/.env(用户本人额度;整轮结果一律不认)
SOURCE_UNSET = "unset"           # 两层都没有


def key_source(key: str) -> str:
    """返回某配置键的**来源标签**,绝不返回其值。

    判据:该键是否出现在 ``os.environ`` 里——因为 `env()` 的优先级是 os.environ > 仓库 .env,
    os.environ 命中即代表覆盖了 .env。注意判据只回答"来源",不回答"值",
    因此本函数对任何 key 都可安全写进入库的评测报告。

    另:本函数按**入参键名**判定,不做大小写折叠(配置键一律大写)。
    """
    if os.environ.get(key):
        return SOURCE_SESSION
    if _ENV.get(key):
        return SOURCE_REPO
    return SOURCE_UNSET


LLM_BASE_URL = env("LLM_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
LLM_MODEL = env("LLM_MODEL", "qwen-flash")
LLM_API_KEY = env("LLM_API_KEY")

EMBEDDING_BASE_URL = env("EMBEDDING_BASE_URL", "https://api.siliconflow.cn/v1")
EMBEDDING_MODEL = env("EMBEDDING_MODEL", "BAAI/bge-m3")
EMBEDDING_API_KEY = env("EMBEDDING_API_KEY")

RERANK_MODEL = env("RERANK_MODEL", "BAAI/bge-reranker-v2-m3")
RERANK_API_KEY = env("RERANK_API_KEY")

WEEKLY_MCP_URL = env("WEEKLY_MCP_URL", "http://127.0.0.1:18080/mcp")

# P4a C1:拒答门控阈值(rerank 原始分低于该值不作为回答依据)。原常量在 rag.py,
# P4a 迁入 config 统一管理;rag.py 保留同名别名兼容既有引用。
RERANK_MIN_SCORE = 0.3
# P4a C1 实测修正:达标来源仅 1 条时的单来源放行线——top_score ≥ 该值视为高置信单据,
# 放行(如 qa-01 单块 0.9952);低于该值且无第二条达标来源则拒答。实测依据:
# 「研究生申请休学需要提交哪些材料?」仅 1 块 0.9952 达标,一刀切 n_above<2 会误杀。
REFUSAL_SINGLE_SOURCE_MIN_SCORE = 0.9

DATA_DIR = Path(env("NOVA_DATA_DIR", str(Path(__file__).resolve().parent.parent / "data")))
DB_PATH = DATA_DIR / "agent.db"

ROLE_RANK = {"student": 1, "counselor": 2, "admin": 3}
ROLE_ZH = {"student": "学生", "counselor": "辅导员", "admin": "校管理员"}

# 模型候选(同 base_url/key,DashScope 兼容模式);设置页供用户切换。
# P4b C3: ctx=模型上下文窗口(token,配置保守值);会话注入预算 = ctx*0.65。
MODEL_CANDIDATES = [
    {"id": "qwen-flash", "label": "qwen-flash(默认 · 快速经济)", "ctx": 131072},
    {"id": "qwen3.7-plus", "label": "qwen3.7-plus(推理 · 高质量)", "ctx": 131072},
]


# ---------- P4d: LangGraph 检索编排 + 查询改写 ----------
# 只用 LangGraph 做状态机编排;LLM 仍走 llm.py(httpx)、向量仍走 numpy 内存余弦。
GRAPH_ENABLED = env("NOVA_GRAPH_ENABLED", "1") not in ("0", "false", "False")
MAX_REWRITE = int(env("NOVA_MAX_REWRITE", "2"))
# grade 判定(C2):top_score ≥ 该值 且 达标条数 ≥ GRADE_MIN_ABOVE 才算召回达标
GRADE_MIN_SCORE = float(env("NOVA_GRADE_MIN_SCORE", "0.3"))
GRADE_MIN_ABOVE = int(env("NOVA_GRADE_MIN_ABOVE", "2"))
# 改写地板(⚠ **P4d 起已废弃、不再参与任何判定**,保留仅为兼容旧 env/复盘引用):
# 原设计"rerank 峰值低于此值 → 不做改写直接拒答"被实测证伪——rerank 在本 corpus 上会把
# 正确候选整体压到 0.03~0.19(见 docs/p4d/probe_rerank_dist.py),绝对值不可作"库里有无此主题"
# 的判据。现改为由 build_rewrite_plan 的档位可用性决定(无可用档位才直拒)。
REWRITE_FLOOR = float(env("NOVA_REWRITE_FLOOR", "0.05"))
INTENT_TIMEOUT_S = float(env("NOVA_INTENT_TIMEOUT_S", "8"))
REWRITE_TIMEOUT_S = float(env("NOVA_REWRITE_TIMEOUT_S", "10"))
# 术语展开词典(改写主力:意图归一 + 同义术语展开)。键=用户口语词,值=材料里的规范表述。
TERM_EXPANSION: dict[str, list[str]] = {
    "学平险": ["学生平安保险", "大学生意外伤害保险"],
    "学生平安保险": ["学平险", "大学生意外伤害保险"],
    "意外伤害保险": ["学平险", "学生平安保险"],
    "医保": ["大学生医疗保险", "城乡居民基本医疗保险"],
    "大学生医疗保险": ["医保", "城乡居民基本医疗保险"],
    "报销": ["理赔"],
    "理赔": ["报销"],
}
# 去情境噪声(改写辅助):命中前缀/句式里的称呼、铺垫、口头语,与检索无关且会污染 rerank
NOISE_PATTERNS = [
    r"^老师[，,、:：]?", r"^同学[，,、:：]?", r"^我想问[一下下]*[，,、:：]?", r"^请问[，,、:：]?",
    r"^麻烦[你您][，,、:：]?", r"我们学校", r"咱们学校", r"我校",
]
# 关键词回退层(2-gram 计次)的停用词:现状"学校/我们/这项"等通用词会把无关块顶榜(C5 ②)
KEYWORD_STOPWORDS = {
    "学校", "我们", "你们", "他们", "这项", "这个", "那个", "同学", "老师", "可以", "怎么",
    "什么", "是否", "需要", "现在", "目前", "请问", "一下", "我想", "知道", "有没有",
}
KEYWORD_STOPWORDS_ENABLED = env("NOVA_KEYWORD_STOPWORDS", "1") not in ("0", "false", "False")

# ---------- P4e S1: 流式 grounding 闸门的「早窗提交」 ----------
# 背景(HANDOFF 坑 60 / TASKS P4e S1):P4e M4 为拦「有来源却零 [n] 零数字」的空话答案,
# 把 /api/chat/stream 改成 delta **全量缓冲**、判完闸门再下发。复核方实测
# **TTFB 2365ms / E2E 2401ms、12 个 delta 挤在最后 36ms** → 渐进显示归零,真流式被关掉。
# S1 的解法:判定与下发解耦——delta 默认直接放行,只在「早窗」内(还没出现可核查事实
# **且**累计生成不足 N 字)暂缓;窗口一过立刻补发。**整段生成完仍零可核查事实**才重生一次。
#
# 【N 为什么取 80】
#   · 可核查事实(首个 `[n]` 引用或第一个数字)在据实作答时**几乎总在首句内**出现,
#     实测本项目 qa 用例答案首句 40~120 字 → 80 字能让「首个事实」大概率落在窗口内,
#     命中即放行,缓冲量通常只有十几字;
#   · 最坏情况(整段无事实)也只憋住 80 字 ≈ 1~2 句,而不是整段 200~400 字;
#   · 太小(如 20)会让短免责话术被提前放行、削弱闸门的"不发空话"初衷;
#     太大(如 300)则退回近似全缓冲。故取 60~120 区间的中位。
GROUNDING_EARLY_WINDOW_CHARS = int(env("NOVA_GROUNDING_EARLY_WINDOW_CHARS", "80"))
# 闸门总开关:0 = 关闭(P4e M4 之前的行为),供三档延迟对照取"关闭"档
GROUNDING_GATE_ENABLED = env("NOVA_GROUNDING_GATE", "1") not in ("0", "false", "False")
# ⚠ 测试钩子(默认关):强制流式首版被判为「无据」,使 stream_sse 的重生通道断言
#   **必然**被执行(否则该通道只有约 20% 概率自然命中,断言会空跑——坑 39/45)。
#   只作用于 /api/chat/stream 的首版判定,不影响 /api/chat,重生仍走真实 LLM。
GROUNDING_STREAM_FORCE_UNGROUNDED = env("NOVA_GROUNDING_STREAM_FORCE_UNGROUNDED", "0") == "1"
# ---------- P4f C0-③: 闸门的**轮次作用域**(修「被套在不需要事实回答的轮次上」) ----------
# 【缺陷】P4e M4 的闸门判据是「有来源 却 零 [n] 零数字 → 无效 → 重生一次」,
#   它**不问这一轮是否期待事实回答**。P4e S2 复核实测:默认档命中 12 次/重生失败 11 次、
#   canonical 档命中 16/失败 14,**全部来自 `cc-01` 的种植轮,`final` 轮一次都没命中**。
#   「重生一次都没救回来过」本身就是判据用错地方的证据(坑 64):
#   种植轮是**往会话里塞背景资料**,用户在同一句里明确要求「简短回复『已阅』即可」,
#   模型回「已阅 / 已阅,本条背景资料已收到」才是**正确行为**,那里本就没有需要引用的事实。
#   代价是每轮评测白烧 11~14 次 LLM 调用,并把 badcase 档案灌满噪声。
# 【本单做法】闸门前先判**轮次类型**,只对「期待事实回答」的轮次生效。
#   判据是**语义级**的(抑制型元指令 / 纯陈述),**明确不用「长度 < N 字」**——
#   长度既不是轮次类型的证据,也会随问句改写漂移(坑 51 的同族教训:看着能用的
#   廉价判据往往是错的)。判据实现与逐条依据见 `agent.turn_expects_factual_answer`。
#   留 `all_turns` 档可退回 P4e 行为,供 A/B 对照(不删原行为,便于复现)。
GROUNDING_GATE_SCOPE_MODE = env("NOVA_GROUNDING_GATE_SCOPE", "factual_turns")

# ---------- P4e M7: 联网搜索(默认关闭) ----------
WEB_SEARCH_ENABLED = env("NOVA_WEB_SEARCH_ENABLED", "0") not in ("0", "false", "False")
# ---------- P4f C0-④: 双层超时(修「名实不符」) ----------
# 【原缺陷】`WEB_SEARCH_TIMEOUT_S=60` 被文档与 UI 写成「超时 60s」,但 httpx 的
#   `timeout=60` 是**空闲/读超时(inactivity)**,**不是总时限**——只要上游持续吐数据,
#   连接可以一直挂着。P4e 实测同一问句 12.3s / **79.4s**,60 根本没截断,用户侧表现为
#   「转圈很久也不给结果」,而日志里看不到任何超时痕迹(名实不符 = 排障时找不到线索)。
# 【本单做法】显式分两层,并各自可注入:
#   · IDLE  —— 空闲/读超时。两次数据之间的最大间隔;上游卡住即断。
#   · TOTAL —— **总时限**,由 websearch.search() 用 asyncio.wait_for 兜住整个请求,
#     无论上游是否持续吐数据,到点必断。TOTAL > IDLE(留一次重试/解析的余量)。
# 【为什么默认 45 而不是 60】实测慢档 79.4s 说明上游方差极大;总时限的意义是
#   **给用户一个可预期的等待上限**(UI 也有对应提示),不是"尽量等"——
#   45s 足以覆盖已观测的 12.3s 快档与多数中档,又不会让用户等到以为页面死了。
#   阈值口径:本单未跑 ≥5 次分布(P4e 只留下 2 个数据点,且**烧的是额度**,本单不再重测),
#   故取"快档 12.3s 的约 3.5 倍 / 慢档 79.4s 的约 0.57 倍"的中位偏保守值。
#   复核方若要定更精确的阈值,应先按坑 63 跑 ≥5 次分布再改,别直接调这个数。
WEB_SEARCH_IDLE_TIMEOUT_S = float(env("NOVA_WEB_SEARCH_IDLE_TIMEOUT_S", "20"))
WEB_SEARCH_TOTAL_TIMEOUT_S = float(env("NOVA_WEB_SEARCH_TOTAL_TIMEOUT_S", "45"))
# ⚠ 兼容别名:保留旧名以免既有引用 ImportError,但**它现在只代表空闲超时**,不再是总时限。
#   新代码请用 WEB_SEARCH_IDLE_TIMEOUT_S / WEB_SEARCH_TOTAL_TIMEOUT_S。
WEB_SEARCH_TIMEOUT_S = WEB_SEARCH_IDLE_TIMEOUT_S
WEB_SEARCH_MAX_SOURCES = int(env("NOVA_WEB_SEARCH_MAX_SOURCES", "8"))

# ---------- 会议纪要:录音转写(ASR) ----------
# 链路:百炼「上传本地文件获取临时 URL」(getUploadPolicy → OSS 表单上传 → oss:// 临时 URL)
# → 录音文件识别异步任务(提交 → 轮询 task_id → 下载识别结果 JSON)。
# ⚠ 三条来自官方文档的硬限制,写在这里是为了让"为什么我的录音转不了"有处可查:
#   · 临时存储**仅限「中国内地(北京)」地域的 API Key**,且文件与模型绑定(上传与调用须同模型);
#   · 临时 URL **有效期 48 小时**,过期无法使用 → 转写必须在本次请求内完成,不做"稍后重转";
#   · 上传凭证接口限流 100 QPS 且不支持扩容,官方明确**请勿用于生产环境**
#     —— 本项目的定位是辅导员单机自用,不是高并发服务端,故可接受,但不得据此对外提供服务。
ASR_ENABLED = env("NOVA_ASR_ENABLED", "1") not in ("0", "false", "False")
# DashScope 原生 REST 基址(与 LLM_BASE_URL 的 compatible-mode 端点不同,别混用)
DASHSCOPE_BASE_URL = env("NOVA_DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com").rstrip("/")
ASR_MODEL = env("NOVA_ASR_MODEL", "paraformer-v2")
# 说话人分离:默认关。开启后官方建议音频 ≤2 小时,且需给出/推断说话人数,识别失败率上升。
ASR_DIARIZATION = env("NOVA_ASR_DIARIZATION", "0") not in ("0", "false", "False")
ASR_SPEAKER_COUNT = int(env("NOVA_ASR_SPEAKER_COUNT", "0"))  # 0 = 不指定,交给模型自动判
# 上传上限(MB)。官方上限 2GB,这里按单机自用的合理余量收紧,超限直接拒绝而不是默默传爆。
ASR_MAX_MB = int(env("NOVA_ASR_MAX_MB", "200"))
ASR_POLL_INTERVAL_S = float(env("NOVA_ASR_POLL_INTERVAL_S", "3"))
# 总时限(秒):提交 + 轮询 + 取结果的整体上限,到点必断(与联网搜索双层超时同一口径:
# 给用户一个可预期的等待上限,而不是"尽量等")。
ASR_TOTAL_TIMEOUT_S = float(env("NOVA_ASR_TOTAL_TIMEOUT_S", "900"))
# 允许上传的音频/视频容器后缀(录音文件识别支持的常见格式)
ASR_AUDIO_EXTS = {
    ".aac", ".amr", ".avi", ".flac", ".flv", ".m4a", ".mkv", ".mov", ".mp3",
    ".mp4", ".mpeg", ".ogg", ".opus", ".wav", ".webm", ".wma", ".wmv",
}



def configured() -> list[str]:
    """返回缺失的关键配置项(启动自检用)。"""
    missing = []
    if not LLM_API_KEY:
        missing.append("LLM_API_KEY")
    if not EMBEDDING_API_KEY:
        missing.append("EMBEDDING_API_KEY")
    return missing
