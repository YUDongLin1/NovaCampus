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


def configured() -> list[str]:
    """返回缺失的关键配置项(启动自检用)。"""
    missing = []
    if not LLM_API_KEY:
        missing.append("LLM_API_KEY")
    if not EMBEDDING_API_KEY:
        missing.append("EMBEDDING_API_KEY")
    return missing
