"""品牌领域业务流转：草稿编辑、版本发布、素材登记。"""

import hashlib
from uuid import UUID

from reven.brand.application import template_asset_ids
from reven.brand.domain import BrandVersionSource, BrandVersionStatus
from reven.brand.images import image_dimensions
from reven.brand.models import BrandAsset, BrandVersion, ChannelTemplateVersion
from reven.brand.repository import BrandRepository
from reven.content_sync.media_archive import ContentAssetStore
from reven.domain import TargetChannel
from reven.scheduling import utc_now


class BrandError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class DraftNotFoundError(BrandError):
    def __init__(self, target: str) -> None:
        super().__init__("draft_not_found", f"{target}不存在草稿，无法发布")


class ReferencedAssetsMissingError(BrandError):
    def __init__(self, missing: list[UUID]) -> None:
        super().__init__("template_assets_missing", f"模板引用的素材不存在：{', '.join(str(item) for item in missing)}")


CHANNEL_KEYS = {"blog": TargetChannel.BLOG, "wechat": TargetChannel.WECHAT}


def parse_channel_key(key: str) -> TargetChannel:
    channel = CHANNEL_KEYS.get(key)
    if channel is None:
        raise BrandError("channel_unknown", f"未知渠道：{key}")
    return channel


class BrandService:
    def __init__(self, repository: BrandRepository) -> None:
        self.repo = repository

    # ---- 品牌档案 ----

    async def upsert_brand_draft(self, payload: dict[str, object]) -> BrandVersion:
        draft = await self.repo.draft_brand()
        if draft is not None:
            draft.payload = payload
            draft.source = BrandVersionSource.MANUAL
            await self.repo.commit()
            return draft
        draft = BrandVersion(
            version=await self.repo.next_brand_version(),
            status=BrandVersionStatus.DRAFT,
            payload=payload,
            source=BrandVersionSource.MANUAL,
        )
        self.repo.add(draft)
        await self.repo.commit()
        return draft

    async def publish_brand(self) -> BrandVersion:
        draft = await self.repo.draft_brand()
        if draft is None:
            raise DraftNotFoundError("品牌档案")
        published = await self.repo.published_brand()
        now = utc_now()
        if published is not None:
            published.status = BrandVersionStatus.ARCHIVED
            await self.repo.flush()
        draft.status = BrandVersionStatus.PUBLISHED
        draft.published_at = now
        await self.repo.commit()
        return draft

    # ---- 渠道模板 ----

    async def upsert_template_draft(self, channel: TargetChannel, payload: dict[str, object]) -> ChannelTemplateVersion:
        draft = await self.repo.draft_template(channel)
        if draft is not None:
            draft.payload = payload
            await self.repo.commit()
            return draft
        draft = ChannelTemplateVersion(
            channel=str(channel),
            version=await self.repo.next_template_version(str(channel)),
            status=BrandVersionStatus.DRAFT,
            payload=payload,
        )
        self.repo.add(draft)
        await self.repo.commit()
        return draft

    async def publish_template(self, channel: TargetChannel) -> ChannelTemplateVersion:
        draft = await self.repo.draft_template(channel)
        if draft is None:
            raise DraftNotFoundError(f"{channel}模板")
        await self._assert_template_assets_exist(draft)
        published = await self.repo.published_template(channel)
        now = utc_now()
        if published is not None:
            published.status = BrandVersionStatus.ARCHIVED
            await self.repo.flush()
        draft.status = BrandVersionStatus.PUBLISHED
        draft.published_at = now
        await self.repo.commit()
        return draft

    async def _assert_template_assets_exist(self, draft: ChannelTemplateVersion) -> None:
        referenced = template_asset_ids(draft.payload)
        existing = {asset.id for asset in await self.repo.assets_by_ids(referenced)}
        missing = [asset_id for asset_id in referenced if asset_id not in existing]
        if missing:
            raise ReferencedAssetsMissingError(missing)

    # ---- 品牌素材 ----

    async def register_asset(
        self,
        store: ContentAssetStore,
        content: bytes,
        *,
        mime_type: str,
        purpose: str,
        label: str,
        source: str,
        source_ref: str | None = None,
    ) -> tuple[BrandAsset, bool]:
        """归档素材内容并登记；按 sha256 去重，已存在时返回既有记录。"""
        sha256 = hashlib.sha256(content).hexdigest()
        existing = await self.repo.asset_by_sha256(sha256)
        if existing is not None:
            return existing, False
        archived = await store.archive(content, sha256=sha256, mime_type=mime_type)
        dimensions = image_dimensions(content, mime_type)
        asset = BrandAsset(
            purpose=purpose,
            label=label,
            storage_key=archived.key,
            public_url=archived.public_url,
            sha256=sha256,
            mime_type=mime_type,
            byte_size=len(content),
            width=dimensions[0] if dimensions else None,
            height=dimensions[1] if dimensions else None,
            source=source,
            source_ref=source_ref,
        )
        self.repo.add(asset)
        await self.repo.commit()
        return asset, True

    async def update_asset(self, asset: BrandAsset, *, label: str | None, enabled: bool | None) -> BrandAsset:
        if label is not None:
            asset.label = label
        if enabled is not None:
            asset.enabled = enabled
        await self.repo.commit()
        return asset

