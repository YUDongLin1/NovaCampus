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
