"""准备阶段的品牌解析：封面优先级、文末素材物化决策、校验上下文。

封面优先级：稿件手工选择的品牌素材 > Notion 页面封面 > 博客模板回落封面素材。
文末素材：准备阶段按模板应用结果决定需要冻结哪些素材，与正文素材同批物化、同 staging 提交。
"""

from collections.abc import Mapping
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from reven.articles.models import Article
from reven.brand.application import (
    ResolvedBrand,
    TemplateApplication,
    TemplateAssetRef,
    apply_wechat_template,
    resolve_brand_config,
    template_asset_ids,
)
from reven.brand.models import BrandAsset
from reven.brand.repository import BrandRepository
from reven.domain import TargetChannel
from reven.integrations.notion.models import MappedNotionPage
from reven.publishing.validation import ValidationError


@dataclass(frozen=True)
class BrandPreparation:
    """一次准备解析出的品牌上下文；全链路只读。"""

    resolved: ResolvedBrand | None
    cover_url: str | None  # None 表示沿用 Notion 封面
    cover_asset: BrandAsset | None  # 品牌素材封面（用于比例提醒）
    application: TemplateApplication | None  # 微信模板应用结果（交付/预览同函数）
    footer_assets: tuple[TemplateAssetRef, ...]  # 需随正文冻结的文末素材
    blog_author: str  # 博客署名（模板 > 品牌默认；空串表示回落 Notion 元数据）
    blog_og_image_url: str | None  # 博客 OG 图覆盖（模板指定素材的绝对地址）
    warnings: tuple[ValidationError, ...]
    errors: tuple[ValidationError, ...]

    @property
    def footer_urls(self) -> list[str]:
        return [asset.public_url for asset in self.footer_assets]


async def prepare_brand(
    session: AsyncSession,
    article_id: UUID,
    mapped: MappedNotionPage,
    markdown: str,
    channels: tuple[TargetChannel, ...],
) -> BrandPreparation | None:
    """解析当前品牌上下文；无品牌绑定且未选择封面素材时返回 None（完整 legacy 路径）。"""
    resolved = await resolve_brand_config(session)
    selected_id = await session.scalar(
        select(Article.selected_cover_asset_id).where(Article.id == article_id)
    )
    if resolved is None and selected_id is None:
        return None

    repository = BrandRepository(session)
    referenced: list[UUID] = []
    if resolved is not None:
        for payload in (resolved.wechat_template_payload, resolved.blog_template_payload):
            if payload is not None:
                referenced.extend(template_asset_ids(payload))
    if selected_id is not None and selected_id not in referenced:
        referenced.append(selected_id)
    assets: Mapping[UUID, BrandAsset] = (
        {asset.id: asset for asset in await repository.assets_by_ids(referenced)} if referenced else {}
    )

    warnings: list[ValidationError] = []
    errors: list[ValidationError] = []
    cover_url, cover_asset = _resolve_cover(mapped, resolved, selected_id, assets, warnings)
    if resolved is not None:
        _check_blog_asset_refs(resolved, assets, errors)
    application = _apply_wechat(resolved, markdown, channels, assets)
    if application is not None:
        warnings.extend(application.warnings)
        errors.extend(application.errors)
    footer_assets = _appended_footer_assets(application, markdown, resolved, assets) if application else ()
    blog_author, blog_og = _blog_static_fields(resolved, assets)
    return BrandPreparation(
        resolved=resolved,
        cover_url=cover_url,
        cover_asset=cover_asset,
        application=application,
        footer_assets=footer_assets,
        blog_author=blog_author,
        blog_og_image_url=blog_og,
        warnings=tuple(warnings),
        errors=tuple(errors),
    )


def _blog_static_fields(
    resolved: ResolvedBrand | None, assets: Mapping[UUID, BrandAsset]
) -> tuple[str, str | None]:
    """博客署名与 OG 覆盖图：路径相关的封面字段由转换器在交付时推导。"""
    if resolved is None:
        return "", None
    payload = resolved.blog_template_payload or {}
    author = payload.get("author")
    if not isinstance(author, str) or not author:
        default = resolved.brand_payload.get("default_author")
        author = default if isinstance(default, str) else ""
    og_asset = _asset_ref(payload.get("og_image_asset_id"), assets)
    return author, og_asset.public_url if og_asset is not None else None


def _resolve_cover(
    mapped: MappedNotionPage,
    resolved: ResolvedBrand | None,
    selected_id: UUID | None,
    assets: Mapping[UUID, BrandAsset],
    warnings: list[ValidationError],
) -> tuple[str | None, BrandAsset | None]:
    """返回 (cover_url, cover_asset)；cover_url 为 None 表示沿用 Notion 封面。"""
    if selected_id is not None:
        selected = assets.get(selected_id)
        if selected is not None and selected.enabled:
            return selected.public_url, selected
        warnings.append(
            ValidationError("selected_cover_unavailable", "已选封面素材不存在或已停用，已回落默认封面", "cover")
        )
    if mapped.cover is not None:
        return None, None
    if resolved is None or resolved.blog_template_payload is None:
        return None, None
    fallback = _asset_ref(resolved.blog_template_payload.get("cover_fallback_asset_id"), assets)
    if fallback is not None:
        return fallback.public_url, fallback
    return None, None


def _asset_ref(raw: object, assets: Mapping[UUID, BrandAsset]) -> BrandAsset | None:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        asset_id = UUID(raw)
    except ValueError:
        return None
    asset = assets.get(asset_id)
    if asset is None or not asset.enabled:
        return None
    return asset


def _check_blog_asset_refs(
    resolved: ResolvedBrand,
    assets: Mapping[UUID, BrandAsset],
    errors: list[ValidationError],
) -> None:
    """博客模板引用的封面/OG 素材必须存在且启用（失效即阻塞，与素材不可读取同级）。"""
    payload = resolved.blog_template_payload
    if payload is None:
        return
    for key, field in (("cover_fallback_asset_id", "cover_fallback"), ("og_image_asset_id", "og_image")):
        raw = payload.get(key)
        if not isinstance(raw, str) or not raw:
            continue
        if _asset_ref(raw, assets) is None:
            errors.append(
                ValidationError("brand_asset_unreadable", "博客模板引用的素材不存在或已停用", field)
            )


def _apply_wechat(
    resolved: ResolvedBrand | None,
    markdown: str,
    channels: tuple[TargetChannel, ...],
    assets: Mapping[UUID, BrandAsset],
) -> TemplateApplication | None:
    if resolved is None or TargetChannel.WECHAT not in channels or resolved.wechat_template_payload is None:
        return None
    return apply_wechat_template(markdown, resolved.brand_payload, resolved.wechat_template_payload, assets)


def _appended_footer_assets(
    application: TemplateApplication | None,
    markdown: str,
    resolved: ResolvedBrand | None,
    assets: Mapping[UUID, BrandAsset],
) -> tuple[TemplateAssetRef, ...]:
    """确定实际被追加的文末图片素材（与交付时 apply 的去重判定同源）。"""
    if application is None or resolved is None or resolved.wechat_template_payload is None:
        return ()
    modules = resolved.wechat_template_payload.get("footer_modules")
    if not isinstance(modules, list):
        return ()
    appended: list[TemplateAssetRef] = []
    for module in modules:
        if not isinstance(module, dict) or module.get("enabled") is not True or module.get("type") != "image":
            continue
        asset = _asset_ref(module.get("asset_id"), assets)
        if asset is None:
            continue
        if asset.public_url in application.markdown and asset.public_url not in markdown:
            appended.append(asset)
    return tuple(appended)
