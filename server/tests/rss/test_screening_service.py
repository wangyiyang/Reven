import hashlib
from datetime import date
from uuid import uuid4

import pytest
from reven.rss.embedding import BGE_M3_DIMENSION, BGE_M3_MODEL, EmbeddingError, EmbedOutcome, KeywordEmbeddingService
from reven.rss.models import RssDiscoveryRun, RssItem, RssSource
from reven.rss.repository import RssSettingsRepository
from reven.rss.screening import RssScreeningEngine
from reven.rss.screening_service import RssScreeningService
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class DeterministicEmbedder:
    model = BGE_M3_MODEL
    dimension = BGE_M3_DIMENSION

    async def embed(self, texts: tuple[str, ...]) -> EmbedOutcome:
        return EmbedOutcome(
            tuple(tuple([1.0] + [0.0] * (self.dimension - 1)) for _text in texts),
            tuple(None for _text in texts),
        )


class FailingEmbedder:
    model = BGE_M3_MODEL
    dimension = BGE_M3_DIMENSION

    async def embed(self, texts: tuple[str, ...]) -> EmbedOutcome:
        raise RuntimeError("provider unavailable")


class CodedFailingEmbedder:
    model = BGE_M3_MODEL
    dimension = BGE_M3_DIMENSION

    async def embed(self, texts: tuple[str, ...]) -> EmbedOutcome:
        raise EmbeddingError("EMBEDDING_TIMEOUT", "Embedding 请求超时", retryable=True)


class PartiallyDegradingEmbedder:
    """含 degraded 的文本返回 None + 错误码，其余正常。"""

    model = BGE_M3_MODEL
    dimension = BGE_M3_DIMENSION

    async def embed(self, texts: tuple[str, ...]) -> EmbedOutcome:
        vectors: list[tuple[float, ...] | None] = []
        codes: list[str | None] = []
        for text in texts:
            if "degraded" in text:
                vectors.append(None)
                codes.append("EMBEDDING_HTTP_ERROR")
            else:
                vectors.append(tuple([1.0] + [0.0] * (self.dimension - 1)))
                codes.append(None)
        return EmbedOutcome(tuple(vectors), tuple(codes))


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


async def seed_item(
    db_session: AsyncSession,
    run: RssDiscoveryRun,
    source: RssSource,
    *,
    suffix: str,
    title_zh: str = "AI 智能体架构",
    status: str = "pending",
    embedding_status: str = "pending",
    screening_error: str | None = None,
    notion_page_id: object = None,
) -> RssItem:
    item = RssItem(
        source_id=source.id,
        first_seen_run_id=run.id,
        source_name=source.name,
        guid=suffix,
        url=f"https://example.com/{suffix}",
        url_key=digest(f"url-{suffix}"),
        guid_key=digest(f"guid-{suffix}"),
        title_key=digest(f"title-{suffix}"),
        title=f"title {suffix}",
        summary="Practical patterns",
        title_zh=title_zh,
        summary_zh="实用模式",
        status=status,
        embedding_status=embedding_status,
        screening_error=screening_error,
        notion_page_id=notion_page_id,  # type: ignore[arg-type]
    )
    db_session.add(item)
    return item


@pytest.mark.anyio
async def test_screening_service_persists_derived_scores_but_not_item_vectors(
    db_session: AsyncSession,
) -> None:
    source = RssSource(name="Example", feed_url="https://example.com/feed", enabled=True)
    run = RssDiscoveryRun(run_date=date(2026, 8, 11))
    db_session.add_all([source, run])
    await db_session.flush()
    item = await seed_item(db_session, run, source, suffix="one")
    await RssSettingsRepository(db_session).create_keyword(term="AI 智能体", kind="positive", enabled=True)
    await db_session.commit()
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    embeddings = KeywordEmbeddingService(factory, DeterministicEmbedder())
    service = RssScreeningService(factory, embeddings, RssScreeningEngine())

    assert await service.screen_run(run.id) == 1

    async with factory() as session:
        stored = await session.get(RssItem, item.id)
        stored_run = await session.get(RssDiscoveryRun, run.id)
        assert stored is not None and stored_run is not None
        assert stored.status == "candidate"
        assert stored.positive_literal_matches == ["AI 智能体"]
        assert stored.bm25_score > 0
        assert stored.positive_embedding_score == 1.0
        assert stored.embedding_model == BGE_M3_MODEL
        assert stored.embedding_status == "completed"
        assert stored.screening_error is None
        assert stored.rules_version == "rss-v1"
        assert stored_run.candidate_count == 1
        assert "embedding" not in RssItem.__table__.columns


@pytest.mark.anyio
async def test_screening_degrades_to_literal_and_bm25_when_embedding_fails(
    db_session: AsyncSession,
) -> None:
    source = RssSource(name="Example", feed_url="https://example.com/feed-2", enabled=True)
    run = RssDiscoveryRun(run_date=date(2026, 8, 12))
    db_session.add_all([source, run])
    await db_session.flush()
    item = await seed_item(db_session, run, source, suffix="two")
    await RssSettingsRepository(db_session).create_keyword(term="AI 智能体", kind="positive", enabled=True)
    await db_session.commit()
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    service = RssScreeningService(
        factory,
        KeywordEmbeddingService(factory, FailingEmbedder()),
        RssScreeningEngine(),
    )

    assert await service.screen_run(run.id) == 1

    async with factory() as session:
        stored = await session.get(RssItem, item.id)
        assert stored is not None
        assert stored.status == "candidate"
        assert stored.positive_literal_matches == ["AI 智能体"]
        assert stored.embedding_status == "degraded"
        assert stored.screening_error == "RuntimeError"


@pytest.mark.anyio
async def test_screening_persists_concrete_embedding_error_code(
    db_session: AsyncSession,
) -> None:
    source = RssSource(name="Example", feed_url="https://example.com/feed-3", enabled=True)
    run = RssDiscoveryRun(run_date=date(2026, 8, 13))
    db_session.add_all([source, run])
    await db_session.flush()
    item = await seed_item(db_session, run, source, suffix="three")
    await RssSettingsRepository(db_session).create_keyword(term="AI 智能体", kind="positive", enabled=True)
    await db_session.commit()
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    service = RssScreeningService(
        factory,
        KeywordEmbeddingService(factory, CodedFailingEmbedder()),
        RssScreeningEngine(),
    )

    assert await service.screen_run(run.id) == 1

    async with factory() as session:
        stored = await session.get(RssItem, item.id)
        assert stored is not None
        assert stored.embedding_status == "degraded"
        assert stored.embedding_model is None
        assert stored.screening_error == "EMBEDDING_TIMEOUT"


@pytest.mark.anyio
async def test_screening_degrades_single_item_when_its_vector_missing(
    db_session: AsyncSession,
) -> None:
    source = RssSource(name="Example", feed_url="https://example.com/feed-4", enabled=True)
    run = RssDiscoveryRun(run_date=date(2026, 8, 14))
    db_session.add_all([source, run])
    await db_session.flush()
    degraded_item = await seed_item(db_session, run, source, suffix="four-a", title_zh="degraded 条目")
    healthy_item = await seed_item(db_session, run, source, suffix="four-b", title_zh="AI 智能体架构")
    await RssSettingsRepository(db_session).create_keyword(term="AI 智能体", kind="positive", enabled=True)
    await db_session.commit()
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    service = RssScreeningService(
        factory,
        KeywordEmbeddingService(factory, PartiallyDegradingEmbedder()),
        RssScreeningEngine(),
    )

    assert await service.screen_run(run.id) == 1

    async with factory() as session:
        degraded = await session.get(RssItem, degraded_item.id)
        healthy = await session.get(RssItem, healthy_item.id)
        assert degraded is not None and healthy is not None
        assert degraded.embedding_status == "degraded"
        assert degraded.screening_error == "EMBEDDING_HTTP_ERROR"
        assert degraded.embedding_model is None
        assert healthy.embedding_status == "completed"
        assert healthy.screening_error is None
        assert healthy.embedding_model == BGE_M3_MODEL


@pytest.mark.anyio
async def test_rescreen_degraded_backfills_scores_and_skips_human_decisions(
    db_session: AsyncSession,
) -> None:
    source = RssSource(name="Example", feed_url="https://example.com/feed-5", enabled=True)
    run = RssDiscoveryRun(run_date=date(2026, 8, 15))
    db_session.add_all([source, run])
    await db_session.flush()
    degraded = await seed_item(
        db_session,
        run,
        source,
        suffix="five-a",
        status="filtered",
        embedding_status="degraded",
        screening_error="EMBEDDING_TIMEOUT",
    )
    ignored = await seed_item(
        db_session,
        run,
        source,
        suffix="five-b",
        status="ignored",
        embedding_status="degraded",
        screening_error="EMBEDDING_TIMEOUT",
    )
    pushed = await seed_item(
        db_session,
        run,
        source,
        suffix="five-c",
        status="candidate",
        embedding_status="degraded",
        screening_error="EMBEDDING_TIMEOUT",
        notion_page_id=uuid4(),
    )
    await RssSettingsRepository(db_session).create_keyword(term="AI 智能体", kind="positive", enabled=True)
    await db_session.commit()
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    service = RssScreeningService(
        factory,
        KeywordEmbeddingService(factory, DeterministicEmbedder()),
        RssScreeningEngine(),
    )

    assert await service.rescreen_degraded() == 1

    async with factory() as session:
        backfilled = await session.get(RssItem, degraded.id)
        skipped_ignored = await session.get(RssItem, ignored.id)
        skipped_pushed = await session.get(RssItem, pushed.id)
        assert backfilled is not None and skipped_ignored is not None and skipped_pushed is not None
        # degraded 条目被重新打分并补齐语义分
        assert backfilled.status == "candidate"
        assert backfilled.embedding_status == "completed"
        assert backfilled.screening_error is None
        assert backfilled.embedding_model == BGE_M3_MODEL
        assert backfilled.positive_embedding_score == 1.0
        # 人工已忽略/已推送的条目保持原样
        assert skipped_ignored.status == "ignored"
        assert skipped_ignored.screening_error == "EMBEDDING_TIMEOUT"
        assert skipped_pushed.screening_error == "EMBEDDING_TIMEOUT"
        assert skipped_pushed.embedding_status == "degraded"


@pytest.mark.anyio
async def test_rescreen_degraded_keeps_degraded_with_new_code_when_still_failing(
    db_session: AsyncSession,
) -> None:
    source = RssSource(name="Example", feed_url="https://example.com/feed-6", enabled=True)
    run = RssDiscoveryRun(run_date=date(2026, 8, 16))
    db_session.add_all([source, run])
    await db_session.flush()
    item = await seed_item(
        db_session,
        run,
        source,
        suffix="six",
        status="candidate",
        embedding_status="degraded",
        screening_error="EMBEDDING_TIMEOUT",
    )
    await RssSettingsRepository(db_session).create_keyword(term="AI 智能体", kind="positive", enabled=True)
    await db_session.commit()
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)

    # refresh 只处理 1 个关键词（成功），embed_temporary 对条目文本降级
    class ItemFailingEmbedder:
        model = BGE_M3_MODEL
        dimension = BGE_M3_DIMENSION

        def __init__(self) -> None:
            self.calls = 0

        async def embed(self, texts: tuple[str, ...]) -> EmbedOutcome:
            self.calls += 1
            if self.calls == 1:
                # refresh 关键词成功
                return EmbedOutcome(
                    tuple(tuple([1.0] + [0.0] * (self.dimension - 1)) for _ in texts),
                    tuple(None for _ in texts),
                )
            return EmbedOutcome(
                tuple(None for _ in texts),
                tuple("EMBEDDING_RATE_LIMITED" for _ in texts),
            )

    service = RssScreeningService(
        factory,
        KeywordEmbeddingService(factory, ItemFailingEmbedder()),
        RssScreeningEngine(),
    )

    assert await service.rescreen_degraded() == 1

    async with factory() as session:
        stored = await session.get(RssItem, item.id)
        assert stored is not None
        assert stored.embedding_status == "degraded"
        assert stored.screening_error == "EMBEDDING_RATE_LIMITED"
        assert stored.embedding_model is None


@pytest.mark.anyio
async def test_rescreen_degraded_without_degraded_items_is_noop(
    db_session: AsyncSession,
) -> None:
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)

    class NoCallEmbedder:
        model = BGE_M3_MODEL
        dimension = BGE_M3_DIMENSION

        async def embed(self, texts: tuple[str, ...]) -> EmbedOutcome:
            raise AssertionError("不应发起 embedding 调用")

    service = RssScreeningService(
        factory,
        KeywordEmbeddingService(factory, NoCallEmbedder()),
        RssScreeningEngine(),
    )

    assert await service.rescreen_degraded() == 0
