import json
from datetime import datetime

import httpx
import pytest
from reven.rss.embedding import (
    BGE_M3_DIMENSION,
    BGE_M3_MODEL,
    EmbeddingError,
    KeywordEmbeddingService,
    SiliconFlowEmbeddingClient,
)
from reven.rss.models import RssItem, RssKeyword
from reven.rss.repository import RssSettingsRepository
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def embedding_response(inputs: int, *, dimension: int = BGE_M3_DIMENSION) -> dict[str, object]:
    return {
        "object": "list",
        "model": BGE_M3_MODEL,
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
        vectors = await SiliconFlowEmbeddingClient("test-key", http=http).embed(("first", "second"))

    assert len(vectors) == 2
    assert len(vectors[0]) == BGE_M3_DIMENSION
    assert vectors[0][0] == 1.0
    assert vectors[1][0] == 2.0


@pytest.mark.anyio
async def test_siliconflow_client_rejects_wrong_dimension() -> None:
    async with httpx.AsyncClient(
        base_url="https://api.siliconflow.cn",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=embedding_response(1, dimension=3))),
    ) as http:
        with pytest.raises(EmbeddingError) as caught:
            await SiliconFlowEmbeddingClient("test-key", http=http).embed(("text",))

    assert caught.value.code == "EMBEDDING_DIMENSION_MISMATCH"


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
        vectors = await SiliconFlowEmbeddingClient("test-key", http=http).embed(
            tuple(f"item-{index}" for index in range(33))
        )

    assert len(vectors) == 33
    assert batch_sizes == [32, 1]


class RecordingEmbedder:
    model = BGE_M3_MODEL
    dimension = BGE_M3_DIMENSION

    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    async def embed(self, texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]:
        self.calls.append(texts)
        return tuple(tuple([0.5] * self.dimension) for _text in texts)


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
