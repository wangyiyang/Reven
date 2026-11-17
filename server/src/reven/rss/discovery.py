"""Daily RSS discovery module: 按源分段抓取入内存，候选直写 Bitable（不落 PG 条目）。"""

import hashlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from reven.notifications import DeliveryNotifier, Notification
from reven.rss.models import RssDiscoveryRun, RssSource
from reven.rss.normalization import normalize_keyword
from reven.scheduling import utc_now

# 待审核候选计数 seam：生产由 BitableCandidateStore.count_candidates 提供（入参为状态）
PendingReviewCounter = Callable[[str], Awaitable[int]]


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
class FetchedEntry:
    """单源分段抓取+本地化后的内存条目（不落 PG）；dedupe_key 优先级 URL > GUID > 归一化标题。"""

    source_name: str
    entry: FeedEntry
    localized: LocalizedEntry
    dedupe_key: str


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
    async def screen_run(self, run_id: UUID, entries: tuple[FetchedEntry, ...]) -> int:
        """内存筛选 run 内抓取条目并把候选写入权威存储，返回实际写入的候选数。

        写入是 run 关键步骤：抛错 = run 失败（调用方标记 failed、不推进 checkpoint、
        不发成功汇总），下一轮整体重试。
        """
        ...


class _RunEntryCollector:
    """run 内抓取条目收集器：seen-set 按去重键去重（防重第一层），add 返回是否为新条目。"""

    def __init__(self) -> None:
        self._seen: set[str] = set()
        self._entries: list[FetchedEntry] = []

    @property
    def entries(self) -> tuple[FetchedEntry, ...]:
        return tuple(self._entries)

    def add(self, source: RssSource, entry: FeedEntry, localized: LocalizedEntry) -> int:
        key = _dedupe_key(source, entry)
        if key in self._seen:
            return 0
        self._seen.add(key)
        self._entries.append(FetchedEntry(source.name, entry, localized, key))
        return 1


class RssDiscoveryService:
    """每日 RSS 发现：按源分段提交 checkpoint，候选经内存筛选直写 Bitable（#226）。

    - 每个 source 一个事务：fetch + localize + 统计/errors + 标记 processed_source_ids，
      进程中断后下一轮跳过已提交源；条目本身只进内存集合（权威存储为 Bitable）。
    - 筛选+候选写入失败 = run 失败：run 标记 failed、不发成功汇总；下轮重试整体重跑
      （重跑入口重置 checkpoint 与计数），Bitable 侧去重键查重 + client_token 兜底幂等。
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
        pending_counter: PendingReviewCounter | None = None,
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
        self._pending_counter = pending_counter
        self._translation_alert_count = translation_alert_count
        self._translation_alert_ratio = translation_alert_ratio
        self._source_max_consecutive_failures = source_max_consecutive_failures

    async def run(self, run_date: date) -> RssRunSummary:
        existing = await self._existing_run(run_date)
        if existing is not None:
            if existing.status in {"screening", "failed"} and self._screener is not None:
                # screening 中断（内存筛选输入已失）或候选写入失败：重置 checkpoint 与计数整体重跑，
                # Bitable 去重键查重 + 稳定 client_token 保证重试不产生明显重复
                await self._reset_for_retry(existing.run_id)
            elif existing.status != "running":
                return await self._notify_if_needed(existing)
            run_id = existing.run_id
            sources = await self._enabled_sources()
            processed = await self._processed_source_ids(run_id)
        else:
            run, sources = await self._start_run(run_date)
            run_id = run.id
            processed = set()
        collector = _RunEntryCollector()
        for source in sources:
            if str(source.id) in processed:
                continue
            await self._process_source(run_id, source, collector)
        summary = await self._finalize_run(run_id, sources)
        if self._screener is not None:
            summary = await self._screen(summary, collector.entries)
        return await self._notify_if_needed(summary)

    async def _reset_for_retry(self, run_id: UUID) -> None:
        """把 failed/中断于 screening 的 run 重置为可整体重跑的 running 状态。"""
        async with self._factory.begin() as session:
            run = await session.get(RssDiscoveryRun, run_id, with_for_update=True)
            if run is None:
                raise RuntimeError("RSS 任务记录不存在")
            run.status = "running"
            run.finished_at = None
            run.processed_source_ids = []
            run.fetched_count = 0
            run.new_count = 0
            run.candidate_count = 0
            run.failure_count = 0
            run.errors = []
            await session.flush()

    async def _process_source(self, run_id: UUID, source: RssSource, collector: _RunEntryCollector) -> None:
        """单源分段：网络/翻译在事务外执行，统计与 checkpoint 在同一事务提交（条目只进内存）。"""
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
                new_count += collector.add(db_source, entry, translated)

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

    async def _screen(self, summary: RssRunSummary, entries: tuple[FetchedEntry, ...]) -> RssRunSummary:
        screener = self._screener
        if screener is None:
            return summary
        try:
            candidate_count = await screener.screen_run(summary.run_id, entries)
            error_type = None
        except Exception as exc:
            candidate_count = 0
            error_type = type(exc).__name__
        async with self._factory.begin() as session:
            run = await session.get(RssDiscoveryRun, summary.run_id, with_for_update=True)
            if run is None:
                raise RuntimeError("RSS 任务记录不存在")
            if error_type is not None:
                # 候选写入是 run 关键步骤：失败 = run 失败（status=failed），checkpoint 立即回退
                # （重试整体重跑），不发成功汇总（finished_at 保持 None，_notify_if_needed 跳过）；
                # 计数与 errors 保留供观测，下轮重跑入口 _reset_for_retry 清零重新累计
                run.status = "failed"
                run.finished_at = None
                run.processed_source_ids = []
                run.failure_count += 1
                run.errors = [*run.errors, {"stage": "candidate_write", "error_type": error_type}]
            else:
                run.candidate_count = candidate_count
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
        links = {"打开候选工作台": self._candidate_url} if self._candidate_url else {}
        try:
            # 待审核计数与发送同属汇总失败域：计数失败（Bitable 未配置/不可用）不标记已发送，
            # 记录 notification_error 并随 run 重入重试（对齐汇总失败重试纪律）
            pending_review = await self._pending_review_count()
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
        """待审核候选总数（Bitable 中状态为 candidate 的记录数，含历史积压，与当日 run 无关）。"""
        if self._pending_counter is None:
            return 0
        return await self._pending_counter("candidate")


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


def _dedupe_key(source: RssSource, entry: FeedEntry) -> str:
    """去重键（带键型前缀，自描述）：URL 规范化 > GUID（源作用域）> 归一化标题。"""
    if entry.url:
        return f"url:{_digest(_canonical_url(entry.url))}"
    if entry.guid:
        return f"guid:{_digest(f'{source.id}:{entry.guid}')}"
    return f"title:{_digest(normalize_keyword(entry.title))}"


def _canonical_url(value: str) -> str:
    parsed = urlsplit(value)
    host = (parsed.hostname or "").casefold()
    port = parsed.port
    netloc = host if port is None or (parsed.scheme == "https" and port == 443) else f"{host}:{port}"
    query = urlencode(sorted(parse_qsl(parsed.query, keep_blank_values=True)))
    return urlunsplit((parsed.scheme.casefold(), netloc, parsed.path or "/", query, ""))
