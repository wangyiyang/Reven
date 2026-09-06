"""Render WeChat preview from the one current immutable snapshot."""

from pathlib import Path
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from reven.brand.application import (
    apply_wechat_template,
    resolve_brand_config,
    template_asset_ids,
    wechat_theme_params,
)
from reven.brand.repository import BrandRepository
from reven.config import get_settings
from reven.content_sync.configured import ConfiguredAssetIntegrityVerifier, ConfiguredContentSource
from reven.content_sync.gate import CurrentSnapshotGate, CurrentSnapshotView
from reven.publishing.wechat.factory import _renderer_parts
from reven.publishing.wechat.renderer import WechatRenderer, WechatTheme, theme_from_params


class PreviewConflictError(RuntimeError):
    pass


class PreviewValidationError(RuntimeError):
    pass


MAX_PREVIEW_MARKDOWN_BYTES = 1024 * 1024
MAX_PREVIEW_IMAGES = 100


class ConfiguredWechatPreview:
    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        renderer_command: str,
    ) -> None:
        self.factory = factory
        self.gate = CurrentSnapshotGate(
            factory,
            ConfiguredContentSource(factory),
            ConfiguredAssetIntegrityVerifier(get_settings()),
        )
        self.renderer_command = renderer_command

    async def render_current(self, article_id: UUID) -> str:
        snapshot = await self.gate.require(article_id)
        markdown = _snapshot_body_with_public_urls(snapshot)
        executable, cli_path = _renderer_parts(self.renderer_command)
        renderer = WechatRenderer(
            executable,
            Path(cli_path),
            sandbox_executable=Path("/usr/bin/bwrap"),
        )
        theme, markdown = await self._apply_brand(markdown, snapshot)
        return await renderer.render(markdown, theme)

    async def _apply_brand(self, markdown: str, snapshot: CurrentSnapshotView) -> tuple[WechatTheme | None, str]:
        """预览套用当前已发布品牌配置；无已发布品牌时完全回落 legacy 渲染。"""
        async with self.factory() as session:
            resolved = await resolve_brand_config(session)
            if resolved is None:
                return None, markdown
            payload = resolved.wechat_template_payload
            assets = {}
            if payload is not None:
                repository = BrandRepository(session)
                assets = {a.id: a for a in await repository.assets_by_ids(template_asset_ids(payload))}
            application = apply_wechat_template(
                markdown,
                resolved.brand_payload,
                payload,
                assets,
                embedded_sha256=tuple(asset.sha256 for asset in snapshot.assets),
            )
            if application.errors:
                reason = "；".join(issue.message for issue in application.errors)
                raise PreviewValidationError(f"品牌模板应用失败：{reason}")
            theme = theme_from_params(wechat_theme_params(resolved.brand_payload, payload))
            return theme, application.markdown


def _snapshot_body_with_public_urls(snapshot: CurrentSnapshotView) -> str:
    markdown = snapshot.source_markdown
    if len(markdown.encode("utf-8")) > MAX_PREVIEW_MARKDOWN_BYTES:
        raise PreviewValidationError("内容快照正文超过预览大小限制")
    if sum(asset.embedded for asset in snapshot.assets) > MAX_PREVIEW_IMAGES:
        raise PreviewValidationError("内容快照正文图片数量超过预览限制")
    for asset in snapshot.assets:
        markdown = markdown.replace(f"reven-asset://sha256/{asset.sha256}", asset.public_url)
    if "reven-asset://" in markdown:
        raise PreviewValidationError("内容快照包含未解析的媒体地址")
    return markdown
