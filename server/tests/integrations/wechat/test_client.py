import asyncio
from pathlib import Path

import httpx
import pytest
from reven.integrations.wechat.client import WeChatClient
from reven.integrations.wechat.models import (
    WeChatBlockedError,
    WeChatPermanentError,
    WeChatTransientError,
)


@pytest.mark.anyio
async def test_token_cache_is_single_flight_and_uses_cached_token() -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.01)
        return httpx.Response(200, json={"access_token": "token-value", "expires_in": 7200})

    async with httpx.AsyncClient(
        base_url="https://api.weixin.qq.com",
        transport=httpx.MockTransport(handler),
    ) as http:
        client = WeChatClient("appid", "secret", http)
        tokens = await asyncio.gather(*(client.get_token() for _ in range(8)))
        assert tokens == ["token-value"] * 8
        assert await client.get_token() == "token-value"
    assert calls == 1


@pytest.mark.anyio
async def test_invalid_token_refreshes_and_replays_operation_once(tmp_path: Path) -> None:
    calls: list[str] = []
    upload_bodies: list[bytes] = []
    upload_types: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/cgi-bin/token":
            token = f"token-{calls.count('/cgi-bin/token')}"
            return httpx.Response(200, json={"access_token": token, "expires_in": 7200})
        upload_bodies.append(await request.aread())
        upload_types.append(request.headers["Content-Type"])
        if calls.count("/cgi-bin/media/uploadimg") == 1:
            return httpx.Response(200, json={"errcode": 40014, "errmsg": "invalid access_token"})
        return httpx.Response(200, json={"url": "https://mmbiz.qpic.cn/image"})

    image = tmp_path / "image.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\npayload")
    async with httpx.AsyncClient(
        base_url="https://api.weixin.qq.com",
        transport=httpx.MockTransport(handler),
    ) as http:
        result = await WeChatClient("appid", "secret", http).upload_body_image(image)

    assert result == "https://mmbiz.qpic.cn/image"
    assert calls == [
        "/cgi-bin/token",
        "/cgi-bin/media/uploadimg",
        "/cgi-bin/token",
        "/cgi-bin/media/uploadimg",
    ]
    assert len(upload_bodies) == 2
    assert all(b"\x89PNG\r\n\x1a\npayload" in body for body in upload_bodies)
    assert all(content_type.startswith("multipart/form-data; boundary=") for content_type in upload_types)


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("payload", "error_type"),
    [
        ({"errcode": 40164, "errmsg": "invalid ip"}, WeChatBlockedError),
        ({"errcode": 45009, "errmsg": "reach max api daily quota limit"}, WeChatTransientError),
        ({"errcode": 40007, "errmsg": "invalid media_id"}, WeChatPermanentError),
    ],
)
async def test_business_errors_are_classified_and_redacted(
    payload: dict[str, object],
    error_type: type[Exception],
) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/cgi-bin/token":
            return httpx.Response(200, json={"access_token": "sensitive-token", "expires_in": 7200})
        return httpx.Response(200, json=payload)

    async with httpx.AsyncClient(
        base_url="https://api.weixin.qq.com",
        transport=httpx.MockTransport(handler),
    ) as http:
        client = WeChatClient("appid", "app-secret", http)
        with pytest.raises(error_type) as raised:
            await client.create_draft({"articles": []})

    message = str(raised.value)
    assert f"code={payload['errcode']}" in message
    assert "app-secret" not in message
    assert "sensitive-token" not in message
    assert "access_token=" not in message


@pytest.mark.anyio
async def test_cover_upload_uses_multipart_and_closes_file(tmp_path: Path) -> None:
    image = tmp_path / "cover.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\npayload")
    seen = b""

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal seen
        if request.url.path == "/cgi-bin/token":
            return httpx.Response(200, json={"access_token": "token", "expires_in": 7200})
        seen = await request.aread()
        assert request.url.params["type"] == "image"
        return httpx.Response(200, json={"media_id": "thumb-id"})

    async with httpx.AsyncClient(
        base_url="https://api.weixin.qq.com",
        transport=httpx.MockTransport(handler),
    ) as http:
        result = await WeChatClient("appid", "secret", http).upload_cover_material(image)

    assert result == "thumb-id"
    assert b'filename="cover.png"' in seen
    image.rename(tmp_path / "renamed.png")


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("status", "uncertain"),
    [(408, True), (429, False), (500, True)],
)
async def test_http_transient_errors_record_outcome_certainty(status: int, uncertain: bool) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/cgi-bin/token":
            return httpx.Response(200, json={"access_token": "token", "expires_in": 7200})
        return httpx.Response(status, json={"errcode": -1})

    async with httpx.AsyncClient(
        base_url="https://api.weixin.qq.com",
        transport=httpx.MockTransport(handler),
    ) as http:
        with pytest.raises(WeChatTransientError) as raised:
            await WeChatClient("appid", "secret", http).create_draft({"articles": []})
    assert raised.value.outcome_uncertain is uncertain


@pytest.mark.anyio
async def test_uploadimg_rejects_non_wechat_host(tmp_path: Path) -> None:
    image = tmp_path / "image.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\npayload")

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/cgi-bin/token":
            return httpx.Response(200, json={"access_token": "token", "expires_in": 7200})
        return httpx.Response(200, json={"url": "https://example.com/image"})

    async with httpx.AsyncClient(
        base_url="https://api.weixin.qq.com",
        transport=httpx.MockTransport(handler),
    ) as http:
        with pytest.raises(WeChatPermanentError):
            await WeChatClient("appid", "secret", http).upload_body_image(image)


@pytest.mark.anyio
@pytest.mark.parametrize("status", [200, 408, 500])
async def test_post_http_failures_are_uncertain_but_token_get_is_safe(status: int) -> None:
    async def post_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/cgi-bin/token":
            return httpx.Response(200, json={"access_token": "token", "expires_in": 7200})
        return httpx.Response(status, json={"errcode": -1})

    async with httpx.AsyncClient(
        base_url="https://api.weixin.qq.com",
        transport=httpx.MockTransport(post_handler),
    ) as http:
        with pytest.raises(WeChatTransientError) as raised:
            await WeChatClient("appid", "secret", http).create_draft({"articles": []})
    assert raised.value.outcome_uncertain

    async def token_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"errcode": -1})

    async with httpx.AsyncClient(
        base_url="https://api.weixin.qq.com",
        transport=httpx.MockTransport(token_handler),
    ) as http:
        with pytest.raises(WeChatTransientError) as token_error:
            await WeChatClient("appid", "secret", http).get_token()
    assert not token_error.value.outcome_uncertain


class ChunkedStream(httpx.AsyncByteStream):
    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = chunks
        self.read_count = 0
        self.closed = False

    async def __aiter__(self):  # type: ignore[no-untyped-def]
        for chunk in self.chunks:
            self.read_count += 1
            yield chunk

    async def aclose(self) -> None:
        self.closed = True


@pytest.mark.anyio
@pytest.mark.parametrize("declared_length", [None, "1"])
async def test_streaming_response_stops_at_actual_size_limit(
    declared_length: str | None,
) -> None:
    stream = ChunkedStream([b"x" * (512 * 1024), b"y" * (512 * 1024 + 1), b"never-read"])
    headers = {"Content-Length": declared_length} if declared_length else {}

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers=headers, stream=stream)

    async with httpx.AsyncClient(
        base_url="https://api.weixin.qq.com",
        transport=httpx.MockTransport(handler),
    ) as http:
        with pytest.raises(WeChatTransientError):
            await WeChatClient("appid", "secret", http).get_token()
    assert stream.read_count == 2
    assert stream.closed


@pytest.mark.anyio
async def test_oversized_content_length_is_rejected_without_reading_body() -> None:
    stream = ChunkedStream([b"must-not-read"])

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"Content-Length": str(1024 * 1024 + 1)}, stream=stream)

    async with httpx.AsyncClient(
        base_url="https://api.weixin.qq.com",
        transport=httpx.MockTransport(handler),
    ) as http:
        with pytest.raises(WeChatTransientError):
            await WeChatClient("appid", "secret", http).get_token()
    assert stream.read_count == 0
    assert stream.closed


@pytest.mark.anyio
async def test_streaming_json_handles_multibyte_split_across_chunks() -> None:
    payload = '{"access_token":"令牌","expires_in":7200}'.encode()
    split = payload.index("令".encode()) + 1
    stream = ChunkedStream([payload[:split], payload[split:]])

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=stream)

    async with httpx.AsyncClient(
        base_url="https://api.weixin.qq.com",
        transport=httpx.MockTransport(handler),
    ) as http:
        assert await WeChatClient("appid", "secret", http).get_token() == "令牌"
