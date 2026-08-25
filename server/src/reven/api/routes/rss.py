"""RSS source and keyword configuration routes."""

from uuid import UUID

from fastapi import APIRouter, Query, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy import func, select

from reven.api.dependencies import RssEmbeddingRefresherDep, RssInboxServiceDep, SessionDep
from reven.api.schemas.rss import (
    InboxPushResponse,
    RssCandidatePage,
    RssCandidateResponse,
    RssEmbeddingRebuildResponse,
    RssKeywordCreate,
    RssKeywordResponse,
    RssRunResponse,
    RssSourceCreate,
    RssSourceResponse,
)
from reven.rss.inbox import InboxPushError, InboxPushResult
from reven.rss.models import RssDiscoveryRun, RssItem, RssKeyword, RssSource
from reven.rss.repository import RssSettingsConflictError, RssSettingsRepository

router = APIRouter(prefix="/api/rss", tags=["rss"])


@router.post("/embeddings/rebuild", response_model=RssEmbeddingRebuildResponse)
async def rebuild_keyword_embeddings(
    embeddings: RssEmbeddingRefresherDep,
) -> RssEmbeddingRebuildResponse | JSONResponse:
    try:
        refreshed = await embeddings.refresh(force=True)
    except Exception:
        return _candidate_error(503, "RSS_EMBEDDING_UNAVAILABLE", "关键词向量重建失败")
    return RssEmbeddingRebuildResponse(refreshed=refreshed, model="BAAI/bge-m3", dimension=1024)


@router.get("/runs/latest", response_model=RssRunResponse)
async def latest_run(session: SessionDep) -> RssDiscoveryRun | JSONResponse:
    run = await session.scalar(select(RssDiscoveryRun).order_by(RssDiscoveryRun.run_date.desc()).limit(1))
    if run is None:
        return _candidate_error(404, "RSS_RUN_NOT_FOUND", "RSS 任务记录不存在")
    return run


@router.get("/candidates", response_model=RssCandidatePage)
async def list_candidates(
    session: SessionDep,
    candidate_status: str = Query("candidate", alias="status", max_length=24),
    page: int = Query(1, ge=1),
    page_size: int = Query(30, ge=1, le=100),
) -> RssCandidatePage:
    filters = [RssItem.status == candidate_status]
    total = await session.scalar(select(func.count()).select_from(RssItem).where(*filters))
    result = await session.scalars(
        select(RssItem)
        .where(*filters)
        .order_by(RssItem.published_at.desc().nullslast(), RssItem.first_seen_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return RssCandidatePage(
        items=[RssCandidateResponse.model_validate(item) for item in result],
        total=total or 0,
        page=page,
        page_size=page_size,
    )


@router.post("/candidates/{item_id}/ignore", response_model=RssCandidateResponse)
async def ignore_candidate(item_id: UUID, session: SessionDep) -> RssItem | JSONResponse:
    item = await session.get(RssItem, item_id, with_for_update=True)
    if item is None:
        return _candidate_error(404, "RSS_CANDIDATE_NOT_FOUND", "RSS 候选不存在")
    if item.status == "ignored":
        return item
    if item.status != "candidate":
        return _candidate_error(409, "RSS_CANDIDATE_NOT_IGNORABLE", "RSS 候选当前状态不允许忽略")
    item.status = "ignored"
    await session.commit()
    return item


@router.post("/candidates/{item_id}/confirm", response_model=InboxPushResponse)
async def confirm_candidate(item_id: UUID, inbox: RssInboxServiceDep) -> InboxPushResult | JSONResponse:
    try:
        return await inbox.push(item_id)
    except InboxPushError as exc:
        return _candidate_error(exc.status_code, exc.code, exc.message)


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


def _candidate_error(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"code": code, "message": message})
