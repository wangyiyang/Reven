from collections.abc import Mapping
from typing import Any

import pytest
from qcloud_cos.cos_exception import CosServiceError  # type: ignore[import-untyped]
from reven.integrations.tencent_cos.client import TencentCosClient, TencentCosRequestError
from reven.integrations.tencent_cos.configuration import TencentCosConfiguration


class FakeSdkClient:
    def __init__(self, response: Mapping[str, Any] | None = None, error: Exception | None = None) -> None:
        self.response = response or {}
        self.error = error
        self.head_bucket_calls: list[str] = []
        self.head_object_calls: list[tuple[str, str]] = []
        self.put_calls: list[dict[str, Any]] = []

    def head_bucket(self, *, Bucket: str) -> Mapping[str, Any]:  # noqa: N803
        self.head_bucket_calls.append(Bucket)
        return self._result()

    def head_object(self, *, Bucket: str, Key: str) -> Mapping[str, Any]:  # noqa: N803
        self.head_object_calls.append((Bucket, Key))
        return self._result()

    def put_object(self, **kwargs: Any) -> Mapping[str, Any]:
        self.put_calls.append(kwargs)
        return self._result()

    def _result(self) -> Mapping[str, Any]:
        if self.error:
            raise self.error
        return self.response


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
async def test_verify_bucket_uses_full_bucket_name() -> None:
    sdk = FakeSdkClient()
    client = TencentCosClient(_configuration(), sdk_client=sdk)

    await client.verify_bucket()

    assert sdk.head_bucket_calls == ["reven-1251081768"]


@pytest.mark.anyio
async def test_head_object_returns_normalized_metadata() -> None:
    sdk = FakeSdkClient(
        {
            "Content-Length": "4",
            "Content-Type": "image/png; charset=binary",
            "x-cos-meta-sha256": "a" * 64,
        }
    )
    client = TencentCosClient(_configuration(), sdk_client=sdk)

    metadata = await client.head_object("assets/test")

    assert sdk.head_object_calls == [("reven-1251081768", "assets/test")]
    assert metadata is not None
    assert metadata.sha256 == "a" * 64
    assert metadata.size == 4
    assert metadata.mime_type == "image/png"


@pytest.mark.anyio
async def test_head_object_returns_none_for_missing_object() -> None:
    error = CosServiceError("HEAD", {"code": "NoSuchKey", "message": "missing"}, 404)
    client = TencentCosClient(_configuration(), sdk_client=FakeSdkClient(error=error))

    assert await client.head_object("assets/missing") is None


@pytest.mark.anyio
async def test_put_object_uses_sdk_integrity_and_immutable_metadata() -> None:
    sdk = FakeSdkClient()
    client = TencentCosClient(_configuration(), sdk_client=sdk)

    await client.put_object("assets/test", b"test", "image/png", "a" * 64)

    assert sdk.put_calls == [
        {
            "Bucket": "reven-1251081768",
            "Body": b"test",
            "Key": "assets/test",
            "EnableMD5": True,
            "StorageClass": "DEFAULT",
            "ContentType": "image/png",
            "CacheControl": "public, max-age=31536000, immutable",
            "Metadata": {"x-cos-meta-sha256": "a" * 64},
        }
    ]


@pytest.mark.anyio
async def test_service_error_is_explicit_and_retryable() -> None:
    error = CosServiceError(
        "HEAD",
        {"code": "ServiceUnavailable", "message": "unavailable", "requestid": "request-1"},
        503,
    )
    client = TencentCosClient(_configuration(), sdk_client=FakeSdkClient(error=error))

    with pytest.raises(TencentCosRequestError) as captured:
        await client.verify_bucket()

    assert captured.value.code == "ServiceUnavailable"
    assert captured.value.request_id == "request-1"
    assert captured.value.retryable is True
