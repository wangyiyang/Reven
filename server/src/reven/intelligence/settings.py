"""Intelligence settings — DeepSeek API 配置。

优先从环境变量读取，自动加载 server/.env 文件（不会提交到 git）。
"""

from __future__ import annotations

import os
from pathlib import Path

# 自动加载 server/.env（仅开发环境，生产环境通过容器 env 注入）
_env_path = Path(__file__).resolve().parent.parent.parent.parent / ".env"
if _env_path.exists():
    try:
        from dotenv import load_dotenv

        load_dotenv(str(_env_path))
    except ImportError:
        pass  # dotenv 未安装时静默跳过

# ═══════════════════════════════════════════════════════════
# DeepSeek API
# ═══════════════════════════════════════════════════════════

DEEPSEEK_API_KEY: str | None = os.environ.get("DEEPSEEK_API_KEY")
DEEPSEEK_BASE_URL: str = os.environ.get(
    "DEEPSEEK_BASE_URL",
    "https://api.deepseek.com",
)
LLM_MODEL_DEFAULT: str = os.environ.get(
    "LLM_MODEL_DEFAULT",
    "deepseek-v4-flash",
)
LLM_MODEL_FALLBACK: str = os.environ.get(
    "LLM_MODEL_FALLBACK",
    "deepseek-v4-pro",
)
LLM_TEMPERATURE: float = float(os.environ.get("LLM_TEMPERATURE", "0.2"))
LLM_MAX_TOKENS: int = int(os.environ.get("LLM_MAX_TOKENS", "65536"))
LLM_MAX_RETRIES: int = int(os.environ.get("LLM_MAX_RETRIES", "3"))
LLM_CONFIDENCE_CAP: float = float(os.environ.get("LLM_CONFIDENCE_CAP", "0.8"))

# ═══════════════════════════════════════════════════════════
# 模板配置缓存（SQLite）
# ═══════════════════════════════════════════════════════════

CACHE_DB_PATH: str = os.environ.get(
    "TEMPLATE_CACHE_DB",
    os.path.join(os.path.dirname(__file__), "template_cache.db"),
)

# ═══════════════════════════════════════════════════════════
# 人工确认队列
# ═══════════════════════════════════════════════════════════

CONFIRMATION_THRESHOLD: float = float(os.environ.get("CONFIRMATION_THRESHOLD", "0.6"))
"""置信度低于此值的 LLM 产出需要人工确认。"""

CONFIRMATION_DB_PATH: str = os.environ.get(
    "CONFIRMATION_DB_PATH",
    os.path.join(os.path.dirname(__file__), "confirmation_queue.db"),
)
