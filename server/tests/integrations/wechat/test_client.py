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

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/cgi-bin/token":
            token = f"token-{calls.count('/cgi-bin/token')}"
            return httpx.Response(200, json={"access_token": token, "expires_in": 7200})
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
    [(408, False), (429, False), (500, True)],
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
