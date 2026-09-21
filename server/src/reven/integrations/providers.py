"""Canonical provider identifiers supported by integration settings."""

from typing import Literal

TranslationProvider = Literal["translate_baidu", "translate_aliyun"]

TRANSLATION_PROVIDERS: tuple[TranslationProvider, ...] = (
    "translate_baidu",
    "translate_aliyun",
)

SUPPORTED_INTEGRATION_PROVIDERS = (
    "feishu_bot",
    *TRANSLATION_PROVIDERS,
    "embedding",
    "agent-llm",
)
