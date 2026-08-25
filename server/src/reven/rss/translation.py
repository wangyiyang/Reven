"""RSS machine-translation orchestration with provider failover and Qwen fallback."""

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from typing import Protocol

import httpx

from reven.integrations.translation import TranslationError
from reven.integrations.translation.aliyun import ALIYUN_MT_BASE_URL, AliyunTranslateClient
from reven.integrations.translation.baidu import BAIDU_TRANSLATE_BASE_URL, BaiduTranslateClient
from reven.integrations.translation.configuration import (
    AliyunTranslationConfig,
    BaiduTranslationConfig,
    TranslationConfig,
)
from reven.rss.discovery import EntryLocalizer, FeedEntry, LocalizedEntry, PartialLocalizationError

logger = logging.getLogger(__name__)

TRANSLATION_CHUNK_SIZE = 1_000
MAX_LOCALIZED_TITLE_LENGTH = 2_000
MAX_LOCALIZED_SUMMARY_LENGTH = 6_000
BAIDU_MIN_REQUEST_INTERVAL_SECONDS = 1.0
TRANSLATION_TIMEOUT = httpx.Timeout(10.0)


class TextTranslator(Protocol):
    async def translate(self, text: str, *, source: str = "auto", target: str = "zh") -> str: ...


@dataclass(frozen=True)
class TranslationBinding:
    provider: str
    translator: TextTranslator


class RateLimitedTextTranslator:
    """Serialize requests and keep their start times at least ``interval`` apart."""

    def __init__(
        self,
        translator: TextTranslator,
        *,
        interval: float,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._translator = translator
        self._interval = interval
        self._clock = clock
        self._sleep = sleep
        self._last_started_at: float | None = None
        self._lock = asyncio.Lock()

    async def translate(self, text: str, *, source: str = "auto", target: str = "zh") -> str:
        async with self._lock:
            now = self._clock()
            if self._last_started_at is not None:
                remaining = self._interval - (now - self._last_started_at)
                if remaining > 0:
                    await self._sleep(remaining)
                    now = self._clock()
            self._last_started_at = now
            return await self._translator.translate(text, source=source, target=target)


class MachineTranslationLocalizer:
    """Translate entries with an ordered provider chain and a final localizer fallback."""

    def __init__(self, bindings: tuple[TranslationBinding, ...], fallback: EntryLocalizer) -> None:
        self._bindings = bindings
        self._fallback = fallback

    async def localize(self, entries: tuple[FeedEntry, ...]) -> tuple[LocalizedEntry, ...]:
        active = list(self._bindings)
        localized: list[LocalizedEntry] = []
        for index, entry in enumerate(entries):
            for binding in tuple(active):
                try:
                    translated = await _translate_entry(binding.translator, entry)
                except Exception as exc:
                    logger.warning(
                        "RSS 机翻供应商本轮停用（provider=%s, entry_index=%d, error_type=%s）",
                        binding.provider,
                        index,
                        type(exc).__name__,
                    )
                    active.remove(binding)
                    continue
                localized.append(translated)
                break
            else:
                return await self._fallback_remaining(tuple(localized), entries[index:])
        return tuple(localized)

    async def _fallback_remaining(
        self,
        completed: tuple[LocalizedEntry, ...],
        remaining: tuple[FeedEntry, ...],
    ) -> tuple[LocalizedEntry, ...]:
        try:
            fallback_result = await self._fallback.localize(remaining)
            if len(fallback_result) != len(remaining):
                raise RuntimeError("RSS 本地化结果数量不匹配")
        except PartialLocalizationError as exc:
            raise PartialLocalizationError(completed + exc.localized, exc.error_types) from exc
        except Exception as exc:
            if not completed:
                raise
            original = tuple(LocalizedEntry(entry, entry.title, entry.summary) for entry in remaining)
            raise PartialLocalizationError(completed + original, (type(exc).__name__,)) from exc
        return completed + fallback_result


async def _translate_entry(translator: TextTranslator, entry: FeedEntry) -> LocalizedEntry:
    title = await _translate_text(translator, entry.title)
    summary = await _translate_text(translator, entry.summary) if entry.summary.strip() else ""
    return LocalizedEntry(
        entry,
        title.strip()[:MAX_LOCALIZED_TITLE_LENGTH],
        summary.strip()[:MAX_LOCALIZED_SUMMARY_LENGTH],
    )


async def _translate_text(translator: TextTranslator, text: str) -> str:
    translated_chunks: list[str] = []
    for start in range(0, len(text), TRANSLATION_CHUNK_SIZE):
        translated = await translator.translate(
            text[start : start + TRANSLATION_CHUNK_SIZE],
            source="auto",
            target="zh",
        )
        if not isinstance(translated, str) or not translated.strip():
            raise TranslationError("机翻响应缺少译文")
        translated_chunks.append(translated)
    return "".join(translated_chunks)


@asynccontextmanager
async def configured_translation_localizer(
    configs: tuple[TranslationConfig, ...],
    fallback: EntryLocalizer,
) -> AsyncIterator[EntryLocalizer]:
    """Create provider HTTP clients for one RSS run and close them afterwards."""
    async with AsyncExitStack() as stack:
        bindings: list[TranslationBinding] = []
        for config in configs:
            if isinstance(config, BaiduTranslationConfig):
                http = await stack.enter_async_context(
                    httpx.AsyncClient(
                        base_url=BAIDU_TRANSLATE_BASE_URL,
                        timeout=TRANSLATION_TIMEOUT,
                        trust_env=False,
                    )
                )
                client: TextTranslator = RateLimitedTextTranslator(
                    BaiduTranslateClient(config.app_id, config.app_key, http=http),
                    interval=BAIDU_MIN_REQUEST_INTERVAL_SECONDS,
                )
            elif isinstance(config, AliyunTranslationConfig):
                http = await stack.enter_async_context(
                    httpx.AsyncClient(
                        base_url=ALIYUN_MT_BASE_URL,
                        timeout=TRANSLATION_TIMEOUT,
                        trust_env=False,
                    )
                )
                client = AliyunTranslateClient(config.access_key_id, config.access_key_secret, http=http)
            else:  # pragma: no cover - TranslationConfig is exhaustive to mypy
                raise TypeError("不支持的机翻配置")
            bindings.append(TranslationBinding(config.provider, client))
        yield MachineTranslationLocalizer(tuple(bindings), fallback) if bindings else fallback
