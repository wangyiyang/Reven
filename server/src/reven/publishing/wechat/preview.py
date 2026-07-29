"""Side-effect-free rendering of the latest Notion article."""

from pathlib import Path
from urllib.parse import unquote, urlsplit

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from reven.integrations.notion.client import NotionClient
from reven.integrations.notion.configuration import load_notion_config
from reven.integrations.notion.mapper import map_notion_page
from reven.integrations.notion.service import NOTION_BASE_URL, REQUEST_TIMEOUT
from reven.publishing.snapshot import build_snapshot, image_urls, replace_image_destinations
from reven.publishing.wechat.factory import _renderer_parts
from reven.publishing.wechat.renderer import WechatRenderer


class PreviewConflictError(RuntimeError):
    pass


class PreviewValidationError(RuntimeError):
    pass


MAX_PREVIEW_MARKDOWN_BYTES = 1024 * 1024
MAX_PREVIEW_IMAGES = 100
_MEDIA_HOSTS = frozenset(
    {
        "file.notion.so",
        "files.notion.so",
        "secure.notion-static.com",
        "prod-files-secure.s3.amazonaws.com",
        "prod-files-secure.s3.us-west-2.amazonaws.com",
    }
)


class ConfiguredWechatPreview:
    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        renderer_command: str,
    ) -> None:
        self.factory = factory
        self.renderer_command = renderer_command

    async def render_latest(self, notion_page_id: str) -> str:
        token, _ = await load_notion_config(self.factory)
        async with httpx.AsyncClient(
            base_url=NOTION_BASE_URL,
            timeout=REQUEST_TIMEOUT,
            trust_env=False,
        ) as http:
            notion = NotionClient(token, http)
            before = map_notion_page(await notion.retrieve_page(notion_page_id))
            markdown = await notion.retrieve_page_markdown(notion_page_id)
            after = map_notion_page(await notion.retrieve_page(notion_page_id))
        if before.last_edited_at != after.last_edited_at:
            raise PreviewConflictError("Notion 页面在预览生成期间发生变化")
        preview_markdown = _canonical_with_current_urls(markdown)
        executable, cli_path = _renderer_parts(self.renderer_command)
        return await WechatRenderer(executable, Path(cli_path)).render(preview_markdown)


def _canonical_with_current_urls(markdown: str) -> str:
    if len(markdown.encode("utf-8")) > MAX_PREVIEW_MARKDOWN_BYTES:
        raise PreviewValidationError("Notion 正文超过预览大小限制")
    urls = image_urls(markdown)
    if len(urls) > MAX_PREVIEW_IMAGES:
        raise PreviewValidationError("Notion 正文图片数量超过预览限制")
    for url in urls:
        _validate_media_url(url)
    snapshot = build_snapshot(
        markdown,
        image_sha256=tuple("0" * 64 for _ in urls),
        cover_sha256="",
    )
    return replace_image_destinations(snapshot.markdown, urls)


def _validate_media_url(url: str) -> None:
    if any(character.isspace() or ord(character) < 32 for character in url):
        raise PreviewValidationError("Notion 正文包含不安全的图片地址")
    try:
        parsed = urlsplit(url)
        host = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise PreviewValidationError("Notion 正文包含不安全的图片地址") from exc
    if (
        parsed.scheme != "https"
        or not host
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
        or parsed.fragment
        or host not in _MEDIA_HOSTS
        or not _safe_media_path(parsed.path)
    ):
        raise PreviewValidationError("Notion 正文包含不安全的图片地址")


def _safe_media_path(path: str) -> bool:
    if not path.startswith("/") or path in {"", "/"} or path.startswith("//"):
        return False
    decoded = unquote(path)
    return "\\" not in decoded and all(segment not in {".", ".."} for segment in decoded.split("/"))
