import socket
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest
from reven.content_sync.downloader import SecureContentDownloader
from reven.content_sync.media_archive import DownloadRequest

PNG = b"\x89PNG\r\n\x1a\n" + b"x" * 20
PDF = b"%PDF-1.7\n" + b"x" * 20


async def public_resolver(host: str, port: int, *, type: int) -> list[tuple[object, ...]]:
    del host, type
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]


class FakeRequester:
    @asynccontextmanager
    async def stream(self, url: str, pinned_ip: str) -> AsyncIterator[httpx.Response]:
        del pinned_ip
        content, mime = (PDF, "application/pdf") if url.endswith(".pdf") else (PNG, "image/png")
        response = httpx.Response(
            200,
            headers={"content-type": mime},
            content=content,
            request=httpx.Request("GET", url),
        )
        try:
            yield response
        finally:
            await response.aclose()


@pytest.mark.anyio
async def test_secure_downloader_accepts_allowlisted_image_and_attachment(tmp_path: Path) -> None:
    downloader = SecureContentDownloader(tmp_path, requester=FakeRequester(), resolver=public_resolver)
    requests = (
        DownloadRequest(0, "封面", False, "https://example.com/cover.png", "cover.png"),
        DownloadRequest(1, "附件", False, "https://example.com/report.pdf", "report.pdf"),
    )

    downloaded = [item async for item in downloader.download("11111111-1111-1111-1111-111111111111", requests)]

    assert [item.mime_type for item in downloaded] == ["image/png", "application/pdf"]
    assert [item.content for item in downloaded] == [PNG, PDF]
    assert [item.filename for item in downloaded] == ["cover.png", "report.pdf"]
    assert not (tmp_path / "content-sync" / "11111111-1111-1111-1111-111111111111").exists()
