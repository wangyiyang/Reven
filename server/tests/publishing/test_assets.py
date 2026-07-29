import hashlib
import socket
from pathlib import Path

import httpx
import pytest
import reven.publishing.assets as assets_module
from reven.publishing.assets import AssetDownloadError, AssetMaterializer

PNG = b"\x89PNG\r\n\x1a\n" + b"x" * 20


async def public_resolver(host: str, port: int, *, type: int) -> list[tuple[object, ...]]:
    del host, type
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]


@pytest.mark.anyio
async def test_materializer_uses_sequential_names_and_hashes(tmp_path: Path) -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, headers={"content-type": "image/png"}, content=PNG)
    )
    async with httpx.AsyncClient(transport=transport) as client:
        result = await AssetMaterializer(tmp_path, client, resolver=public_resolver).materialize(
            "job-1", ["https://example.com/image"], "https://example.com/cover"
        )

    assert result.images[0].path.name == "image-1.png"
    assert result.cover.path.name == "cover.png"
    assert result.images[0].sha256 == hashlib.sha256(PNG).hexdigest()


@pytest.mark.anyio
async def test_materializer_rejects_private_dns_target(tmp_path: Path) -> None:
    async def private_resolver(host: str, port: int, *, type: int) -> list[tuple[object, ...]]:
        del host, type
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", port))]

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=PNG))
    ) as client:
        with pytest.raises(AssetDownloadError, match="不安全"):
            await AssetMaterializer(tmp_path, client, resolver=private_resolver).materialize(
                "job-1", [], "https://localhost/cover"
            )


@pytest.mark.anyio
async def test_materializer_rejects_mime_magic_mismatch(tmp_path: Path) -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, headers={"content-type": "image/png"}, content=b"not an image")
    )
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(AssetDownloadError, match="格式"):
            await AssetMaterializer(tmp_path, client, resolver=public_resolver).materialize(
                "job-1", [], "https://example.com/cover"
            )


@pytest.mark.anyio
async def test_materializer_revalidates_redirect_target(tmp_path: Path) -> None:
    async def resolver(host: str, port: int, *, type: int) -> list[tuple[object, ...]]:
        del type
        address = "127.0.0.1" if host == "internal.example" else "93.184.216.34"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port))]

    transport = httpx.MockTransport(
        lambda request: httpx.Response(302, headers={"location": "https://internal.example/cover"})
    )
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(AssetDownloadError, match="内部网络"):
            await AssetMaterializer(tmp_path, client, resolver=resolver).materialize(
                "job-1", [], "https://example.com/cover"
            )


@pytest.mark.anyio
async def test_materializer_streaming_limit_removes_partial_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(assets_module, "MAX_FILE_BYTES", 10)
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, headers={"content-type": "image/png"}, content=PNG)
    )
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(AssetDownloadError, match="大小限制"):
            await AssetMaterializer(tmp_path, client, resolver=public_resolver).materialize(
                "job-1", [], "https://example.com/cover"
            )

    assert list((tmp_path / "jobs" / "job-1" / "snapshot").glob("*")) == []


@pytest.mark.anyio
async def test_materializer_classifies_network_failure(tmp_path: Path) -> None:
    def fail(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("signed-url-secret", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(fail)) as client:
        with pytest.raises(AssetDownloadError) as caught:
            await AssetMaterializer(tmp_path, client, resolver=public_resolver).materialize(
                "job-1", [], "https://example.com/cover?token=secret"
            )

    assert caught.value.code == "download_failed"
    assert "secret" not in str(caught.value)


@pytest.mark.anyio
async def test_materializer_enforces_cumulative_job_limit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(assets_module, "MAX_JOB_BYTES", len(PNG) + 5)
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, headers={"content-type": "image/png"}, content=PNG)
    )
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(AssetDownloadError, match="大小限制"):
            await AssetMaterializer(tmp_path, client, resolver=public_resolver).materialize(
                "job-1", ["https://example.com/image"], "https://example.com/cover"
            )

    assert list((tmp_path / "jobs" / "job-1" / "snapshot").glob("*")) == []
