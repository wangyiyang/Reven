"""RSS source and keyword configuration routes."""

from uuid import UUID

from fastapi import APIRouter, Response, status
from fastapi.responses import JSONResponse

from reven.api.dependencies import SessionDep
from reven.api.schemas.rss import RssKeywordCreate, RssKeywordResponse, RssSourceCreate, RssSourceResponse
from reven.rss.models import RssKeyword, RssSource
from reven.rss.repository import RssSettingsConflictError, RssSettingsRepository

router = APIRouter(prefix="/api/rss", tags=["rss"])


@router.get("/sources", response_model=list[RssSourceResponse])
async def list_sources(session: SessionDep) -> list[RssSource]:
    return await RssSettingsRepository(session).list_sources()


@router.post("/sources", response_model=RssSourceResponse, status_code=status.HTTP_201_CREATED)
async def create_source(body: RssSourceCreate, session: SessionDep) -> RssSource | JSONResponse:
    try:
        source = await RssSettingsRepository(session).create_source(
            name=body.name,
            feed_url=str(body.feed_url),
            enabled=body.enabled,
        )
    except RssSettingsConflictError as exc:
        return _conflict_response(exc)
    await session.commit()
    return source


@router.put("/sources/{source_id}", response_model=RssSourceResponse)
async def update_source(
    source_id: UUID,
    body: RssSourceCreate,
    session: SessionDep,
) -> RssSource | JSONResponse:
    try:
        source = await RssSettingsRepository(session).update_source(
            source_id,
            name=body.name,
            feed_url=str(body.feed_url),
            enabled=body.enabled,
        )
    except RssSettingsConflictError as exc:
        return _conflict_response(exc)
    if source is None:
        return JSONResponse(
            status_code=404,
            content={"code": "RSS_SOURCE_NOT_FOUND", "message": "RSS 源不存在"},
        )
    await session.commit()
    return source


@router.delete(
    "/sources/{source_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_source(source_id: UUID, session: SessionDep) -> Response:
    deleted = await RssSettingsRepository(session).delete_source(source_id)
    if not deleted:
        return JSONResponse(
            status_code=404,
            content={"code": "RSS_SOURCE_NOT_FOUND", "message": "RSS 源不存在"},
        )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/keywords", response_model=list[RssKeywordResponse])
async def list_keywords(session: SessionDep) -> list[RssKeyword]:
    return await RssSettingsRepository(session).list_keywords()


@router.post("/keywords", response_model=RssKeywordResponse, status_code=status.HTTP_201_CREATED)
async def create_keyword(body: RssKeywordCreate, session: SessionDep) -> RssKeyword | JSONResponse:
    try:
        keyword = await RssSettingsRepository(session).create_keyword(
            term=body.term,
            kind=body.kind,
            enabled=body.enabled,
        )
    except RssSettingsConflictError as exc:
        return _conflict_response(exc)
    await session.commit()
    return keyword


@router.put("/keywords/{keyword_id}", response_model=RssKeywordResponse)
async def update_keyword(
    keyword_id: UUID,
    body: RssKeywordCreate,
    session: SessionDep,
) -> RssKeyword | JSONResponse:
    try:
        keyword = await RssSettingsRepository(session).update_keyword(
            keyword_id,
            term=body.term,
            kind=body.kind,
            enabled=body.enabled,
        )
    except RssSettingsConflictError as exc:
        return _conflict_response(exc)
    if keyword is None:
        return JSONResponse(
            status_code=404,
            content={"code": "RSS_KEYWORD_NOT_FOUND", "message": "关键词不存在"},
        )
    await session.commit()
    return keyword


@router.delete(
    "/keywords/{keyword_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_keyword(keyword_id: UUID, session: SessionDep) -> Response:
    deleted = await RssSettingsRepository(session).delete_keyword(keyword_id)
    if not deleted:
        return JSONResponse(
            status_code=404,
            content={"code": "RSS_KEYWORD_NOT_FOUND", "message": "关键词不存在"},
        )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _conflict_response(exc: RssSettingsConflictError) -> JSONResponse:
    return JSONResponse(
        status_code=409,
        content={"code": exc.code, "message": exc.message},
    )
