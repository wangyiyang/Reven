"""RSS source and keyword configuration routes."""

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Query, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy import select

from reven.api.dependencies import CandidateStoreDep, RssEmbeddingRefresherDep, SessionDep
from reven.api.schemas.rss import (
    RssCandidatePage,
    RssCandidateResponse,
    RssEmbeddingRebuildResponse,
    RssKeywordCreate,
    RssKeywordResponse,
    RssRunResponse,
    RssSourceCreate,
    RssSourceResponse,
)
from reven.rss.bitable_store import BitableCandidate, BitableCandidateStoreError
from reven.rss.models import RssDiscoveryRun, RssKeyword, RssSource
from reven.rss.repository import RssSettingsConflictError, RssSettingsRepository

router = APIRouter(prefix="/api/rss", tags=["rss"])

CandidateStatus = Literal["candidate", "saved", "ignored"]


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
    store: CandidateStoreDep,
    candidate_status: CandidateStatus = Query("candidate", alias="status"),
    cursor: str | None = Query(None, max_length=200),
    page_size: int = Query(30, ge=1, le=100),
) -> RssCandidatePage | JSONResponse:
    try:
        page = await store.list_candidates(status=candidate_status, page_size=page_size, cursor=cursor)
    except BitableCandidateStoreError as exc:
        return _candidate_error(exc.status_code, exc.code, exc.message)
    return RssCandidatePage(
        items=[_candidate_response(item) for item in page.items],
        total=page.total,
        next_cursor=page.next_cursor,
    )


@router.post("/candidates/{record_id}/ignore", response_model=RssCandidateResponse)
async def ignore_candidate(record_id: str, store: CandidateStoreDep) -> RssCandidateResponse | JSONResponse:
    try:
        return _candidate_response(await store.set_status(record_id, "ignored"))
    except BitableCandidateStoreError as exc:
        return _candidate_error(exc.status_code, exc.code, exc.message)


@router.post("/candidates/{record_id}/confirm", response_model=RssCandidateResponse)
async def confirm_candidate(record_id: str, store: CandidateStoreDep) -> RssCandidateResponse | JSONResponse:
    try:
        return _candidate_response(await store.set_status(record_id, "saved"))
    except BitableCandidateStoreError as exc:
        return _candidate_error(exc.status_code, exc.code, exc.message)


def _candidate_response(candidate: BitableCandidate) -> RssCandidateResponse:
    return RssCandidateResponse(
        record_id=candidate.record_id,
        title=candidate.title,
        summary=candidate.summary,
        source_name=candidate.source_name,
        published_at=candidate.published_at,
        url=candidate.url,
        status=candidate.status,
        matched_keywords=list(candidate.matched_keywords),
        archived_at=candidate.archived_at,
        dedupe_key=candidate.dedupe_key,
    )


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
