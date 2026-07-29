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
    spans = _image_destination_spans(markdown)
    if len(spans) != len(urls):
        raise ValueError("无法在 Markdown 中精确定位已解析的图片地址")
    result = markdown
    for index, (start, end) in reversed(list(enumerate(spans, start=1))):
        replacement = f"reven-asset://image/{index}"
        result = result[:start] + replacement + result[end:]
    return result


def _image_destination_spans(markdown: str) -> tuple[tuple[int, int], ...]:
    excluded = _block_exclusions(markdown)
    spans: list[tuple[int, int]] = []
    index = 0
    while index < len(markdown):
        block_end = _containing_end(index, excluded)
        if block_end is not None:
            index = block_end
        elif markdown[index] == "`":
            index = _skip_code_span(markdown, index)
        elif markdown[index] == "<":
            index = _skip_html_tag(markdown, index)
        elif markdown.startswith("![", index) and not _is_escaped(markdown, index):
            span = _inline_image_destination(markdown, index)
            if span is None:
                index += 2
            else:
                spans.append(span)
                index = span[1]
        else:
            index += 1
    return tuple(spans)


def _block_exclusions(markdown: str) -> tuple[tuple[int, int], ...]:
    line_starts = [0]
    line_starts.extend(index + 1 for index, character in enumerate(markdown) if character == "\n")
    line_starts.append(len(markdown))
    ranges: list[tuple[int, int]] = []
    for token in MarkdownIt().parse(markdown):
        if token.type not in {"fence", "code_block", "html_block"} or token.map is None:
            continue
        start_line, end_line = token.map
        ranges.append((line_starts[start_line], line_starts[min(end_line, len(line_starts) - 1)]))
    return tuple(ranges)


def _containing_end(index: int, ranges: tuple[tuple[int, int], ...]) -> int | None:
    for start, end in ranges:
        if start <= index < end:
            return end
    return None


def _skip_code_span(markdown: str, start: int) -> int:
    run = 1
    while start + run < len(markdown) and markdown[start + run] == "`":
        run += 1
    marker = "`" * run
    end = markdown.find(marker, start + run)
    return start + run if end < 0 else end + run


def _skip_html_tag(markdown: str, start: int) -> int:
    quote: str | None = None
    index = start + 1
    while index < len(markdown):
        character = markdown[index]
        if quote is not None:
            if character == quote and not _is_escaped(markdown, index):
                quote = None
        elif character in {'"', "'"}:
            quote = character
        elif character == ">":
            return index + 1
        index += 1
    return start + 1


def _inline_image_destination(markdown: str, start: int) -> tuple[int, int] | None:
    label_end = _find_unescaped(markdown, "]", start + 2)
    if label_end < 0 or label_end + 1 >= len(markdown) or markdown[label_end + 1] != "(":
        return None
    destination = label_end + 2
    while destination < len(markdown) and markdown[destination] in " \t\n":
        destination += 1
    if destination >= len(markdown):
        return None
    if markdown[destination] == "<":
        end = _find_unescaped(markdown, ">", destination + 1)
        return (destination + 1, end) if end >= 0 else None
    return _bare_destination(markdown, destination)


def _bare_destination(markdown: str, start: int) -> tuple[int, int] | None:
    depth = 0
    index = start
    while index < len(markdown):
        character = markdown[index]
        if _is_escaped(markdown, index):
            index += 1
        elif character == "(":
            depth += 1
        elif character == ")" and depth == 0:
            return (start, index)
        elif character == ")":
            depth -= 1
        elif character.isspace() and depth == 0:
            return (start, index)
        index += 1
    return None


def _find_unescaped(markdown: str, target: str, start: int) -> int:
    index = start
    while index < len(markdown):
        if markdown[index] == target and not _is_escaped(markdown, index):
            return index
        index += 1
    return -1


def _is_escaped(markdown: str, index: int) -> bool:
    slashes = 0
    while index - slashes - 1 >= 0 and markdown[index - slashes - 1] == "\\":
        slashes += 1
    return slashes % 2 == 1
