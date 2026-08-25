import json
from datetime import datetime

import httpx
import pytest
from reven.rss.embedding import (
    BGE_M3_DIMENSION,
    BGE_M3_MODEL,
    EmbeddingError,
    EmbedOutcome,
    KeywordEmbeddingService,
    SiliconFlowEmbeddingClient,
)
from reven.rss.models import RssItem, RssKeyword
from reven.rss.repository import RssSettingsRepository
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def embedding_response(
    inputs: int, *, dimension: int = BGE_M3_DIMENSION, model: str = BGE_M3_MODEL
) -> dict[str, object]:
    return {
        "object": "list",
        "model": model,
        "data": [
            {"object": "embedding", "index": index, "embedding": [float(index + 1)] * dimension}
            for index in reversed(range(inputs))
        ],
        "usage": {"prompt_tokens": inputs, "total_tokens": inputs},
    }


@pytest.mark.anyio
async def test_siliconflow_client_batches_and_orders_bge_m3_vectors() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer test-key"
        assert request.url.path == "/v1/embeddings"
        assert request.read()
        return httpx.Response(200, json=embedding_response(2))

    async with httpx.AsyncClient(
        base_url="https://api.siliconflow.cn",
        transport=httpx.MockTransport(handler),
    ) as http:
        outcome = await SiliconFlowEmbeddingClient("test-key", http=http).embed(("first", "second"))

    assert outcome.error_codes == (None, None)
    vectors = outcome.vectors
    assert len(vectors) == 2
    assert vectors[0] is not None and len(vectors[0]) == BGE_M3_DIMENSION
    assert vectors[0][0] == 1.0
    assert vectors[1] is not None and vectors[1][0] == 2.0


@pytest.mark.anyio
async def test_siliconflow_client_degrades_wrong_dimension_batch() -> None:
    # 响应解析错误不可重试，该批直接降级为 None + 具体错误码
    async with httpx.AsyncClient(
        base_url="https://api.siliconflow.cn",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=embedding_response(1, dimension=3))),
    ) as http:
        outcome = await SiliconFlowEmbeddingClient("test-key", http=http).embed(("text",))

    assert outcome.vectors == (None,)
    assert outcome.error_codes == ("EMBEDDING_DIMENSION_MISMATCH",)


@pytest.mark.anyio
async def test_siliconflow_client_rejects_empty_input() -> None:
    async with httpx.AsyncClient(
        base_url="https://api.siliconflow.cn",
        transport=httpx.MockTransport(lambda request: httpx.Response(200)),
    ) as http:
        with pytest.raises(EmbeddingError) as caught:
            await SiliconFlowEmbeddingClient("test-key", http=http).embed(("  ",))

    assert caught.value.code == "EMBEDDING_INPUT_INVALID"


@pytest.mark.anyio
async def test_siliconflow_client_splits_large_batches() -> None:
    batch_sizes: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        batch_sizes.append(len(payload["input"]))
        return httpx.Response(200, json=embedding_response(len(payload["input"])))

    async with httpx.AsyncClient(
        base_url="https://api.siliconflow.cn",
        transport=httpx.MockTransport(handler),
    ) as http:
        outcome = await SiliconFlowEmbeddingClient("test-key", http=http).embed(
            tuple(f"item-{index}" for index in range(33))
        )

    assert len(outcome.vectors) == 33
    assert all(vector is not None for vector in outcome.vectors)
    assert batch_sizes == [32, 1]


@pytest.mark.anyio
async def test_siliconflow_client_retries_rate_limit_then_succeeds() -> None:
    responses = iter((httpx.Response(429), httpx.Response(200, json=embedding_response(1))))

    def handler(request: httpx.Request) -> httpx.Response:
        return next(responses)

    async with httpx.AsyncClient(
        base_url="https://api.siliconflow.cn",
        transport=httpx.MockTransport(handler),
    ) as http:
        client = SiliconFlowEmbeddingClient("test-key", http=http, backoff_base_seconds=0)
        outcome = await client.embed(("text",))

    assert outcome.error_codes == (None,)
    assert outcome.vectors[0] is not None


@pytest.mark.anyio
async def test_siliconflow_client_degrades_batch_after_retry_exhausted() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429)

    async with httpx.AsyncClient(
        base_url="https://api.siliconflow.cn",
        transport=httpx.MockTransport(handler),
    ) as http:
        client = SiliconFlowEmbeddingClient("test-key", http=http, max_attempts=2, backoff_base_seconds=0)
        outcome = await client.embed(("text",))

    assert outcome.vectors == (None,)
    assert outcome.error_codes == ("EMBEDDING_RATE_LIMITED",)


@pytest.mark.anyio
async def test_siliconflow_client_partial_batch_degradation() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(400, json={"message": "bad request"})
        payload = json.loads(request.content)
        return httpx.Response(200, json=embedding_response(len(payload["input"])))

    async with httpx.AsyncClient(
        base_url="https://api.siliconflow.cn",
        transport=httpx.MockTransport(handler),
    ) as http:
        client = SiliconFlowEmbeddingClient("test-key", http=http, backoff_base_seconds=0)
        outcome = await client.embed(tuple(f"item-{index}" for index in range(33)))

    assert len(outcome.vectors) == 33
    assert all(vector is None for vector in outcome.vectors[:32])
    assert all(code == "EMBEDDING_HTTP_ERROR" for code in outcome.error_codes[:32])
    assert outcome.vectors[32] is not None
    assert outcome.error_codes[32] is None


@pytest.mark.anyio
async def test_siliconflow_client_base_url_validation() -> None:
    async with httpx.AsyncClient(base_url="http://api.siliconflow.cn") as http:
        with pytest.raises(ValueError, match="HTTPS"):
            SiliconFlowEmbeddingClient("test-key", http=http)
    async with httpx.AsyncClient(base_url="http://localhost:8080") as http:
        client = SiliconFlowEmbeddingClient("test-key", http=http)
    assert client.model == BGE_M3_MODEL
    assert client.dimension == BGE_M3_DIMENSION


@pytest.mark.anyio
async def test_siliconflow_client_custom_model_must_match_response() -> None:
    async with httpx.AsyncClient(
        base_url="https://embedding.example.com",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=embedding_response(1))),
    ) as http:
        client = SiliconFlowEmbeddingClient("test-key", http=http, model="custom/model", dimension=8)
        outcome = await client.embed(("text",))

    # 响应里的 model 仍是 BGE_M3_MODEL，与配置的 custom/model 不匹配
    assert outcome.vectors == (None,)
    assert outcome.error_codes == ("EMBEDDING_MODEL_MISMATCH",)


class RecordingEmbedder:
    model = BGE_M3_MODEL
    dimension = BGE_M3_DIMENSION

    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    async def embed(self, texts: tuple[str, ...]) -> EmbedOutcome:
        self.calls.append(texts)
        return EmbedOutcome(
            tuple(tuple([0.5] * self.dimension) for _text in texts),
            tuple(None for _text in texts),
        )


class PartiallyFailingEmbedder:
    model = BGE_M3_MODEL
    dimension = BGE_M3_DIMENSION

    async def embed(self, texts: tuple[str, ...]) -> EmbedOutcome:
        vectors: list[tuple[float, ...] | None] = []
        codes: list[str | None] = []
        for text in texts:
            if "bad" in text:
                vectors.append(None)
                codes.append("EMBEDDING_RATE_LIMITED")
            else:
                vectors.append(tuple([0.5] * self.dimension))
                codes.append(None)
        return EmbedOutcome(tuple(vectors), tuple(codes))


@pytest.mark.anyio
async def test_keyword_vectors_are_cached_and_invalidated_when_term_changes(
    db_session: AsyncSession,
) -> None:
    repository = RssSettingsRepository(db_session)
    keyword = await repository.create_keyword(term="AI agents", kind="positive", enabled=True)
    await db_session.commit()
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    embedder = RecordingEmbedder()
    service = KeywordEmbeddingService(factory, embedder)

    assert await service.refresh() == 1
    assert await service.refresh() == 0
    async with factory.begin() as session:
        stored = await session.get(RssKeyword, keyword.id)
        assert stored is not None
        assert stored.embedding_model == BGE_M3_MODEL
        assert stored.embedding_dimension == BGE_M3_DIMENSION
        assert isinstance(stored.embedding_generated_at, datetime)
        assert stored.embedding is not None and len(stored.embedding) == BGE_M3_DIMENSION
        changed = await RssSettingsRepository(session).update_keyword(
            keyword.id,
            term="AI systems",
            kind="positive",
            enabled=True,
        )
        assert changed is not None
        assert changed.embedding is None

    assert await service.refresh() == 1
    assert embedder.calls == [("AI agents",), ("AI systems",)]
    assert "embedding" not in RssItem.__table__.columns


@pytest.mark.anyio
async def test_refresh_persists_successes_and_raises_first_failure_code(
    db_session: AsyncSession,
) -> None:
    repository = RssSettingsRepository(db_session)
    good = await repository.create_keyword(term="good term", kind="positive", enabled=True)
    bad = await repository.create_keyword(term="bad term", kind="positive", enabled=True)
    await db_session.commit()
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    service = KeywordEmbeddingService(factory, PartiallyFailingEmbedder())

    with pytest.raises(EmbeddingError) as caught:
        await service.refresh(force=True)

    assert caught.value.code == "EMBEDDING_RATE_LIMITED"
    async with factory() as session:
        stored_good = await session.get(RssKeyword, good.id)
        stored_bad = await session.get(RssKeyword, bad.id)
        assert stored_good is not None and stored_bad is not None
        assert stored_good.embedding is not None
        assert stored_good.embedding_error is None
        assert stored_bad.embedding is None
        assert stored_bad.embedding_error == "EMBEDDING_RATE_LIMITED"


@pytest.mark.anyio
async def test_embed_temporary_degrades_invalid_vectors(db_session: AsyncSession) -> None:
    class BadVectorEmbedder:
        model = BGE_M3_MODEL
        dimension = BGE_M3_DIMENSION

        async def embed(self, texts: tuple[str, ...]) -> EmbedOutcome:
            return EmbedOutcome(
                (tuple([0.5] * 3), tuple([0.5] * self.dimension)),
                (None, None),
            )

    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    service = KeywordEmbeddingService(factory, BadVectorEmbedder())

    outcome = await service.embed_temporary(("short", "fine"))

    assert outcome.vectors[0] is None
    assert outcome.error_codes[0] == "EMBEDDING_DIMENSION_MISMATCH"
    assert outcome.vectors[1] is not None
    assert outcome.error_codes[1] is None
