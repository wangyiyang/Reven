"""Persistence interface for RSS configuration."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from reven.rss.models import RssKeyword, RssSource
from reven.rss.normalization import normalize_keyword


class RssSettingsConflictError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class RssSettingsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_source(self, *, name: str, feed_url: str, enabled: bool) -> RssSource:
        source = RssSource(name=name, feed_url=feed_url, enabled=enabled)
        self.session.add(source)
        await _flush_or_conflict(
            self.session,
            code="RSS_SOURCE_URL_CONFLICT",
            message="RSS 源地址已存在",
        )
        return source

    async def list_sources(self) -> list[RssSource]:
        result = await self.session.scalars(select(RssSource).order_by(RssSource.created_at, RssSource.id))
        return list(result)

    async def update_source(
        self,
        source_id: UUID,
        *,
        name: str,
        feed_url: str,
        enabled: bool,
    ) -> RssSource | None:
        source = await self.session.get(RssSource, source_id)
        if source is None:
            return None
        source.name = name
        source.feed_url = feed_url
        source.enabled = enabled
        await _flush_or_conflict(
            self.session,
            code="RSS_SOURCE_URL_CONFLICT",
            message="RSS 源地址已存在",
        )
        return source

    async def delete_source(self, source_id: UUID) -> bool:
        source = await self.session.get(RssSource, source_id)
        if source is None:
            return False
        await self.session.delete(source)
        await self.session.flush()
        return True

    async def create_keyword(self, *, term: str, kind: str, enabled: bool) -> RssKeyword:
        keyword = RssKeyword(
            term=term,
            normalized_term=normalize_keyword(term),
            kind=kind,
            enabled=enabled,
        )
        self.session.add(keyword)
        await _flush_or_conflict(
            self.session,
            code="RSS_KEYWORD_CONFLICT",
            message="关键词已存在于正向或反向列表",
        )
        return keyword

    async def list_keywords(self) -> list[RssKeyword]:
        result = await self.session.scalars(select(RssKeyword).order_by(RssKeyword.created_at, RssKeyword.id))
        return list(result)

    async def update_keyword(
        self,
        keyword_id: UUID,
        *,
        term: str,
        kind: str,
        enabled: bool,
    ) -> RssKeyword | None:
        keyword = await self.session.get(RssKeyword, keyword_id)
        if keyword is None:
            return None
        keyword.term = term
        keyword.normalized_term = normalize_keyword(term)
        keyword.kind = kind
        keyword.enabled = enabled
        await _flush_or_conflict(
            self.session,
            code="RSS_KEYWORD_CONFLICT",
            message="关键词已存在于正向或反向列表",
        )
        return keyword

    async def delete_keyword(self, keyword_id: UUID) -> bool:
        keyword = await self.session.get(RssKeyword, keyword_id)
        if keyword is None:
            return False
        await self.session.delete(keyword)
        await self.session.flush()
        return True


async def _flush_or_conflict(
    session: AsyncSession,
    *,
    code: str,
    message: str,
) -> None:
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise RssSettingsConflictError(code, message) from exc
