"""RSS machine translation chunking, failover, rate limiting, and fallback."""

import asyncio

import pytest
from reven.rss.discovery import FeedEntry, LocalizedEntry, PartialLocalizationError
from reven.rss.translation import (
    MachineTranslationLocalizer,
    RateLimitedTextTranslator,
    TranslationBinding,
)


def _entry(title: str, summary: str = "") -> FeedEntry:
    return FeedEntry(guid=None, url=None, title=title, summary=summary, published_at=None)


class RecordingTranslator:
    def __init__(
        self,
        prefix: str = "",
        *,
        fail_on: set[str] | None = None,
        responses: dict[str, str] | None = None,
    ) -> None:
        self.prefix = prefix
        self.fail_on = fail_on or set()
        self.responses = responses or {}
        self.calls: list[tuple[str, str, str]] = []

    async def translate(self, text: str, *, source: str = "auto", target: str = "zh") -> str:
        self.calls.append((text, source, target))
        if text in self.fail_on:
            raise RuntimeError("provider failure with sensitive response")
        return self.responses.get(text, f"{self.prefix}{text}")


class RecordingFallback:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[tuple[FeedEntry, ...]] = []

    async def localize(self, entries: tuple[FeedEntry, ...]) -> tuple[LocalizedEntry, ...]:
        self.calls.append(entries)
        if self.error is not None:
            raise self.error
        return tuple(LocalizedEntry(entry, f"Q:{entry.title}", f"Q:{entry.summary}") for entry in entries)


@pytest.mark.anyio
async def test_primary_success_does_not_call_secondary_or_qwen() -> None:
    primary = RecordingTranslator("P:")
    secondary = RecordingTranslator("S:")
    fallback = RecordingFallback()
    localizer = MachineTranslationLocalizer(
        (
            TranslationBinding("translate_baidu", primary),
            TranslationBinding("translate_aliyun", secondary),
        ),
        fallback,
    )

    result = await localizer.localize((_entry("title", "summary"),))

    assert [(item.title_zh, item.summary_zh) for item in result] == [("P:title", "P:summary")]
    assert primary.calls == [("title", "auto", "zh"), ("summary", "auto", "zh")]
    assert secondary.calls == []
    assert fallback.calls == []


@pytest.mark.anyio
async def test_summary_failure_retries_whole_entry_and_disables_provider_for_later_entries() -> None:
    primary = RecordingTranslator("P:", fail_on={"summary-one"})
    secondary = RecordingTranslator("S:")
    fallback = RecordingFallback()
    entries = (_entry("title-one", "summary-one"), _entry("title-two", "summary-two"))
    localizer = MachineTranslationLocalizer(
        (
            TranslationBinding("translate_baidu", primary),
            TranslationBinding("translate_aliyun", secondary),
        ),
        fallback,
    )

    result = await localizer.localize(entries)

    assert [(item.title_zh, item.summary_zh) for item in result] == [
        ("S:title-one", "S:summary-one"),
        ("S:title-two", "S:summary-two"),
    ]
    assert [call[0] for call in primary.calls] == ["title-one", "summary-one"]
    assert [call[0] for call in secondary.calls] == [
        "title-one",
        "summary-one",
        "title-two",
        "summary-two",
    ]
    assert fallback.calls == []


@pytest.mark.anyio
async def test_whitespace_translation_is_invalid_and_retries_whole_entry() -> None:
    primary = RecordingTranslator("P:", responses={"summary": "  \n"})
    secondary = RecordingTranslator("S:")
    fallback = RecordingFallback()
    localizer = MachineTranslationLocalizer(
        (
            TranslationBinding("translate_baidu", primary),
            TranslationBinding("translate_aliyun", secondary),
        ),
        fallback,
    )

    result = await localizer.localize((_entry("title", "summary"),))

    assert [(item.title_zh, item.summary_zh) for item in result] == [("S:title", "S:summary")]
    assert [call[0] for call in primary.calls] == ["title", "summary"]
    assert [call[0] for call in secondary.calls] == ["title", "summary"]
    assert fallback.calls == []


@pytest.mark.anyio
async def test_chunks_in_order_skips_empty_summary_and_applies_storage_limits() -> None:
    translator = RecordingTranslator()
    fallback = RecordingFallback()
    title = "a" * 2_501
    summary = "b" * 6_501
    localizer = MachineTranslationLocalizer(
        (TranslationBinding("translate_aliyun", translator),),
        fallback,
    )

    first, second = await localizer.localize((_entry(title, summary), _entry("short", "   ")))

    chunks = [call[0] for call in translator.calls]
    assert [len(chunk) for chunk in chunks] == [1_000, 1_000, 501, 1_000, 1_000, 1_000, 1_000, 1_000, 1_000, 501, 5]
    assert all(call[1:] == ("auto", "zh") for call in translator.calls)
    assert first.title_zh == title[:2_000]
    assert first.summary_zh == summary[:6_000]
    assert second.title_zh == "short"
    assert second.summary_zh == ""
    assert fallback.calls == []


@pytest.mark.anyio
async def test_baidu_rate_limiter_uses_injected_clock_and_sleep() -> None:
    now = 0.0
    sleeps: list[float] = []
    translator = RecordingTranslator()

    def clock() -> float:
        return now

    async def sleep(delay: float) -> None:
        nonlocal now
        sleeps.append(delay)
        now += delay

    limited = RateLimitedTextTranslator(translator, interval=1.0, clock=clock, sleep=sleep)

    await limited.translate("one")
    await limited.translate("two")
    await limited.translate("three")

    assert sleeps == [1.0, 1.0]
    assert [call[0] for call in translator.calls] == ["one", "two", "three"]


@pytest.mark.anyio
async def test_baidu_rate_limiter_serializes_concurrent_requests_at_one_qps() -> None:
    now = 0.0
    starts: list[float] = []

    def clock() -> float:
        return now

    async def sleep(delay: float) -> None:
        nonlocal now
        now += delay

    class TimestampTranslator:
        async def translate(self, text: str, *, source: str = "auto", target: str = "zh") -> str:
            del source, target
            starts.append(clock())
            await asyncio.sleep(0)
            return text

    limited = RateLimitedTextTranslator(TimestampTranslator(), interval=1.0, clock=clock, sleep=sleep)

    await asyncio.gather(limited.translate("one"), limited.translate("two"), limited.translate("three"))

    assert starts == [0.0, 1.0, 2.0]


@pytest.mark.anyio
async def test_no_machine_config_uses_qwen_for_all_entries() -> None:
    fallback = RecordingFallback()
    entries = (_entry("one"), _entry("two"))

    result = await MachineTranslationLocalizer((), fallback).localize(entries)

    assert [item.title_zh for item in result] == ["Q:one", "Q:two"]
    assert fallback.calls == [entries]


@pytest.mark.anyio
async def test_all_machine_providers_fail_then_qwen_handles_current_and_remaining_entries() -> None:
    baidu = RecordingTranslator(fail_on={"one"})
    aliyun = RecordingTranslator(fail_on={"one"})
    fallback = RecordingFallback()
    entries = (_entry("one"), _entry("two"))
    localizer = MachineTranslationLocalizer(
        (
            TranslationBinding("translate_baidu", baidu),
            TranslationBinding("translate_aliyun", aliyun),
        ),
        fallback,
    )

    result = await localizer.localize(entries)

    assert [item.title_zh for item in result] == ["Q:one", "Q:two"]
    assert [call[0] for call in baidu.calls] == ["one"]
    assert [call[0] for call in aliyun.calls] == ["one"]
    assert fallback.calls == [entries]


@pytest.mark.anyio
async def test_final_fallback_failure_preserves_completed_machine_results() -> None:
    provider = RecordingTranslator("M:", fail_on={"two"})
    fallback = RecordingFallback(error=RuntimeError("qwen unavailable"))
    entries = (_entry("one"), _entry("two"))
    localizer = MachineTranslationLocalizer(
        (TranslationBinding("translate_baidu", provider),),
        fallback,
    )

    with pytest.raises(PartialLocalizationError) as captured:
        await localizer.localize(entries)

    assert [(item.title_zh, item.summary_zh) for item in captured.value.localized] == [
        ("M:one", ""),
        ("two", ""),
    ]
    assert captured.value.error_types == ("RuntimeError",)
    assert fallback.calls == [(entries[1],)]


@pytest.mark.anyio
async def test_final_fallback_partial_error_preserves_machine_and_qwen_results() -> None:
    entries = (_entry("one"), _entry("two"), _entry("three"))
    provider = RecordingTranslator("M:", fail_on={"two"})
    qwen_partial = PartialLocalizationError(
        (
            LocalizedEntry(entries[1], "two", ""),
            LocalizedEntry(entries[2], "Q:three", ""),
        ),
        ("QwenBatchError",),
    )
    fallback = RecordingFallback(error=qwen_partial)
    localizer = MachineTranslationLocalizer(
        (TranslationBinding("translate_baidu", provider),),
        fallback,
    )

    with pytest.raises(PartialLocalizationError) as captured:
        await localizer.localize(entries)

    assert [(item.title_zh, item.summary_zh) for item in captured.value.localized] == [
        ("M:one", ""),
        ("two", ""),
        ("Q:three", ""),
    ]
    assert captured.value.error_types == ("QwenBatchError",)
    assert fallback.calls == [(entries[1], entries[2])]
