"""Daily RSS discovery module with idempotent persistence and one summary."""

import hashlib
from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from reven.notifications import DeliveryNotifier, Notification
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


class PartialLocalizationError(RuntimeError):
    def __init__(
        self,
        localized: tuple[LocalizedEntry, ...],
        error_types: tuple[str, ...],
    ) -> None:
        super().__init__("RSS 本地化部分失败")
        self.localized = localized
        self.error_types = error_types


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
    """每日 RSS 发现：按源分段提交 checkpoint，支持中断续跑与死源自动治理（#178）。

    - 每个 source 一个事务：fetch + localize + 持久化 + 标记 processed_source_ids，
      进程中断后下一轮跳过已提交源，避免单轮超时全部重来。
    - 翻译失败超阈值（绝对数或占比）时在当日汇总后追加一条告警通知。
    - source 连续 N 轮抓取失败自动禁用并在 errors 中标注 source_governance。
    """

    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        feed_reader: FeedReader,
        localizer: EntryLocalizer,
        notifier: DeliveryNotifier,
        *,
        screener: RunScreener | None = None,
        candidate_url: str | None = None,
        translation_alert_count: int = 10,
        translation_alert_ratio: float = 0.3,
        source_max_consecutive_failures: int = 3,
    ) -> None:
        self._factory = factory
        self._feed_reader = feed_reader
        self._localizer = localizer
        self._notifier = notifier
        self._screener = screener
        self._candidate_url = candidate_url
        self._translation_alert_count = translation_alert_count
        self._translation_alert_ratio = translation_alert_ratio
        self._source_max_consecutive_failures = source_max_consecutive_failures

    async def run(self, run_date: date) -> RssRunSummary:
        existing = await self._existing_run(run_date)
        if existing is not None:
            if existing.status == "screening" and self._screener is not None:
                return await self._notify_if_needed(await self._screen(existing))
            if existing.status != "running":
                return await self._notify_if_needed(existing)
            run_id = existing.run_id
            sources = await self._enabled_sources()
            processed = await self._processed_source_ids(run_id)
        else:
            run, sources = await self._start_run(run_date)
            run_id = run.id
            processed = set()
        for source in sources:
            if str(source.id) in processed:
                continue
            await self._process_source(run_id, source)
        summary = await self._finalize_run(run_id, sources)
        if self._screener is not None:
            summary = await self._screen(summary)
        return await self._notify_if_needed(summary)

    async def _process_source(self, run_id: UUID, source: RssSource) -> None:
        """单源分段：网络/翻译在事务外执行，持久化与 checkpoint 在同一事务提交。"""
        fetch_error: str | None = None
        entries: tuple[FeedEntry, ...] = ()
        try:
            entries = await self._feed_reader.fetch(source)
        except Exception as exc:
            fetch_error = type(exc).__name__

        localized: tuple[LocalizedEntry, ...] = ()
        translation_errors: list[str] = []
        if entries:
            try:
                localized = await self._localizer.localize(entries)
            except PartialLocalizationError as exc:
                localized = exc.localized
                translation_errors = list(exc.error_types)
            except Exception as exc:
                # 整批 localize 失败 = 本批所有条目翻译失败，按条目计数以对齐告警阈值口径
                translation_errors = [type(exc).__name__] * len(entries)
                localized = tuple(LocalizedEntry(entry, entry.title, entry.summary) for entry in entries)
            if len(localized) != len(entries):
                translation_errors.append("RuntimeError")
                localized = tuple(LocalizedEntry(entry, entry.title, entry.summary) for entry in entries)

        async with self._factory.begin() as session:
            run = await session.get(RssDiscoveryRun, run_id, with_for_update=True)
            if run is None:
                raise RuntimeError("RSS 任务记录不存在")
            db_source = await session.get(RssSource, source.id, with_for_update=True)
            if db_source is None:
                return  # 源在本轮中被人工删除：跳过且不占 checkpoint
            new_count = 0
            for entry, translated in zip(entries, localized, strict=True):
                new_count += await _save_if_new(session, run_id, db_source, entry, translated)

            now = utc_now()
            db_source.last_fetched_at = now
            if fetch_error is not None:
                db_source.consecutive_failures += 1
                db_source.last_error = fetch_error
                run.failure_count += 1
                run.errors = [*run.errors, {"source_id": str(db_source.id), "error_type": fetch_error}]
                if db_source.enabled and db_source.consecutive_failures >= self._source_max_consecutive_failures:
                    db_source.enabled = False
                    db_source.disabled_at = now
                    db_source.disabled_reason = (
                        f"连续 {db_source.consecutive_failures} 轮抓取失败（最近一次：{fetch_error}），自动禁用"
                    )
                    run.errors = [
                        *run.errors,
                        {
                            "stage": "source_governance",
                            "action": "auto_disable",
                            "source_id": str(db_source.id),
                            "source_name": db_source.name,
                            "consecutive_failures": db_source.consecutive_failures,
                            "error_type": fetch_error,
                        },
                    ]
            else:
                db_source.consecutive_failures = 0
                db_source.last_error = None

            for error_type in translation_errors:
                run.failure_count += 1
                run.errors = [*run.errors, {"stage": "translation", "error_type": error_type}]

            run.fetched_count += len(entries)
            run.new_count += new_count
            run.processed_source_ids = [*run.processed_source_ids, str(db_source.id)]
            await session.flush()

    async def _finalize_run(self, run_id: UUID, sources: list[RssSource]) -> RssRunSummary:
        async with self._factory.begin() as session:
            run = await session.get(RssDiscoveryRun, run_id, with_for_update=True)
            if run is None:
                raise RuntimeError("RSS 任务记录不存在")
            run.source_count = len(sources)
            if self._screener is not None:
                run.status = "screening"
                run.finished_at = None
            else:
                run.status = "partial" if run.errors else "completed"
                run.finished_at = utc_now()
            await session.flush()
            return _summary(run)

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

    async def _processed_source_ids(self, run_id: UUID) -> set[str]:
        async with self._factory() as session:
            value = await session.scalar(
                select(RssDiscoveryRun.processed_source_ids).where(RssDiscoveryRun.id == run_id)
            )
        return set(value or [])

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

    async def _notify_if_needed(self, summary: RssRunSummary) -> RssRunSummary:
        async with self._factory() as session:
            run = await session.get(RssDiscoveryRun, summary.run_id)
            if run is None or run.finished_at is None:
                return summary
            needs_summary = run.notification_sent_at is None
            needs_translation_alert = self._translation_alert_pending(run)
        if needs_summary:
            await self._send_summary(summary)
        if needs_translation_alert:
            await self._send_translation_alert(summary)
        return summary

    def _translation_alert_pending(self, run: RssDiscoveryRun) -> bool:
        """翻译失败数/占比任一超阈值且本 run 尚未发送告警。"""
        if any(error.get("stage") == "translation_alert_sent" for error in run.errors):
            return False
        translation_failures = sum(1 for error in run.errors if error.get("stage") == "translation")
        if translation_failures == 0:
            return False
        if translation_failures >= self._translation_alert_count:
            return True
        if run.fetched_count <= 0:
            return False
        return translation_failures / run.fetched_count >= self._translation_alert_ratio

    async def _send_translation_alert(self, summary: RssRunSummary) -> None:
        async with self._factory() as session:
            run = await session.get(RssDiscoveryRun, summary.run_id)
            if run is None:
                return
            translation_failures = sum(1 for error in run.errors if error.get("stage") == "translation")
            fetched = run.fetched_count
            ratio = (translation_failures / fetched) if fetched > 0 else 0.0
        notification = Notification(
            "Reven RSS 翻译失败告警",
            "RSS 翻译告警",
            (
                f"本轮翻译失败 {translation_failures} 条"
                f"（抓取 {fetched} 条，占比 {ratio:.0%}），"
                f"已超阈值（数量 {self._translation_alert_count} 或占比 {self._translation_alert_ratio:.0%}）。"
                "请检查翻译供应商额度与限速。"
            ),
            {"打开候选工作台": self._candidate_url} if self._candidate_url else {},
        )
        try:
            await self._notifier.send(notification)
        except Exception as exc:
            async with self._factory.begin() as session:
                run = await session.get(RssDiscoveryRun, summary.run_id, with_for_update=True)
                if run is not None:
                    run.notification_error = type(exc).__name__
            return
        async with self._factory.begin() as session:
            run = await session.get(RssDiscoveryRun, summary.run_id, with_for_update=True)
            if run is not None and not any(e.get("stage") == "translation_alert_sent" for e in run.errors):
                run.errors = [
                    *run.errors,
                    {"stage": "translation_alert_sent", "translation_failures": translation_failures},
                ]

    async def _send_summary(self, summary: RssRunSummary) -> None:
        pending_review = await self._pending_review_count()
        links = {"打开候选工作台": self._candidate_url} if self._candidate_url else {}
        notification = Notification(
            "Reven RSS 每日汇总",
            "RSS 内容发现",
            (
                f"抓取 {summary.fetched_count} 条，新增 {summary.new_count} 条，"
                f"候选 {summary.candidate_count} 条，异常 {summary.failure_count} 个。"
                f"待审核共 {pending_review} 条。"
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
            return
        async with self._factory.begin() as session:
            run = await session.get(RssDiscoveryRun, summary.run_id, with_for_update=True)
            if run is not None and run.notification_sent_at is None:
                run.notification_sent_at = utc_now()
                run.notification_error = None

    async def _pending_review_count(self) -> int:
        """待审核候选总数（status=candidate，含历史积压，与当日 run 无关）。"""
        async with self._factory() as session:
            count = await session.scalar(select(func.count()).select_from(RssItem).where(RssItem.status == "candidate"))
        return int(count or 0)


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
