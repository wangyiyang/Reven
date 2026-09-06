"""品牌与发布设置路由。"""

from pathlib import Path
from typing import Annotated, Any
from uuid import UUID

import httpx
from fastapi import APIRouter, Body, Query, Response, status
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from reven.api.dependencies import SessionDep, SessionFactoryDep
from reven.api.schemas.brand import (
    BlogTemplatePayload,
    BrandAssetCreatedResponse,
    BrandAssetResponse,
    BrandAssetUpdate,
    BrandProfilePayload,
    BrandProfileResponse,
    BrandVersionResponse,
    ChannelTemplateResponse,
    ImportNotionRequest,
    ImportRunResponse,
    TemplateVersionResponse,
    WeChatTemplatePayload,
)
from reven.brand.domain import BrandAssetPurpose, BrandAssetSource
from reven.brand.images import sniff_image_mime
from reven.brand.migration import VI_HUB_PAGE_ID, ViHubImporter
from reven.brand.models import BrandVersion, ChannelTemplateVersion
from reven.brand.repository import BrandRepository
from reven.brand.service import BrandError, BrandService, parse_channel_key
from reven.config import get_settings
from reven.content_sync.downloader import SecureContentDownloader
from reven.domain import TargetChannel
from reven.integrations.notion.client import NotionClient
from reven.integrations.notion.configuration import IntegrationConfigurationError, load_notion_config
from reven.integrations.notion.service import NOTION_BASE_URL, REQUEST_TIMEOUT
from reven.integrations.tencent_cos.configuration import TencentCosConfigurationError
from reven.integrations.tencent_cos.store import build_tencent_cos_asset_store

router = APIRouter(prefix="/api/brand", tags=["brand"])

MAX_UPLOAD_BYTES = 10 * 1024 * 1024


def _error(http_status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=http_status, content={"detail": message, "code": code})


def _brand_error(exc: BrandError) -> JSONResponse:
    http_status = status.HTTP_409_CONFLICT if exc.code == "draft_not_found" else status.HTTP_400_BAD_REQUEST
    return _error(http_status, exc.code, str(exc))


def _parse_channel(channel: str) -> TargetChannel | JSONResponse:
    try:
        return parse_channel_key(channel)
    except BrandError as exc:
        return _error(status.HTTP_404_NOT_FOUND, exc.code, str(exc))


# ---- 品牌档案 ----


@router.get("/profile", response_model=BrandProfileResponse)
async def get_profile(session: SessionDep) -> BrandProfileResponse:
    repo = BrandRepository(session)
    published = await repo.published_brand()
    draft = await repo.draft_brand()
    return BrandProfileResponse(
        published=BrandVersionResponse.model_validate(published) if published else None,
        draft=BrandVersionResponse.model_validate(draft) if draft else None,
    )


@router.put("/profile/draft", response_model=BrandVersionResponse)
async def upsert_profile_draft(payload: BrandProfilePayload, session: SessionDep) -> BrandVersion:
    return await BrandService(BrandRepository(session)).upsert_brand_draft(payload.model_dump(mode="json"))


@router.post("/profile/publish", response_model=BrandVersionResponse)
async def publish_profile(session: SessionDep) -> BrandVersion | JSONResponse:
    try:
        return await BrandService(BrandRepository(session)).publish_brand()
    except BrandError as exc:
        return _brand_error(exc)


@router.get("/profile/versions", response_model=list[BrandVersionResponse])
async def list_profile_versions(session: SessionDep) -> list[BrandVersion]:
    return await BrandRepository(session).list_brand_versions()


# ---- 品牌素材 ----


@router.get("/assets", response_model=list[BrandAssetResponse])
async def list_assets(
    session: SessionDep,
    purpose: Annotated[str | None, Query(max_length=32)] = None,
    enabled: bool | None = None,
) -> list[BrandAssetResponse]:
    assets = await BrandRepository(session).list_assets(purpose, enabled)
    return [BrandAssetResponse.model_validate(asset) for asset in assets]


@router.post("/assets", response_model=BrandAssetCreatedResponse)
async def upload_asset(
    session: SessionDep,
    response: Response,
    purpose: Annotated[str, Query(max_length=32)],
    label: Annotated[str, Query(min_length=1, max_length=200)],
    content: Annotated[bytes, Body()],
) -> BrandAssetCreatedResponse | JSONResponse:
    if purpose not in {item.value for item in BrandAssetPurpose}:
        return _error(status.HTTP_422_UNPROCESSABLE_ENTITY, "purpose_unknown", f"未知素材用途：{purpose}")
    if not content or len(content) > MAX_UPLOAD_BYTES:
        return _error(status.HTTP_422_UNPROCESSABLE_ENTITY, "upload_invalid", "文件为空或超过 10MB 上限")
    mime_type = sniff_image_mime(content)
    if mime_type is None:
        return _error(status.HTTP_422_UNPROCESSABLE_ENTITY, "upload_not_image", "仅支持 PNG/JPEG/GIF/WebP 图片")
    try:
        store = build_tencent_cos_asset_store(get_settings())
    except TencentCosConfigurationError as exc:
        return _error(status.HTTP_503_SERVICE_UNAVAILABLE, "cos_not_configured", str(exc))
    try:
        asset, created = await BrandService(BrandRepository(session)).register_asset(
            store,
            content,
            mime_type=mime_type,
            purpose=purpose,
            label=label,
            source=BrandAssetSource.UPLOAD,
        )
    finally:
        await store.aclose()
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return BrandAssetCreatedResponse(asset=BrandAssetResponse.model_validate(asset), created=created)


@router.patch("/assets/{asset_id}", response_model=BrandAssetResponse)
async def update_asset(
    asset_id: UUID, payload: BrandAssetUpdate, session: SessionDep
) -> BrandAssetResponse | JSONResponse:
    repo = BrandRepository(session)
    asset = await repo.get_asset(asset_id)
    if asset is None:
        return _error(status.HTTP_404_NOT_FOUND, "asset_not_found", "素材不存在")
    updated = await BrandService(repo).update_asset(asset, label=payload.label, enabled=payload.enabled)
    return BrandAssetResponse.model_validate(updated)


# ---- 渠道模板 ----


@router.get("/templates/{channel}", response_model=ChannelTemplateResponse)
async def get_template(channel: str, session: SessionDep) -> ChannelTemplateResponse | JSONResponse:
    target = _parse_channel(channel)
    if isinstance(target, JSONResponse):
        return target
    repo = BrandRepository(session)
    published = await repo.published_template(str(target))
    draft = await repo.draft_template(str(target))
    return ChannelTemplateResponse(
        published=TemplateVersionResponse.model_validate(published) if published else None,
        draft=TemplateVersionResponse.model_validate(draft) if draft else None,
    )


@router.put("/templates/{channel}/draft", response_model=TemplateVersionResponse)
async def upsert_template_draft(
    channel: str,
    session: SessionDep,
    body: Annotated[dict[str, Any], Body()],
) -> ChannelTemplateVersion | JSONResponse:
    target = _parse_channel(channel)
    if isinstance(target, JSONResponse):
        return target
    model = BlogTemplatePayload if target == TargetChannel.BLOG else WeChatTemplatePayload
    try:
        payload = model.model_validate(body)
    except ValidationError as exc:
        return _error(status.HTTP_422_UNPROCESSABLE_ENTITY, "payload_invalid", exc.errors()[0]["msg"])
    return await BrandService(BrandRepository(session)).upsert_template_draft(target, payload.model_dump(mode="json"))


@router.post("/templates/{channel}/publish", response_model=TemplateVersionResponse)
async def publish_template(channel: str, session: SessionDep) -> ChannelTemplateVersion | JSONResponse:
    target = _parse_channel(channel)
    if isinstance(target, JSONResponse):
        return target
    try:
        return await BrandService(BrandRepository(session)).publish_template(target)
    except BrandError as exc:
        return _brand_error(exc)


@router.get("/templates/{channel}/versions", response_model=list[TemplateVersionResponse])
async def list_template_versions(channel: str, session: SessionDep) -> list[ChannelTemplateVersion] | JSONResponse:
    target = _parse_channel(channel)
    if isinstance(target, JSONResponse):
        return target
    return await BrandRepository(session).list_template_versions(str(target))


# ---- Notion VI Hub 迁移 ----


@router.post("/import/notion", response_model=ImportRunResponse)
async def import_notion_vi_hub(
    payload: ImportNotionRequest,
    factory: SessionFactoryDep,
) -> ImportRunResponse | JSONResponse:
    """一次性迁移 VI Hub；dry_run 预演不写库，execute 幂等（已成功迁移过则返回既有记录）。"""
    try:
        token, _data_source_id = await load_notion_config(factory)
    except IntegrationConfigurationError as exc:
        return _error(status.HTTP_409_CONFLICT, "notion_not_configured", f"Notion 集成不可用：{exc}")
    try:
        store = build_tencent_cos_asset_store(get_settings())
    except TencentCosConfigurationError as exc:
        return _error(status.HTTP_503_SERVICE_UNAVAILABLE, "cos_not_configured", str(exc))
    settings = get_settings()
    try:
        async with httpx.AsyncClient(base_url=NOTION_BASE_URL, timeout=REQUEST_TIMEOUT) as http:
            notion = NotionClient(token=token, http=http)
            async with factory() as session:
                downloader = SecureContentDownloader(Path(settings.job_data_dir))
                run = await ViHubImporter(session, notion, downloader, store).run(
                    page_id=VI_HUB_PAGE_ID, dry_run=payload.dry_run
                )
    finally:
        await store.aclose()
    return ImportRunResponse.model_validate(run)


@router.get("/import/runs", response_model=list[ImportRunResponse])
async def list_import_runs(session: SessionDep) -> list[ImportRunResponse]:
    runs = await BrandRepository(session).list_import_runs()
    return [ImportRunResponse.model_validate(run) for run in runs]
