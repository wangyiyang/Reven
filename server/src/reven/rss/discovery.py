"""Daily RSS discovery module with idempotent persistence and one summary."""

import hashlib
from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from reven.publishing.notifications import DeliveryNotifier, Notification
from reven.rss.models import RssDiscoveryRun, RssItem, RssSource
from reven.rss.normalization import normalize_keyword
from reven.scheduling import utc_now


@dataclass(frozen=True)
class FeedEntry:
    guid: str | None
    url: str | None
    title: str
    summary: str
    published_at: datetime | None


@dataclass(frozen=True)
class LocalizedEntry:
    entry: FeedEntry
    title_zh: str
    summary_zh: str


@dataclass(frozen=True)
class RssRunSummary:
    run_id: UUID
    run_date: date
    status: str
    source_count: int
    fetched_count: int
    new_count: int
    candidate_count: int
    failure_count: int


class FeedReader(Protocol):
    async def fetch(self, source: RssSource) -> tuple[FeedEntry, ...]: ...


class EntryLocalizer(Protocol):
    async def localize(self, entries: tuple[FeedEntry, ...]) -> tuple[LocalizedEntry, ...]: ...


class RunScreener(Protocol):
    async def screen_run(self, run_id: UUID) -> int: ...


class RssDiscoveryService:
    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        feed_reader: FeedReader,
        localizer: EntryLocalizer,
        notifier: DeliveryNotifier,
        *,
        screener: RunScreener | None = None,
        candidate_url: str | None = None,
    ) -> None:
        self._factory = factory
        self._feed_reader = feed_reader
        self._localizer = localizer
        self._notifier = notifier
        self._screener = screener
        self._candidate_url = candidate_url

    async def run(self, run_date: date) -> RssRunSummary:
        existing = await self._existing_run(run_date)
        if existing is not None:
            if existing.status == "screening" and self._screener is not None:
                return await self._notify_if_needed(await self._screen(existing))
            if existing.status != "running":
                return await self._notify_if_needed(existing)
            run_id = existing.run_id
            sources = await self._enabled_sources()
        else:
            run, sources = await self._start_run(run_date)
            run_id = run.id
        fetched: list[tuple[RssSource, FeedEntry]] = []
        errors: list[dict[str, object]] = []
        for source in sources:
            try:
                fetched.extend((source, entry) for entry in await self._feed_reader.fetch(source))
            except Exception as exc:
                errors.append({"source_id": str(source.id), "error_type": type(exc).__name__})
        entries = tuple(entry for _source, entry in fetched)
        try:
            localized = await self._localizer.localize(entries)
            if len(localized) != len(fetched):
                raise RuntimeError("RSS 本地化结果数量与输入不一致")
        except Exception as exc:
            errors.append({"stage": "translation", "error_type": type(exc).__name__})
            localized = tuple(LocalizedEntry(entry, entry.title, entry.summary) for entry in entries)
        summary = await self._persist_result(run_id, sources, fetched, localized, errors)
        if self._screener is not None:
            summary = await self._screen(summary)
        return await self._notify_if_needed(summary)

    async def _screen(self, summary: RssRunSummary) -> RssRunSummary:
        screener = self._screener
        if screener is None:
            return summary
        try:
            candidate_count = await screener.screen_run(summary.run_id)
            error_type = None
        except Exception as exc:
            candidate_count = summary.candidate_count
            error_type = type(exc).__name__
        async with self._factory.begin() as session:
            run = await session.get(RssDiscoveryRun, summary.run_id, with_for_update=True)
            if run is None:
                raise RuntimeError("RSS 任务记录不存在")
            run.candidate_count = candidate_count
            if error_type is not None:
                run.status = "partial"
                run.failure_count += 1
                run.errors = [*run.errors, {"stage": "screening", "error_type": error_type}]
            else:
                run.status = "partial" if run.errors else "completed"
            run.finished_at = utc_now()
            await session.flush()
            return _summary(run)

    async def _existing_run(self, run_date: date) -> RssRunSummary | None:
        async with self._factory() as session:
            run = await session.scalar(select(RssDiscoveryRun).where(RssDiscoveryRun.run_date == run_date))
            return _summary(run) if run is not None else None

    async def _start_run(self, run_date: date) -> tuple[RssDiscoveryRun, list[RssSource]]:
        async with self._factory.begin() as session:
            run = RssDiscoveryRun(run_date=run_date)
            session.add(run)
            sources = await _enabled_sources(session)
            await session.flush()
            return run, sources

    async def _enabled_sources(self) -> list[RssSource]:
        async with self._factory() as session:
            return await _enabled_sources(session)

    async def _persist_result(
        self,
        run_id: UUID,
        sources: list[RssSource],
        fetched: list[tuple[RssSource, FeedEntry]],
        localized: tuple[LocalizedEntry, ...],
        errors: list[dict[str, object]],
    ) -> RssRunSummary:
        async with self._factory.begin() as session:
            run = await session.get(RssDiscoveryRun, run_id, with_for_update=True)
            if run is None:
                raise RuntimeError("RSS 任务记录不存在")
            new_count = 0
            for (source, entry), translated in zip(fetched, localized, strict=True):
                new_count += await _save_if_new(session, run_id, source, entry, translated)
            run.status = "screening" if self._screener is not None else "partial" if errors else "completed"
            run.source_count = len(sources)
            run.fetched_count = len(fetched)
            run.new_count = new_count
            run.failure_count = len(errors)
            run.errors = errors
            run.finished_at = None if self._screener is not None else utc_now()
            await session.flush()
            return _summary(run)

    async def _notify_if_needed(self, summary: RssRunSummary) -> RssRunSummary:
        async with self._factory() as session:
            run = await session.get(RssDiscoveryRun, summary.run_id)
            if run is None or run.notification_sent_at is not None or run.finished_at is None:
                return summary
        links = {"打开候选工作台": self._candidate_url} if self._candidate_url else {}
        notification = Notification(
            "Reven RSS 每日汇总",
            "RSS 内容发现",
            (
                f"抓取 {summary.fetched_count} 条，新增 {summary.new_count} 条，"
                f"候选 {summary.candidate_count} 条，异常 {summary.failure_count} 个。"
            ),
            links,
        )
        try:
            await self._notifier.send(notification)
        except Exception as exc:
            async with self._factory.begin() as session:
                run = await session.get(RssDiscoveryRun, summary.run_id, with_for_update=True)
                if run is not None:
                    run.notification_error = type(exc).__name__
            return summary
        async with self._factory.begin() as session:
            run = await session.get(RssDiscoveryRun, summary.run_id, with_for_update=True)
            if run is not None and run.notification_sent_at is None:
                run.notification_sent_at = utc_now()
                run.notification_error = None
        return summary


async def _save_if_new(
    session: AsyncSession,
    run_id: UUID,
    source: RssSource,
    entry: FeedEntry,
    localized: LocalizedEntry,
) -> int:
    url_key = _digest(_canonical_url(entry.url)) if entry.url else None
    guid_key = _digest(f"{source.id}:{entry.guid}") if entry.guid else None
    title_key = _digest(normalize_keyword(entry.title))
    conditions = [RssItem.title_key == title_key]
    if url_key is not None:
        conditions.append(RssItem.url_key == url_key)
    if guid_key is not None:
        conditions.append(RssItem.guid_key == guid_key)
    existing = await session.scalar(select(RssItem).where(or_(*conditions)).limit(1))
    if existing is not None:
        existing.last_seen_at = utc_now()
        return 0
    session.add(
        RssItem(
            source_id=source.id,
            first_seen_run_id=run_id,
            source_name=source.name,
            guid=entry.guid,
            url=entry.url,
            url_key=url_key,
            guid_key=guid_key,
            title_key=title_key,
            title=entry.title,
            summary=entry.summary,
            title_zh=localized.title_zh,
            summary_zh=localized.summary_zh,
            published_at=entry.published_at,
        )
    )
    await session.flush()
    return 1


def _summary(run: RssDiscoveryRun) -> RssRunSummary:
    return RssRunSummary(
        run.id,
        run.run_date,
        run.status,
        run.source_count,
        run.fetched_count,
        run.new_count,
        run.candidate_count,
        run.failure_count,
    )


async def _enabled_sources(session: AsyncSession) -> list[RssSource]:
    return list(
        (await session.scalars(select(RssSource).where(RssSource.enabled.is_(True)).order_by(RssSource.id))).all()
    )


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _canonical_url(value: str) -> str:
    parsed = urlsplit(value)
    host = (parsed.hostname or "").casefold()
    port = parsed.port
    netloc = host if port is None or (parsed.scheme == "https" and port == 443) else f"{host}:{port}"
    query = urlencode(sorted(parse_qsl(parsed.query, keep_blank_values=True)))
    return urlunsplit((parsed.scheme.casefold(), netloc, parsed.path or "/", query, ""))
