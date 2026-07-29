from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from uuid import UUID

from bs4 import BeautifulSoup

from reven.jobs.errors import BlockedPublishError
from reven.publishing.assets import AssetMaterializer, MaterializedAsset, MaterializedAssets
from reven.publishing.snapshot import build_snapshot, image_urls

ASSET_PREFIX = "reven-asset://image/"


class SnapshotAssetsMissingError(BlockedPublishError):
    """冻结素材目录缺失，可尝试从 Notion 安全重建。"""


@dataclass(frozen=True)
class ImagePlaceholder:
    ordinal: int
    asset: MaterializedAsset


def validate_placeholders(html: str, assets: tuple[MaterializedAsset, ...]) -> tuple[ImagePlaceholder, ...]:
    soup = BeautifulSoup(html, "html.parser")
    expected = {index: asset for index, asset in enumerate(assets, start=1)}
    found: list[ImagePlaceholder] = []
    seen: set[int] = set()
    for image in soup.find_all("img"):
        source = image.get("src")
        if not isinstance(source, str) or not source.startswith("reven-asset://"):
            continue
        ordinal = _parse_ordinal(source)
        if ordinal in seen or ordinal not in expected:
            raise BlockedPublishError("微信正文图片占位符与冻结快照不一致")
        seen.add(ordinal)
        found.append(ImagePlaceholder(ordinal, expected[ordinal]))
    if seen != set(expected):
        raise BlockedPublishError("微信正文图片占位符与冻结快照不一致")
    return tuple(found)


def replace_placeholders(html: str, urls: dict[int, str]) -> str:
    soup = BeautifulSoup(html, "html.parser")
    seen: set[int] = set()
    for image in soup.find_all("img"):
        source = image.get("src")
        if not isinstance(source, str) or not source.startswith("reven-asset://"):
            continue
        ordinal = _parse_ordinal(source)
        if ordinal in seen or ordinal not in urls:
            raise BlockedPublishError("微信正文图片替换映射无效")
        image["src"] = urls[ordinal]
        seen.add(ordinal)
    if seen != set(urls) or "reven-asset://" in str(soup):
        raise BlockedPublishError("微信正文仍包含未替换的素材占位符")
    return str(soup)


class SnapshotAssetRecoverer:
    def __init__(
        self,
        materializer: AssetMaterializer,
        fetch_markdown: Callable[[], Awaitable[str]],
        fetch_cover_url: Callable[[], Awaitable[str | None]],
    ) -> None:
        self.materializer = materializer
        self.fetch_markdown = fetch_markdown
        self.fetch_cover_url = fetch_cover_url

    async def recover(
        self,
        job_id: UUID,
        frozen_markdown: str,
        metadata: dict[str, object],
    ) -> MaterializedAssets:
        fresh_markdown = await self.fetch_markdown()
        cover_url = await self.fetch_cover_url()
        staged = await self.materializer.materialize(job_id, list(image_urls(fresh_markdown)), cover_url)
        try:
            self._verify(staged, fresh_markdown, frozen_markdown, metadata)
            finalized = await self.materializer.finalize(staged)
            return finalized
        except Exception:
            await self.materializer.discard(staged)
            raise

    @staticmethod
    def _verify(
        assets: MaterializedAssets,
        fresh_markdown: str,
        frozen_markdown: str,
        metadata: dict[str, object],
    ) -> None:
        if assets.cover is None:
            raise BlockedPublishError("恢复的微信素材缺少封面")
        images = metadata.get("images")
        if not isinstance(images, list):
            raise BlockedPublishError("微信冻结素材清单无效")
        expected = tuple(_expected_sha(item) for item in images)
        actual = tuple(asset.sha256 for asset in assets.images)
        categories_raw = metadata.get("categories", [])
        categories = tuple(str(item) for item in categories_raw) if isinstance(categories_raw, list) else ()
        snapshot = build_snapshot(
            fresh_markdown,
            image_sha256=actual,
            cover_sha256=assets.cover.sha256,
            title=str(metadata.get("title", "")),
            summary=str(metadata.get("summary", "")),
            categories=categories,
        )
        if (
            snapshot.markdown != frozen_markdown
            or actual != expected
            or assets.cover.sha256 != metadata.get("cover_sha256")
        ):
            raise BlockedPublishError("Notion 内容或素材已变化，禁止恢复旧发布任务")


def _parse_ordinal(source: str) -> int:
    raw = source.removeprefix(ASSET_PREFIX)
    if not source.startswith(ASSET_PREFIX) or not raw.isascii() or not raw.isdigit():
        raise BlockedPublishError("微信正文包含非法素材占位符")
    ordinal = int(raw)
    if ordinal <= 0 or str(ordinal) != raw:
        raise BlockedPublishError("微信正文包含非法素材占位符")
    return ordinal


def _expected_sha(raw: object) -> str:
    if not isinstance(raw, dict):
        raise BlockedPublishError("微信冻结素材清单无效")
    sha256 = raw.get("sha256")
    if not isinstance(sha256, str) or len(sha256) != 64:
        raise BlockedPublishError("微信冻结素材清单无效")
    return sha256
