"""品牌配置解析与渠道产物模板应用（纯函数为核心）。

预览与交付共用这些函数：同一组（正文, 品牌, 模板, 素材）输入必然得到同一产物，
从机制上保证预览与实际交付一致。
"""

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from reven.brand.repository import BrandRepository
from reven.domain import TargetChannel
from reven.publishing.validation import ValidationIssue


class TemplateAssetRef(Protocol):
    """文末图片模块对素材的最小依赖；ORM BrandAsset 与冻结记录实现均可满足。"""

    @property
    def id(self) -> UUID: ...
    @property
    def enabled(self) -> bool: ...
    @property
    def sha256(self) -> str: ...
    @property
    def public_url(self) -> str: ...
    @property
    def label(self) -> str: ...


@dataclass(frozen=True)
class BrandAssetLike:
    """非 ORM 场景（如交付时从冻结元数据重建）的素材引用实现。"""

    id: UUID
    enabled: bool
    sha256: str
    public_url: str
    label: str

LEGACY_BINDING_KEY = "legacy"

# 微信封面推荐比例（首图 900x383 ≈ 2.35:1），偏离容忍 ±10%
WECHAT_COVER_RATIO = 2.35
COVER_RATIO_TOLERANCE = 0.10

_FOOTER_SIGNALS = ("关注", "公众号", "二维码", "扫码", "微信")
_FOOTER_TAIL_CHARS = 300
_FOOTER_UNCERTAIN_MESSAGE = "正文末尾疑似已有推广内容，为避免重复未自动追加，请人工确认"


@dataclass(frozen=True)
class ResolvedBrand:
    """当前生效的品牌档案与渠道模板（均指向不可变的已发布版本行）。"""

    brand_version_id: UUID
    brand_version: int
    brand_payload: dict[str, object]
    wechat_template_version_id: UUID | None
    wechat_template_version: int | None
    wechat_template_payload: dict[str, object] | None
    blog_template_version_id: UUID | None
    blog_template_version: int | None
    blog_template_payload: dict[str, object] | None

    @property
    def binding_key(self) -> str:
        """确定性绑定键（sha256 hex，恰好 64 字符）；完整绑定细节由任务外键与元数据承载。"""
        raw = f"{self.brand_version_id}:{self.wechat_template_version_id}:{self.blog_template_version_id}"
        return hashlib.sha256(raw.encode()).hexdigest()

    @property
    def default_author(self) -> str:
        author = self.brand_payload.get("default_author")
        return author if isinstance(author, str) else ""

    def version_fingerprint(self) -> dict[str, object]:
        return {
            "brand_version": self.brand_version,
            "wechat_template_version": self.wechat_template_version,
            "blog_template_version": self.blog_template_version,
        }


async def resolve_brand_config(session: AsyncSession) -> ResolvedBrand | None:
    """读取当前已发布品牌与渠道模板；无已发布品牌时返回 None（全链路回落 legacy 行为）。"""
    repo = BrandRepository(session)
    brand = await repo.published_brand()
    if brand is None:
        return None
    wechat = await repo.published_template(str(TargetChannel.WECHAT))
    blog = await repo.published_template(str(TargetChannel.BLOG))
    return ResolvedBrand(
        brand_version_id=brand.id,
        brand_version=brand.version,
        brand_payload=brand.payload,
        wechat_template_version_id=wechat.id if wechat else None,
        wechat_template_version=wechat.version if wechat else None,
        wechat_template_payload=wechat.payload if wechat else None,
        blog_template_version_id=blog.id if blog else None,
        blog_template_version=blog.version if blog else None,
        blog_template_payload=blog.payload if blog else None,
    )


def binding_key_for(resolved: ResolvedBrand | None) -> str:
    return resolved.binding_key if resolved is not None else LEGACY_BINDING_KEY


@dataclass(frozen=True)
class TemplateApplication:
    markdown: str
    errors: tuple[ValidationIssue, ...]
    warnings: tuple[ValidationIssue, ...]


def apply_wechat_template(
    markdown: str,
    brand_payload: dict[str, object],
    template_payload: dict[str, object] | None,
    assets_by_id: Mapping[UUID, TemplateAssetRef],
    *,
    embedded_sha256: tuple[str, ...] = (),
) -> TemplateApplication:
    """在微信正文末尾套用文末模块。渠道产物不回写正文，去重保守：不确定只提醒不改动。

    embedded_sha256：正文已内嵌图片的 sha256 集合（预览与交付各自从快照视图/冻结元数据提取），
    保证两种正文表示下图片模块去重判定一致。
    """
    if template_payload is None:
        return TemplateApplication(markdown, (), ())
    modules = template_payload.get("footer_modules")
    if not isinstance(modules, list):
        return TemplateApplication(markdown, (), ())

    errors: list[ValidationIssue] = []
    warnings: list[ValidationIssue] = []
    appends: list[str] = []
    for module in modules:
        if not isinstance(module, dict) or module.get("enabled") is not True:
            continue
        module_type = module.get("type")
        if module_type == "text":
            _apply_text_module(markdown, module, appends, warnings)
        elif module_type == "image":
            _apply_image_module(markdown, module, assets_by_id, embedded_sha256, appends, errors, warnings)
    if not appends:
        return TemplateApplication(markdown, tuple(errors), tuple(warnings))
    separator = "\n\n---\n\n"
    applied = markdown.rstrip() + separator + "\n\n".join(appends) + "\n"
    return TemplateApplication(applied, tuple(errors), tuple(warnings))


def _apply_text_module(
    markdown: str,
    module: dict[str, object],
    appends: list[str],
    warnings: list[ValidationIssue],
) -> None:
    content = module.get("content")
    if not isinstance(content, str) or not content.strip():
        return
    if _normalize(content) in _normalize(markdown):
        warnings.append(ValidationIssue("footer_already_present", "正文已包含相同文末模块，已跳过追加", "footer"))
        return
    if _text_footer_like_tail(markdown):
        warnings.append(ValidationIssue("footer_conflict_uncertain", _FOOTER_UNCERTAIN_MESSAGE, "footer"))
        return
    appends.append(content.strip())


def _apply_image_module(
    markdown: str,
    module: dict[str, object],
    assets_by_id: Mapping[UUID, TemplateAssetRef],
    embedded_sha256: tuple[str, ...],
    appends: list[str],
    errors: list[ValidationIssue],
    warnings: list[ValidationIssue],
) -> None:
    raw_id = module.get("asset_id")
    asset = _asset_by_raw_id(raw_id, assets_by_id)
    if asset is None or not asset.enabled:
        errors.append(ValidationIssue("brand_asset_unreadable", "文末模块引用的素材不存在或已停用", "footer"))
        return
    if asset.sha256 in embedded_sha256 or asset.public_url in markdown:
        warnings.append(ValidationIssue("footer_already_present", "正文已包含相同文末图片，已跳过追加", "footer"))
        return
    if _text_footer_like_tail(markdown):
        warnings.append(ValidationIssue("footer_conflict_uncertain", _FOOTER_UNCERTAIN_MESSAGE, "footer"))
        return
    appends.append(f"![{asset.label}]({asset.public_url})")


def _asset_by_raw_id(raw: object, assets_by_id: Mapping[UUID, TemplateAssetRef]) -> TemplateAssetRef | None:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        return assets_by_id.get(UUID(raw))
    except ValueError:
        return None


def _normalize(text: str) -> str:
    return "".join(text.split())


def _text_footer_like_tail(markdown: str) -> bool:
    tail = markdown[-_FOOTER_TAIL_CHARS:]
    return any(signal in tail for signal in _FOOTER_SIGNALS)


def wechat_theme_params(
    brand_payload: dict[str, object], template_payload: dict[str, object] | None
) -> dict[str, object]:
    """组装渲染器主题参数：模板主题优先，回落品牌档案配色与字体。"""
    colors = brand_payload.get("colors")
    fonts = brand_payload.get("fonts")
    theme = template_payload.get("theme") if template_payload else None
    colors = colors if isinstance(colors, dict) else {}
    fonts = fonts if isinstance(fonts, dict) else {}
    theme = theme if isinstance(theme, dict) else {}
    return {
        "primaryColor": _str_or(theme.get("primary_color"), _str_or(colors.get("primary"), "")),
        "fontFamily": _str_or(theme.get("font_family"), _str_or(fonts.get("body"), "")),
        "fontSize": theme.get("font_size") if isinstance(theme.get("font_size"), int) else 16,
    }


def _str_or(value: object, fallback: str) -> str:
    return value if isinstance(value, str) and value else fallback



def template_asset_ids(payload: dict[str, object]) -> list[UUID]:
    """提取模板 payload 中引用的素材 id（微信文末模块 + 博客封面/OG 字段）。"""
    ids: list[UUID] = []
    modules = payload.get("footer_modules")
    if isinstance(modules, list):
        for module in modules:
            if isinstance(module, dict):
                _collect_id(ids, module.get("asset_id"))
    for key in ("cover_fallback_asset_id", "og_image_asset_id"):
        _collect_id(ids, payload.get(key))
    return ids


def _collect_id(ids: list[UUID], raw: object) -> None:
    if not isinstance(raw, str) or not raw:
        return
    try:
        parsed = UUID(raw)
    except ValueError:
        return
    if parsed not in ids:
        ids.append(parsed)


def cover_ratio_warning(width: int | None, height: int | None, *, channel: str) -> ValidationIssue | None:
    """封面比例偏离渠道推荐值时给出提醒（不阻塞）。"""
    if channel != "微信公众号" or width is None or height is None or height == 0:
        return None
    ratio = width / height
    if abs(ratio - WECHAT_COVER_RATIO) / WECHAT_COVER_RATIO > COVER_RATIO_TOLERANCE:
        return ValidationIssue(
            "cover_aspect_ratio",
            f"封面比例 {ratio:.2f}:1 偏离微信首图推荐 {WECHAT_COVER_RATIO}:1，可按需更换",
            "cover",
        )
    return None
