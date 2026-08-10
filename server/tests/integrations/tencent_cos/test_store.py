import hashlib

import pytest
from reven.integrations.tencent_cos.client import ObjectMetadata
from reven.integrations.tencent_cos.configuration import TencentCosConfiguration
from reven.integrations.tencent_cos.store import AssetArchiveError, TencentCosAssetStore


class FakeClient:
    def __init__(self, existing: ObjectMetadata | None = None) -> None:
        self.existing = existing
        self.puts: list[tuple[str, bytes, str, str]] = []
        self.verified = False
        self.closed = False

    async def verify_bucket(self) -> None:
        self.verified = True

    async def head_object(self, key: str) -> ObjectMetadata | None:
        return self.existing

    async def put_object(self, key: str, content: bytes, mime_type: str, sha256: str) -> None:
        self.puts.append((key, content, mime_type, sha256))

    async def aclose(self) -> None:
        self.closed = True


def _configuration() -> TencentCosConfiguration:
    return TencentCosConfiguration(
        bucket="reven-1251081768",
        region="ap-beijing",
        secret_id="AKIDexample",
        secret_key="secret-key",
        public_base_url="https://assets.example.com",
        asset_prefix="assets/sha256",
    )


@pytest.mark.anyio
async def test_store_verifies_and_closes_client() -> None:
    client = FakeClient()
    store = TencentCosAssetStore(client, _configuration())

    await store.verify_connection()
    await store.aclose()

    assert client.verified is True
    assert client.closed is True


@pytest.mark.anyio
async def test_archive_uploads_to_content_addressed_key() -> None:
    content = b"asset"
    digest = hashlib.sha256(content).hexdigest()
    client = FakeClient()

    result = await TencentCosAssetStore(client, _configuration()).archive(
        content,
        sha256=digest,
        mime_type="image/png",
    )

    expected_key = f"assets/sha256/{digest[:2]}/{digest}"
    assert client.puts == [(expected_key, content, "image/png", digest)]
    assert result.key == expected_key
    assert result.public_url == f"https://assets.example.com/{expected_key}"
    assert result.reused is False


@pytest.mark.anyio
async def test_archive_reuses_verified_existing_object() -> None:
    content = b"asset"
    digest = hashlib.sha256(content).hexdigest()
    client = FakeClient(ObjectMetadata(digest, len(content), "image/png"))

    result = await TencentCosAssetStore(client, _configuration()).archive(
        content,
        sha256=digest,
        mime_type="image/png",
    )

    assert client.puts == []
    assert result.reused is True


@pytest.mark.anyio
async def test_archive_rejects_existing_object_with_unverified_metadata() -> None:
    content = b"asset"
    digest = hashlib.sha256(content).hexdigest()
    client = FakeClient(ObjectMetadata(None, len(content), "image/png"))

    with pytest.raises(AssetArchiveError) as captured:
        await TencentCosAssetStore(client, _configuration()).archive(
            content,
            sha256=digest,
            mime_type="image/png",
        )

    assert captured.value.code == "object_conflict"
    assert client.puts == []


@pytest.mark.anyio
async def test_archive_rejects_digest_mismatch_before_network_request() -> None:
    client = FakeClient()

    with pytest.raises(AssetArchiveError) as captured:
        await TencentCosAssetStore(client, _configuration()).archive(
            b"asset",
            sha256="0" * 64,
            mime_type="image/png",
        )

    assert captured.value.code == "digest_mismatch"
    assert client.puts == []
