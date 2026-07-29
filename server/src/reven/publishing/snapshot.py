"""Stable publication snapshots built from Markdown tokens and asset digests."""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from markdown_it import MarkdownIt
from markdown_it.rules_inline.image import image as markdown_image_rule
from markdown_it.rules_inline.state_inline import StateInline
from markdown_it.token import Token


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
    _, tokens, _ = _parse_with_image_positions(markdown)
    urls: list[str] = []
    for token in tokens:
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
    _, tokens, env = _parse_with_image_positions(markdown)
    urls = _image_urls_from_tokens(tokens)
    if len(urls) != len(image_sha256):
        raise ValueError("正文图片数量与素材摘要数量不一致")
    canonical = _canonical_markdown(markdown, tokens, env)
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


def _parse_with_image_positions(markdown: str) -> tuple[MarkdownIt, list[Token], dict[str, Any]]:
    parser = MarkdownIt("commonmark", {"store_labels": True})
    parser.inline.ruler.at("image", _recording_image_rule)
    env: dict[str, Any] = {}
    return parser, parser.parse(markdown, env), env


def _recording_image_rule(state: StateInline, silent: bool) -> bool:
    start = state.pos
    matched = markdown_image_rule(state, silent)
    if matched and not silent:
        token = state.tokens[-1]
        token.meta["source_start"] = start
        token.meta["source_end"] = state.pos
    return matched


def _image_urls_from_tokens(tokens: list[Token]) -> tuple[str, ...]:
    return tuple(
        src
        for token in tokens
        for child in (token.children or ())
        if child.type == "image" and isinstance(src := child.attrGet("src"), str)
    )


def _canonical_markdown(markdown: str, tokens: list[Token], env: dict[str, Any]) -> str:
    replacements: list[tuple[int, int, str]] = []
    line_starts = _line_starts(markdown)
    used_labels: set[str] = set()
    ordinal = 0
    for token in tokens:
        if token.type != "inline" or token.map is None or token.children is None:
            continue
        base = _inline_source_offset(markdown, token, line_starts)
        for child in token.children:
            if child.type != "image":
                continue
            ordinal += 1
            start = child.meta.get("source_start")
            end = child.meta.get("source_end")
            if not isinstance(start, int) or not isinstance(end, int):
                raise ValueError("Markdown 图片缺少解析器源位置")
            replacement = f"![{_escape_alt(child.content)}](reven-asset://image/{ordinal})"
            replacements.append((base + start, base + end, replacement))
            label = child.meta.get("label")
            if isinstance(label, str):
                used_labels.add(label)
    replacements.extend(_reference_replacements(markdown, env, used_labels, line_starts))
    return _apply_replacements(markdown, replacements)


def _line_starts(markdown: str) -> list[int]:
    starts = [0]
    starts.extend(index + 1 for index, character in enumerate(markdown) if character == "\n")
    starts.append(len(markdown))
    return starts


def _inline_source_offset(markdown: str, token: Token, line_starts: list[int]) -> int:
    assert token.map is not None
    start_line, end_line = token.map
    block_start = line_starts[start_line]
    block_end = line_starts[min(end_line, len(line_starts) - 1)]
    position = markdown.find(token.content, block_start, block_end)
    if position < 0:
        raise ValueError("无法将解析器识别的 Markdown 图片安全映射回源文")
    return position


def _reference_replacements(
    markdown: str,
    env: dict[str, Any],
    used_labels: set[str],
    line_starts: list[int],
) -> list[tuple[int, int, str]]:
    references = env.get("references")
    if not isinstance(references, dict):
        return []
    replacements: list[tuple[int, int, str]] = []
    for label in sorted(used_labels):
        reference = references.get(label)
        if not isinstance(reference, dict) or not isinstance(reference.get("map"), list):
            raise ValueError("Markdown 图片引用缺少定义源位置")
        start_line, end_line = reference["map"]
        start = line_starts[start_line]
        end = line_starts[min(end_line, len(line_starts) - 1)]
        href = reference.get("href")
        if not isinstance(href, str):
            raise ValueError("Markdown 图片引用缺少地址")
        suffix = "\n" if markdown[start:end].endswith("\n") else ""
        replacements.append((start, end, f"[{label}]: <{_stable_reference_href(href)}>{suffix}"))
    return replacements


def _stable_reference_href(href: str) -> str:
    parsed = urlsplit(href)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", parsed.fragment))


def _escape_alt(alt: str) -> str:
    return alt.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")


def _apply_replacements(markdown: str, replacements: list[tuple[int, int, str]]) -> str:
    result = markdown
    last_start = len(markdown) + 1
    for start, end, replacement in sorted(replacements, reverse=True):
        if end > last_start:
            raise ValueError("Markdown 图片源位置发生重叠")
        result = result[:start] + replacement + result[end:]
        last_start = start
    return result
