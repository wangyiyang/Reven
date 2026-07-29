import hashlib
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

from bs4 import BeautifulSoup

from reven.integrations.wechat.client import WECHAT_IMAGE_HOSTS
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
        if not isinstance(source, str) or not source.startswith(ASSET_PREFIX):
            raise BlockedPublishError("微信正文图片必须来自冻结素材占位符")
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
    rendered = str(soup)
    _validate_wechat_images(rendered)
    return rendered


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
            if staged.final_dir is not None and staged.final_dir.exists():
                repaired = _repair_existing_snapshot(staged, metadata)
                await self.materializer.discard(staged)
                return repaired
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


def _validate_wechat_images(html: str) -> None:
    from urllib.parse import urlsplit

    soup = BeautifulSoup(html, "html.parser")
    for image in soup.find_all("img"):
        source = image.get("src")
        if not isinstance(source, str):
            raise BlockedPublishError("微信正文图片缺少托管地址")
        parsed = urlsplit(source)
        if (
            parsed.scheme != "https"
            or parsed.hostname not in WECHAT_IMAGE_HOSTS
            or parsed.username is not None
            or parsed.password is not None
            or not parsed.path.startswith("/")
        ):
            raise BlockedPublishError("微信正文包含非微信托管图片")


def _repair_existing_snapshot(
    staged: MaterializedAssets,
    metadata: dict[str, object],
) -> MaterializedAssets:
    if staged.final_dir is None or staged.cover is None:
        raise BlockedPublishError("微信素材恢复目录无效")
    images_raw = metadata.get("images")
    cover_raw = metadata.get("cover")
    if not isinstance(images_raw, list) or not isinstance(cover_raw, dict):
        raise BlockedPublishError("微信冻结素材清单无效")
    expected = [*_repair_pairs(staged.images, images_raw), (staged.cover, cover_raw)]
    repaired: list[MaterializedAsset] = []
    for source, raw in expected:
        destination = _safe_destination(staged.final_dir, raw)
        _replace_if_needed(source, destination)
        repaired.append(
            MaterializedAsset(
                source.original_url,
                destination,
                source.sha256,
                source.mime_type,
                source.size,
            )
        )
    return MaterializedAssets(tuple(repaired[:-1]), repaired[-1], final_dir=staged.final_dir)


def _repair_pairs(
    staged: tuple[MaterializedAsset, ...],
    metadata: list[object],
) -> list[tuple[MaterializedAsset, dict[object, object]]]:
    if len(staged) != len(metadata):
        raise BlockedPublishError("微信冻结素材清单无效")
    pairs: list[tuple[MaterializedAsset, dict[object, object]]] = []
    for source, raw in zip(staged, metadata, strict=True):
        if not isinstance(raw, dict):
            raise BlockedPublishError("微信冻结素材清单无效")
        pairs.append((source, raw))
    return pairs


def _safe_destination(directory: Path, raw: dict[object, object]) -> Path:
    raw_path = raw.get("path")
    if not isinstance(raw_path, str):
        raise BlockedPublishError("微信冻结素材路径无效")
    name = Path(raw_path).name
    if not name:
        raise BlockedPublishError("微信冻结素材路径无效")
    if directory.is_symlink():
        raise BlockedPublishError("微信素材目录不能是符号链接")
    destination = directory / name
    if destination.is_symlink():
        raise BlockedPublishError("微信素材文件不能是符号链接")
    return destination


def _replace_if_needed(source: MaterializedAsset, destination: Path) -> None:
    if destination.is_file() and _sha256(destination) == source.sha256:
        return
    temporary = destination.parent / f".{destination.name}.recover-{uuid4().hex}"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(temporary, flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(source.path.read_bytes())
            output.flush()
            os.fsync(output.fileno())
        if _sha256(temporary) != source.sha256:
            raise BlockedPublishError("恢复素材哈希校验失败")
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
