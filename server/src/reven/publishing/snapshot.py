"""Stable publication snapshots built from Markdown tokens and asset digests."""

import hashlib
import json
from bisect import bisect_right
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

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
    canonical, hash_canonical = _canonical_markdown(markdown, tokens, env)
    normalized_categories = tuple(sorted(categories))
    payload = {
        "title": title.strip(),
        "summary": summary.strip(),
        "categories": list(normalized_categories),
        "markdown": hash_canonical.replace("\r\n", "\n").strip(),
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
        destination = _inline_destination_span(state, start)
        token.meta["is_reference"] = destination is None
        if destination is not None:
            token.meta["destination_start"], token.meta["destination_end"] = destination
    return matched


def _inline_destination_span(state: StateInline, image_start: int) -> tuple[int, int] | None:
    label_end = state.md.helpers.parseLinkLabel(state, image_start + 1, False)
    position = label_end + 1
    if label_end < 0 or position >= len(state.src) or state.src[position] != "(":
        return None
    position += 1
    while position < len(state.src) and (state.src[position].isspace() or state.src[position] == "\n"):
        position += 1
    result = state.md.helpers.parseLinkDestination(state.src, position, len(state.src))
    if not result.ok:
        return None
    if state.src[position] == "<":
        return position + 1, result.pos - 1
    return position, result.pos


def _image_urls_from_tokens(tokens: list[Token]) -> tuple[str, ...]:
    return tuple(
        src
        for token in tokens
        for child in (token.children or ())
        if child.type == "image" and isinstance(src := child.attrGet("src"), str)
    )


def _canonical_markdown(markdown: str, tokens: list[Token], env: dict[str, Any]) -> tuple[str, str]:
    replacements: list[tuple[int, int, str]] = []
    line_starts = _line_starts(markdown)
    used_labels: set[str] = set()
    ordinal = 0
    for token in tokens:
        if token.type != "inline" or token.map is None or token.children is None:
            continue
        source_map = _inline_source_map(markdown, token, line_starts)
        for child in token.children:
            if child.type != "image":
                continue
            ordinal += 1
            start = child.meta.get("source_start")
            end = child.meta.get("source_end")
            if not isinstance(start, int) or not isinstance(end, int):
                raise ValueError("Markdown 图片缺少解析器源位置")
            label = child.meta.get("label")
            if child.meta.get("is_reference") is True:
                replacement = _reference_image(child, ordinal)
                replacements.append((source_map.absolute(start), source_map.absolute(end), replacement))
            else:
                destination_start = child.meta.get("destination_start")
                destination_end = child.meta.get("destination_end")
                if not isinstance(destination_start, int) or not isinstance(destination_end, int):
                    raise ValueError("Markdown 图片缺少 destination 源位置")
                replacements.append(
                    (
                        source_map.absolute(destination_start),
                        source_map.absolute(destination_end),
                        f"reven-asset://image/{ordinal}",
                    )
                )
            if child.meta.get("is_reference") is True and isinstance(label, str):
                used_labels.add(label)
    output = _apply_replacements(markdown, replacements)
    hash_output = _normalize_reference_definitions(output, env, used_labels, _line_starts(output))
    return output, hash_output


def _line_starts(markdown: str) -> list[int]:
    starts = [0]
    starts.extend(index + 1 for index, character in enumerate(markdown) if character == "\n")
    starts.append(len(markdown))
    return starts


@dataclass(frozen=True)
class _InlineSourceMap:
    local_starts: tuple[int, ...]
    absolute_starts: tuple[int, ...]
    content_length: int

    def absolute(self, local_offset: int) -> int:
        if not 0 <= local_offset <= self.content_length:
            raise ValueError("Markdown 图片 local offset 超出正文范围")
        line = max(0, bisect_right(self.local_starts, local_offset) - 1)
        return self.absolute_starts[line] + local_offset - self.local_starts[line]


def _inline_source_map(markdown: str, token: Token, line_starts: list[int]) -> _InlineSourceMap:
    assert token.map is not None
    start_line, end_line = token.map
    content_lines = token.content.splitlines(keepends=True) or [""]
    local_starts: list[int] = []
    absolute_starts: list[int] = []
    local_offset = 0
    source_line = start_line
    for content_line in content_lines:
        body = content_line.removesuffix("\n")
        match = _find_content_line(markdown, body, source_line, end_line, line_starts)
        if match is None:
            raise ValueError("无法将解析器识别的 Markdown 图片安全映射回源文")
        matched_line, absolute = match
        local_starts.append(local_offset)
        absolute_starts.append(absolute)
        local_offset += len(content_line)
        source_line = matched_line + 1
    return _InlineSourceMap(tuple(local_starts), tuple(absolute_starts), len(token.content))


def _find_content_line(
    markdown: str,
    content: str,
    start_line: int,
    end_line: int,
    line_starts: list[int],
) -> tuple[int, int] | None:
    for line in range(start_line, end_line):
        raw_start = line_starts[line]
        raw_end = line_starts[min(line + 1, len(line_starts) - 1)]
        column = markdown.find(content, raw_start, raw_end)
        if column >= 0:
            return line, column
    return None


def _normalize_reference_definitions(
    markdown: str,
    env: dict[str, Any],
    used_labels: set[str],
    line_starts: list[int],
) -> str:
    references = env.get("references")
    if not isinstance(references, dict):
        return markdown
    replacements: list[tuple[int, int, str]] = []
    for label in sorted(used_labels):
        reference = references.get(label)
        if not isinstance(reference, dict) or not isinstance(reference.get("map"), list):
            raise ValueError("Markdown 图片引用缺少定义源位置")
        start_line, end_line = reference["map"]
        start = line_starts[start_line]
        end = line_starts[min(end_line, len(line_starts) - 1)]
        href = reference.get("href")
        title = reference.get("title")
        if not isinstance(href, str) or not isinstance(title, str):
            raise ValueError("Markdown 图片引用缺少地址")
        suffix = "\n" if markdown[start:end].endswith("\n") else ""
        stable = _stable_reference_href(href)
        title_part = f' "{_escape_title(title)}"' if title else ""
        replacements.append((start, end, f"[{label}]: <{stable}>{title_part}{suffix}"))
    return _apply_replacements(markdown, replacements)


def _stable_reference_href(href: str) -> str:
    parsed = urlsplit(href)
    query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not _is_signature_query(key, parsed.hostname)
    ]
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment))


def _is_signature_query(key: str, hostname: str | None) -> bool:
    normalized = key.casefold()
    if normalized.startswith(("x-amz-", "x-goog-")):
        return True
    signed_host = hostname is not None and hostname.casefold().endswith(
        ("notion.so", "amazonaws.com", "cloudfront.net")
    )
    return signed_host and normalized in {
        "signature",
        "policy",
        "key-pair-id",
    }


def _reference_image(token: Token, ordinal: int) -> str:
    title = token.attrGet("title")
    title_part = f' "{_escape_title(title)}"' if isinstance(title, str) and title else ""
    return f"![{_escape_alt(token.content)}](reven-asset://image/{ordinal}{title_part})"


def _escape_alt(alt: str) -> str:
    return alt.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")


def _escape_title(title: str) -> str:
    return title.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


def _apply_replacements(markdown: str, replacements: list[tuple[int, int, str]]) -> str:
    result = markdown
    last_start = len(markdown) + 1
    for start, end, replacement in sorted(replacements, reverse=True):
        if end > last_start:
            raise ValueError("Markdown 图片源位置发生重叠")
        result = result[:start] + replacement + result[end:]
        last_start = start
    return result
