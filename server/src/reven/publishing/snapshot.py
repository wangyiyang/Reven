"""Stable publication snapshots built from Markdown tokens and asset digests."""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from markdown_it import MarkdownIt


@dataclass(frozen=True)
class SnapshotAsset:
    ordinal: int
    original_url: str
    path: Path | None
    sha256: str


@dataclass(frozen=True)
class ContentSnapshot:
    markdown: str
    content_hash: str
    title: str
    summary: str
    categories: tuple[str, ...]
    images: tuple[SnapshotAsset, ...]
    cover_sha256: str

    def metadata(self) -> dict[str, object]:
        return {
            "title": self.title,
            "summary": self.summary,
            "categories": list(self.categories),
            "images": [
                {
                    "ordinal": image.ordinal,
                    "original_url": image.original_url,
                    "path": str(image.path) if image.path else None,
                    "sha256": image.sha256,
                }
                for image in self.images
            ],
            "cover_sha256": self.cover_sha256,
        }


def image_urls(markdown: str) -> tuple[str, ...]:
    urls: list[str] = []
    for token in MarkdownIt().parse(markdown):
        if token.type != "inline" or token.children is None:
            continue
        urls.extend(
            src for child in token.children if child.type == "image" and isinstance(src := child.attrGet("src"), str)
        )
    return tuple(urls)


def build_snapshot(
    markdown: str,
    *,
    image_sha256: tuple[str, ...],
    cover_sha256: str,
    title: str = "",
    summary: str = "",
    categories: tuple[str, ...] = (),
    image_paths: tuple[Path, ...] = (),
) -> ContentSnapshot:
    urls = image_urls(markdown)
    if len(urls) != len(image_sha256):
        raise ValueError("正文图片数量与素材摘要数量不一致")
    canonical = _replace_image_urls(markdown, urls)
    normalized_categories = tuple(sorted(categories))
    payload = {
        "title": title.strip(),
        "summary": summary.strip(),
        "categories": list(normalized_categories),
        "markdown": canonical.replace("\r\n", "\n").strip(),
        "image_sha256": list(image_sha256),
        "cover_sha256": cover_sha256,
    }
    digest = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    images = tuple(
        SnapshotAsset(index, url, image_paths[index - 1] if image_paths else None, image_sha256[index - 1])
        for index, url in enumerate(urls, start=1)
    )
    return ContentSnapshot(
        markdown=canonical,
        content_hash=digest,
        title=title.strip(),
        summary=summary.strip(),
        categories=normalized_categories,
        images=images,
        cover_sha256=cover_sha256,
    )


def _replace_image_urls(markdown: str, urls: tuple[str, ...]) -> str:
    result = markdown
    cursor = 0
    for index, url in enumerate(urls, start=1):
        position = result.find(url, cursor)
        if position < 0:
            raise ValueError("无法在 Markdown 中定位已解析的图片地址")
        replacement = f"reven-asset://image/{index}"
        result = result[:position] + replacement + result[position + len(url) :]
        cursor = position + len(replacement)
    return result
