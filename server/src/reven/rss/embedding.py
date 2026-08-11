"""SiliconFlow BGE-M3 adapter and persistent keyword-vector lifecycle."""

import hashlib
import json
import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, NoReturn, Protocol
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from reven.rss.models import RssKeyword
from reven.scheduling import utc_now

BGE_M3_MODEL = "BAAI/bge-m3"
BGE_M3_DIMENSION = 1024
MAX_EMBEDDING_RESPONSE_BYTES = 4 * 1024 * 1024
EMBEDDING_BATCH_SIZE = 32


class EmbeddingError(Exception):
    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class Embedder(Protocol):
    model: str
    dimension: int

    async def embed(self, texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]: ...


class SiliconFlowEmbeddingClient:
    model = BGE_M3_MODEL
    dimension = BGE_M3_DIMENSION

    def __init__(self, api_key: str, *, http: httpx.AsyncClient) -> None:
        if not api_key:
            raise ValueError("SiliconFlow API Key 不能为空")
        if http.base_url.scheme != "https" or http.base_url.host != "api.siliconflow.cn":
            raise ValueError("SiliconFlow 客户端必须使用官方 HTTPS API")
        self._api_key = api_key
        self._http = http

    async def embed(self, texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]:
        if not texts or any(not text.strip() for text in texts):
            raise EmbeddingError("EMBEDDING_INPUT_INVALID", "Embedding 输入不能为空")
        vectors: list[tuple[float, ...]] = []
        for start in range(0, len(texts), EMBEDDING_BATCH_SIZE):
            vectors.extend(await self._embed_batch(texts[start : start + EMBEDDING_BATCH_SIZE]))
        return tuple(vectors)

    async def _embed_batch(self, texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]:
        try:
            async with self._http.stream(
                "POST",
                "/v1/embeddings",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={"model": self.model, "input": list(texts), "encoding_format": "float"},
            ) as response:
                body = await _read_bounded(response)
                status = response.status_code
        except httpx.TimeoutException as exc:
            raise EmbeddingError("EMBEDDING_TIMEOUT", "Embedding 请求超时", retryable=True) from exc
        except httpx.HTTPError as exc:
            raise EmbeddingError("EMBEDDING_NETWORK_ERROR", "Embedding 网络请求失败", retryable=True) from exc
        if not 200 <= status < 300:
            _raise_for_status(status)
        return _parse_response(body, len(texts))


@dataclass(frozen=True)
class _PendingKeyword:
    id: UUID
    term: str
    normalized_term: str


class KeywordEmbeddingService:
    def __init__(self, factory: async_sessionmaker[AsyncSession], embedder: Embedder) -> None:
        self._factory = factory
        self._embedder = embedder

    async def refresh(self, *, force: bool = False) -> int:
        pending = await self._pending(force=force)
        if not pending:
            return 0
        try:
            vectors = await self._embedder.embed(tuple(item.term for item in pending))
            _validate_vectors(vectors, len(pending), self._embedder.dimension)
        except Exception as exc:
            await self._record_error(pending, type(exc).__name__)
            raise
        return await self._persist(pending, vectors)

    async def embed_temporary(self, texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]:
        vectors = await self._embedder.embed(texts)
        _validate_vectors(vectors, len(texts), self._embedder.dimension)
        return vectors

    async def _pending(self, *, force: bool) -> tuple[_PendingKeyword, ...]:
        async with self._factory() as session:
            keywords = list(
                (
                    await session.scalars(
                        select(RssKeyword).where(RssKeyword.enabled.is_(True)).order_by(RssKeyword.id)
                    )
                ).all()
            )
        return tuple(
            _PendingKeyword(keyword.id, keyword.term, keyword.normalized_term)
            for keyword in keywords
            if force or _is_stale(keyword, self._embedder)
        )

    async def _persist(
        self,
        pending: tuple[_PendingKeyword, ...],
        vectors: tuple[tuple[float, ...], ...],
    ) -> int:
        saved = 0
        async with self._factory.begin() as session:
            for item, vector in zip(pending, vectors, strict=True):
                keyword = await session.get(RssKeyword, item.id, with_for_update=True)
                if keyword is None or keyword.normalized_term != item.normalized_term:
                    continue
                keyword.embedding = list(vector)
                keyword.embedding_model = self._embedder.model
                keyword.embedding_dimension = self._embedder.dimension
                keyword.embedding_term_hash = _term_hash(item.normalized_term)
                keyword.embedding_generated_at = utc_now()
                keyword.embedding_error = None
                saved += 1
        return saved

    async def _record_error(self, pending: tuple[_PendingKeyword, ...], error_type: str) -> None:
        async with self._factory.begin() as session:
            keywords = list(
                (
                    await session.scalars(
                        select(RssKeyword).where(RssKeyword.id.in_([item.id for item in pending])).with_for_update()
                    )
                ).all()
            )
            for keyword in keywords:
                keyword.embedding_error = error_type[:120]


def _is_stale(keyword: RssKeyword, embedder: Embedder) -> bool:
    return (
        keyword.embedding is None
        or keyword.embedding_model != embedder.model
        or keyword.embedding_dimension != embedder.dimension
        or keyword.embedding_term_hash != _term_hash(keyword.normalized_term)
        or len(keyword.embedding) != embedder.dimension
    )


def _validate_vectors(vectors: Sequence[Sequence[float]], expected: int, dimension: int) -> None:
    if len(vectors) != expected or any(len(vector) != dimension for vector in vectors):
        raise EmbeddingError("EMBEDDING_DIMENSION_MISMATCH", "Embedding 返回数量或维度不一致")
    if any(not math.isfinite(value) for vector in vectors for value in vector):
        raise EmbeddingError("EMBEDDING_VALUE_INVALID", "Embedding 包含非有限数值")


async def _read_bounded(response: httpx.Response) -> bytes:
    chunks: list[bytes] = []
    size = 0
    async for chunk in response.aiter_bytes():
        size += len(chunk)
        if size > MAX_EMBEDDING_RESPONSE_BYTES:
            raise EmbeddingError("EMBEDDING_RESPONSE_TOO_LARGE", "Embedding 响应超过大小限制")
        chunks.append(chunk)
    return b"".join(chunks)


def _parse_response(body: bytes, expected: int) -> tuple[tuple[float, ...], ...]:
    try:
        payload: Any = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EmbeddingError("EMBEDDING_RESPONSE_INVALID", "Embedding 响应不是有效 JSON") from exc
    if not isinstance(payload, dict) or payload.get("model") != BGE_M3_MODEL:
        raise EmbeddingError("EMBEDDING_MODEL_MISMATCH", "Embedding 响应模型不匹配")
    data = payload.get("data")
    if not isinstance(data, list) or len(data) != expected:
        raise EmbeddingError("EMBEDDING_RESPONSE_INVALID", "Embedding 响应数量不匹配")
    ordered: list[tuple[float, ...] | None] = [None] * expected
    for item in data:
        index, vector = _parse_item(item, expected)
        if ordered[index] is not None:
            raise EmbeddingError("EMBEDDING_RESPONSE_INVALID", "Embedding 响应索引重复")
        ordered[index] = vector
    if any(vector is None for vector in ordered):
        raise EmbeddingError("EMBEDDING_RESPONSE_INVALID", "Embedding 响应索引缺失")
    result = tuple(vector for vector in ordered if vector is not None)
    _validate_vectors(result, expected, BGE_M3_DIMENSION)
    return result


def _parse_item(item: object, expected: int) -> tuple[int, tuple[float, ...]]:
    if not isinstance(item, dict):
        raise EmbeddingError("EMBEDDING_RESPONSE_INVALID", "Embedding 数据项无效")
    index = item.get("index")
    raw_vector = item.get("embedding")
    if not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < expected:
        raise EmbeddingError("EMBEDDING_RESPONSE_INVALID", "Embedding 索引无效")
    if not isinstance(raw_vector, list):
        raise EmbeddingError("EMBEDDING_RESPONSE_INVALID", "Embedding 向量无效")
    if any(not isinstance(value, (int, float)) or isinstance(value, bool) for value in raw_vector):
        raise EmbeddingError("EMBEDDING_VALUE_INVALID", "Embedding 向量包含非法数值")
    return index, tuple(float(value) for value in raw_vector)


def _raise_for_status(status: int) -> NoReturn:
    retryable = status == 429 or status >= 500
    code = "EMBEDDING_RATE_LIMITED" if status == 429 else "EMBEDDING_HTTP_ERROR"
    raise EmbeddingError(code, f"Embedding 请求失败（HTTP {status}）", retryable=retryable)


def _term_hash(normalized_term: str) -> str:
    return hashlib.sha256(normalized_term.encode()).hexdigest()
