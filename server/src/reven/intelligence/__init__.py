"""Intelligence — LLM 插件口。

提供 DeepSeek 直连的匹配器、模板配置缓存、人工确认队列。
"""

from reven.intelligence.llm_matcher import llm_matcher, llm_matcher_fallback
from reven.intelligence.cache import TemplateCache
from reven.intelligence.confirmation import ConfirmationQueue

__all__ = [
    "llm_matcher",
    "llm_matcher_fallback",
    "TemplateCache",
    "ConfirmationQueue",
]
