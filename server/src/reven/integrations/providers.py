"""Canonical provider identifiers supported by integration settings."""

from typing import Literal

TranslationProvider = Literal["translate_baidu", "translate_aliyun"]

TRANSLATION_PROVIDERS: tuple[TranslationProvider, ...] = (
    "translate_baidu",
    "translate_aliyun",
)

AGENT_LLM_PROVIDER = "agent-llm"
DEFAULT_AGENT_LLM_PROVIDER = "deepseek-official"
DEFAULT_AGENT_LLM_MODEL = "deepseek-v4-flash"

SUPPORTED_INTEGRATION_PROVIDERS = (
    "feishu_bot",
    *TRANSLATION_PROVIDERS,
    "embedding",
    AGENT_LLM_PROVIDER,
)


def model_ref_of(provider: str, model: str) -> str:
    """模型引用：统一 `provider/model` 主键格式（对齐 OpenClaw model ref）。"""
    return f"{provider}/{model}"
