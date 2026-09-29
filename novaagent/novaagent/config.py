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

# 模型候选(同 base_url/key,DashScope 兼容模式);设置页供用户切换
MODEL_CANDIDATES = [
    {"id": "qwen-flash", "label": "qwen-flash(默认 · 快速经济)"},
    {"id": "qwen3.7-plus", "label": "qwen3.7-plus(推理 · 高质量)"},
]


def configured() -> list[str]:
    """返回缺失的关键配置项(启动自检用)。"""
    missing = []
    if not LLM_API_KEY:
        missing.append("LLM_API_KEY")
    if not EMBEDDING_API_KEY:
        missing.append("EMBEDDING_API_KEY")
    return missing
