"""品牌领域持久化访问。"""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from reven.brand.domain import BrandVersionStatus, ImportRunStatus
from reven.brand.models import BrandAsset, BrandImportRun, BrandVersion, ChannelTemplateVersion


class BrandRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ---- 品牌档案版本 ----

    async def published_brand(self) -> BrandVersion | None:
        return await self._brand_by_status(BrandVersionStatus.PUBLISHED)

    async def draft_brand(self) -> BrandVersion | None:
        return await self._brand_by_status(BrandVersionStatus.DRAFT)

    async def _brand_by_status(self, status: BrandVersionStatus) -> BrandVersion | None:
        stmt = select(BrandVersion).where(BrandVersion.status == status)
        row: BrandVersion | None = await self.session.scalar(stmt)
        return row

    async def list_brand_versions(self) -> list[BrandVersion]:
        stmt = select(BrandVersion).order_by(BrandVersion.version.desc())
        return list(await self.session.scalars(stmt))

    async def next_brand_version(self) -> int:
        stmt = select(func.max(BrandVersion.version))
        return ((await self.session.scalar(stmt)) or 0) + 1

    # ---- 渠道模板版本 ----

    async def published_template(self, channel: str) -> ChannelTemplateVersion | None:
        return await self._template_by_status(channel, BrandVersionStatus.PUBLISHED)

    async def draft_template(self, channel: str) -> ChannelTemplateVersion | None:
        return await self._template_by_status(channel, BrandVersionStatus.DRAFT)

    async def _template_by_status(self, channel: str, status: BrandVersionStatus) -> ChannelTemplateVersion | None:
        stmt = select(ChannelTemplateVersion).where(
            ChannelTemplateVersion.channel == channel,
            ChannelTemplateVersion.status == status,
        )
        row: ChannelTemplateVersion | None = await self.session.scalar(stmt)
        return row

    async def list_template_versions(self, channel: str) -> list[ChannelTemplateVersion]:
        stmt = (
            select(ChannelTemplateVersion)
            .where(ChannelTemplateVersion.channel == channel)
            .order_by(ChannelTemplateVersion.version.desc())
        )
        return list(await self.session.scalars(stmt))

    async def next_template_version(self, channel: str) -> int:
        stmt = select(func.max(ChannelTemplateVersion.version)).where(ChannelTemplateVersion.channel == channel)
        return ((await self.session.scalar(stmt)) or 0) + 1

    # ---- 品牌素材 ----

    async def list_assets(self, purpose: str | None, enabled: bool | None) -> list[BrandAsset]:
        stmt = select(BrandAsset)
        if purpose:
            stmt = stmt.where(BrandAsset.purpose == purpose)
        if enabled is not None:
            stmt = stmt.where(BrandAsset.enabled == enabled)
        stmt = stmt.order_by(BrandAsset.created_at.desc())
        return list(await self.session.scalars(stmt))

    async def get_asset(self, asset_id: UUID) -> BrandAsset | None:
        return await self.session.get(BrandAsset, asset_id)

    async def asset_by_sha256(self, sha256: str) -> BrandAsset | None:
        stmt = select(BrandAsset).where(BrandAsset.sha256 == sha256)
        row: BrandAsset | None = await self.session.scalar(stmt)
        return row

    async def assets_by_ids(self, ids: list[UUID]) -> list[BrandAsset]:
        if not ids:
            return []
        stmt = select(BrandAsset).where(BrandAsset.id.in_(ids))
        return list(await self.session.scalars(stmt))

    # ---- 迁移记录 ----

    async def successful_import_run(self, notion_page_id: str) -> BrandImportRun | None:
        stmt = (
            select(BrandImportRun)
            .where(
                BrandImportRun.notion_page_id == notion_page_id,
                BrandImportRun.dry_run.is_(False),
                BrandImportRun.status == ImportRunStatus.COMPLETED,
            )
            .order_by(BrandImportRun.created_at.desc())
            .limit(1)
        )
        row: BrandImportRun | None = await self.session.scalar(stmt)
        return row

    async def list_import_runs(self, notion_page_id: str | None = None) -> list[BrandImportRun]:
        stmt = select(BrandImportRun)
        if notion_page_id:
            stmt = stmt.where(BrandImportRun.notion_page_id == notion_page_id)
        stmt = stmt.order_by(BrandImportRun.created_at.desc())
        return list(await self.session.scalars(stmt))

    # ---- 通用 ----

    def add(self, row: BrandVersion | ChannelTemplateVersion | BrandAsset | BrandImportRun) -> None:
        self.session.add(row)

    async def flush(self) -> None:
        await self.session.flush()

    async def commit(self) -> None:
        await self.session.commit()
