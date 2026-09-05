"""微信交付链路的品牌模板套用：冻结配置 + 冻结素材 → 渲染输入。

安全不变量：渲染正文中的一切图片必须是本地冻结文件的 reven-asset 占位符。
文末模块图片在准备阶段与正文素材同目录冻结（snapshot_metadata["footer_assets"]），
交付时套用模板后将其公网 URL 替换为续序占位符，校验与正文素材同一套哈希机制。
"""

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from reven.brand.application import BrandAssetLike, TemplateApplication, TemplateAssetRef, apply_wechat_template
from reven.jobs.errors import BlockedPublishError
from reven.publishing.assets import MaterializedAsset
from reven.publishing.wechat.renderer import WechatTheme, theme_from_params


@dataclass(frozen=True)
class FooterAssetEntry:
    """准备阶段冻结的文末模块素材记录。"""

    asset_id: UUID
    label: str
    sha256: str
    public_url: str
    path: Path
    mime_type: str
    size: int

    def as_template_asset(self) -> BrandAssetLike:
        return BrandAssetLike(
            id=self.asset_id, enabled=True, sha256=self.sha256, public_url=self.public_url, label=self.label
        )


@dataclass(frozen=True)
class BrandDeliveryInput:
    """模板套用后的交付输入。"""

    markdown: str
    footer_images: tuple[MaterializedAsset, ...]
    theme: WechatTheme | None


def parse_footer_entries(metadata: dict[str, Any]) -> tuple[FooterAssetEntry, ...]:
    raw = metadata.get("footer_assets")
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise BlockedPublishError("冻结文末素材清单无效")
    return tuple(_parse_entry(item) for item in raw)


def apply_brand_for_delivery(
    markdown: str,
    brand: dict[str, Any],
    footer_entries: tuple[FooterAssetEntry, ...],
    embedded_sha256: tuple[str, ...],
    *,
    footer_start_ordinal: int,
) -> BrandDeliveryInput:
    """套用冻结品牌配置；素材不可读取 / 模板引用失效时阻塞交付。"""
    brand_payload = _payload(brand.get("brand_payload"), "品牌配置")
    template_payload = brand.get("template_payload")
    if template_payload is not None:
        template_payload = _payload(template_payload, "微信模板配置")
    assets_by_id: dict[UUID, TemplateAssetRef] = {entry.asset_id: entry.as_template_asset() for entry in footer_entries}
    application = apply_wechat_template(
        markdown, brand_payload, template_payload, assets_by_id, embedded_sha256=embedded_sha256
    )
    if application.errors:
        reason = "；".join(issue.message for issue in application.errors)
        raise BlockedPublishError(f"品牌模板应用失败：{reason}")
    applied, footer_images = _placeholderize(application, footer_entries, footer_start_ordinal)
    return BrandDeliveryInput(applied, footer_images, theme_from_params(_theme(brand)))


def _placeholderize(
    application: TemplateApplication, entries: tuple[FooterAssetEntry, ...], start_ordinal: int
) -> tuple[str, tuple[MaterializedAsset, ...]]:
    """把已追加到正文的文末素材公网 URL 替换为续序占位符，并校验冻结文件。"""
    markdown = application.markdown
    images: list[MaterializedAsset] = []
    ordinal = start_ordinal
    for entry in entries:
        if entry.public_url not in markdown:
            continue
        _verify_entry_file(entry)
        markdown = markdown.replace(entry.public_url, f"reven-asset://image/{ordinal}")
        ordinal += 1
        images.append(
            MaterializedAsset(
                original_url=entry.public_url,
                path=entry.path,
                sha256=entry.sha256,
                mime_type=entry.mime_type,
                size=entry.size,
            )
        )
    return markdown, tuple(images)


def _verify_entry_file(entry: FooterAssetEntry) -> None:
    if entry.path.is_symlink() or not entry.path.is_file():
        raise BlockedPublishError(f"文末素材文件缺失：{entry.label}")
    digest = hashlib.sha256(entry.path.read_bytes()).hexdigest()
    if digest != entry.sha256:
        raise BlockedPublishError(f"文末素材校验失败：{entry.label}")


def _parse_entry(item: object) -> FooterAssetEntry:
    if not isinstance(item, dict):
        raise BlockedPublishError("冻结文末素材清单无效")
    try:
        return FooterAssetEntry(
            asset_id=UUID(str(item["asset_id"])),
            label=str(item.get("label", "")),
            sha256=str(item["sha256"]),
            public_url=str(item["public_url"]),
            path=Path(str(item["path"])),
            mime_type=str(item["mime_type"]),
            size=int(item["size"]),
        )
    except (KeyError, ValueError, TypeError) as exc:
        raise BlockedPublishError("冻结文末素材清单无效") from exc


def _payload(raw: object, field: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise BlockedPublishError(f"{field}无效")
    return {str(key): value for key, value in raw.items()}


def _theme(brand: dict[str, Any]) -> dict[str, object]:
    raw = brand.get("theme")
    return raw if isinstance(raw, dict) else {}
