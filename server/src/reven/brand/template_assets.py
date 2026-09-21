"""品牌模板引用的素材标识提取。"""

from uuid import UUID


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
