"""Discover and safely rewrite downloadable Markdown media destinations."""

from bisect import bisect_right
from dataclasses import dataclass
from pathlib import PurePosixPath
from urllib.parse import unquote, urlsplit

from markdown_it import MarkdownIt
from markdown_it.rules_inline.image import image as markdown_image_rule
from markdown_it.rules_inline.link import link as markdown_link_rule
from markdown_it.rules_inline.state_inline import StateInline
from markdown_it.token import Token

_IMAGE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".gif", ".webp"})
_AUDIO_EXTENSIONS = frozenset({".mp3", ".m4a", ".aac", ".wav", ".ogg", ".flac"})
_VIDEO_EXTENSIONS = frozenset({".mp4", ".m4v", ".mov", ".webm"})


@dataclass(frozen=True)
class MarkdownMedia:
    ordinal: int
    kind: str
    embedded: bool
    label: str
    source_url: str
    destination_start: int
    destination_end: int


def discover_media(markdown: str) -> tuple[MarkdownMedia, ...]:
    parser = MarkdownIt("commonmark", {"store_labels": True})
    parser.inline.ruler.at("image", _recording_image_rule)
    parser.inline.ruler.at("link", _recording_link_rule)
    environment: dict[str, object] = {}
    tokens = parser.parse(markdown, environment)
    line_starts = _line_starts(markdown)
    discovered: list[MarkdownMedia] = []
    referenced: dict[str, tuple[str, str, bool, str]] = {}
    for token in tokens:
        if token.type != "inline" or token.map is None:
            continue
        source_map = _inline_source_map(markdown, token, line_starts)
        for child in token.children or ():
            candidate = _media_from_token(child, source_map, len(discovered) + 1)
            if candidate is not None:
                discovered.append(candidate)
                continue
            reference = _reference_media(child)
            if reference is not None:
                referenced.setdefault(reference[0], reference[1:])
    references = environment.get("references")
    if isinstance(references, dict):
        for label, media in referenced.items():
            definition = references.get(label)
            span = _reference_destination_span(markdown, definition, media[0], line_starts)
            if span is None:
                raise ValueError("无法定位 Markdown 引用式媒体地址")
            discovered.append(
                MarkdownMedia(len(discovered) + 1, media[1], media[2], media[3], media[0], span[0], span[1])
            )
    return tuple(discovered)


def rewrite_media(
    markdown: str,
    manifest: tuple[MarkdownMedia, ...],
    destinations: tuple[str, ...],
) -> str:
    if len(manifest) != len(destinations):
        raise ValueError("Markdown 媒体数量与替换地址不一致")
    replacements = [
        (item.destination_start, item.destination_end, destinations[index]) for index, item in enumerate(manifest)
    ]
    result = markdown
    last_start = len(markdown) + 1
    for start, end, replacement in sorted(replacements, reverse=True):
        if end > last_start:
            raise ValueError("Markdown 媒体源位置发生重叠")
        result = result[:start] + replacement + result[end:]
        last_start = start
    return result


def _recording_image_rule(state: StateInline, silent: bool) -> bool:
    start = state.pos
    matched = markdown_image_rule(state, silent)
    if matched and not silent:
        token = state.tokens[-1]
        _record_destination(token, state, start, label_start=start + 1)
        token.meta["media_label"] = token.content
    return matched


def _recording_link_rule(state: StateInline, silent: bool) -> bool:
    start = state.pos
    token_start = len(state.tokens)
    matched = markdown_link_rule(state, silent)
    if matched and not silent:
        token = next((item for item in state.tokens[token_start:] if item.type == "link_open"), None)
        if token is not None:
            label_end = state.md.helpers.parseLinkLabel(state, start, False)
            _record_destination(token, state, start, label_start=start)
            token.meta["media_label"] = state.src[start + 1 : label_end] if label_end >= 0 else ""
    return matched


def _record_destination(token: Token, state: StateInline, start: int, *, label_start: int) -> None:
    span = _inline_destination_span(state, label_start)
    if span is None:
        return
    token.meta["destination_start"], token.meta["destination_end"] = span
    token.meta["source_start"] = start


def _inline_destination_span(state: StateInline, label_start: int) -> tuple[int, int] | None:
    label_end = state.md.helpers.parseLinkLabel(state, label_start, False)
    position = label_end + 1
    if label_end < 0 or position >= len(state.src) or state.src[position] != "(":
        return None
    position += 1
    while position < len(state.src) and (state.src[position].isspace() or state.src[position] == "\n"):
        position += 1
    result = state.md.helpers.parseLinkDestination(state.src, position, len(state.src))
    if not result.ok:
        return None
    return (position + 1, result.pos - 1) if state.src[position] == "<" else (position, result.pos)


def _media_from_token(token: Token, source_map: "_InlineSourceMap", ordinal: int) -> MarkdownMedia | None:
    if token.type not in {"image", "link_open"}:
        return None
    source_url = token.attrGet("src" if token.type == "image" else "href")
    start = token.meta.get("destination_start")
    end = token.meta.get("destination_end")
    label = token.meta.get("media_label", "")
    if not isinstance(source_url, str) or not isinstance(start, int) or not isinstance(end, int):
        return None
    if token.type == "link_open" and not _is_notion_download(source_url):
        return None
    kind = "图片" if token.type == "image" else _link_kind(source_url, str(label))
    return MarkdownMedia(
        ordinal,
        kind,
        token.type == "image",
        str(label),
        source_url,
        source_map.absolute(start),
        source_map.absolute(end),
    )


def _reference_media(token: Token) -> tuple[str, str, str, bool, str] | None:
    if token.type not in {"image", "link_open"}:
        return None
    label = token.meta.get("label")
    source_url = token.attrGet("src" if token.type == "image" else "href")
    if not isinstance(label, str) or not isinstance(source_url, str):
        return None
    if token.type == "link_open" and not _is_notion_download(source_url):
        return None
    kind = "图片" if token.type == "image" else _link_kind(source_url, str(token.meta.get("media_label", "")))
    media_label = token.content if token.type == "image" else str(token.meta.get("media_label", ""))
    return label, source_url, kind, token.type == "image", media_label


def _reference_destination_span(
    markdown: str,
    raw_definition: object,
    source_url: str,
    line_starts: list[int],
) -> tuple[int, int] | None:
    if not isinstance(raw_definition, dict):
        return None
    line_map = raw_definition.get("map")
    if not isinstance(line_map, list) or len(line_map) != 2 or not all(isinstance(item, int) for item in line_map):
        return None
    start_line, end_line = line_map
    if not 0 <= start_line < end_line < len(line_starts):
        return None
    start, end = line_starts[start_line], line_starts[end_line]
    position = markdown.find(source_url, start, end)
    return None if position < 0 else (position, position + len(source_url))


def _is_notion_download(url: str) -> bool:
    parsed = urlsplit(url)
    host = (parsed.hostname or "").casefold()
    return (
        host == "notion.so"
        or host.endswith(".notion.so")
        or host.endswith(".notion-static.com")
        or (host.endswith(".amazonaws.com") and host.startswith("prod-files-secure."))
    )


def _link_kind(url: str, label: str) -> str:
    path_suffix = PurePosixPath(unquote(urlsplit(url).path)).suffix.casefold()
    label_suffix = PurePosixPath(label).suffix.casefold()
    suffix = path_suffix or label_suffix
    if suffix in _IMAGE_EXTENSIONS:
        return "图片"
    if suffix in _AUDIO_EXTENSIONS:
        return "音频"
    if suffix in _VIDEO_EXTENSIONS:
        return "视频"
    return "附件"


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
            raise ValueError("Markdown 媒体偏移超出正文范围")
        line = max(0, bisect_right(self.local_starts, local_offset) - 1)
        return self.absolute_starts[line] + local_offset - self.local_starts[line]


def _inline_source_map(markdown: str, token: Token, line_starts: list[int]) -> _InlineSourceMap:
    assert token.map is not None
    start_line, end_line = token.map
    local_starts: list[int] = []
    absolute_starts: list[int] = []
    local_offset = 0
    source_line = start_line
    for content_line in token.content.splitlines(keepends=True) or [""]:
        body = content_line.removesuffix("\n")
        match = _find_content_line(markdown, body, source_line, end_line, line_starts)
        if match is None:
            raise ValueError("无法将 Markdown 媒体安全映射回源文")
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
