import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, cast

from qcloud_cos import CosConfig, CosS3Client  # type: ignore[import-untyped]
from qcloud_cos.cos_exception import CosClientError, CosServiceError  # type: ignore[import-untyped]

from reven.integrations.tencent_cos.configuration import TencentCosConfiguration


class TencentCosRequestError(RuntimeError):
    def __init__(self, status: int | None, code: str, request_id: str | None, *, retryable: bool) -> None:
        message = f"腾讯云 COS 请求失败（status={status}, code={code}"
        if request_id:
            message += f", request_id={request_id}"
        super().__init__(message + "）")
        self.status = status
        self.code = code
        self.request_id = request_id
        self.retryable = retryable


@dataclass(frozen=True)
class ObjectMetadata:
    sha256: str | None
    size: int
    mime_type: str


class CosSdkClient(Protocol):
    def head_bucket(self, *, Bucket: str) -> Mapping[str, Any]: ...  # noqa: N803
    def head_object(self, *, Bucket: str, Key: str) -> Mapping[str, Any]: ...  # noqa: N803
    def put_object(self, **kwargs: Any) -> Mapping[str, Any]: ...


class TencentCosClient:
    def __init__(
        self,
        configuration: TencentCosConfiguration,
        *,
        sdk_client: CosSdkClient | None = None,
    ) -> None:
        self._configuration = configuration
        self._client = sdk_client or _build_sdk_client(configuration)

    async def aclose(self) -> None:
        return None

    async def verify_bucket(self) -> None:
        try:
            await asyncio.to_thread(self._client.head_bucket, Bucket=self._configuration.bucket)
        except (CosServiceError, CosClientError) as exc:
            raise _request_error(exc) from exc

    async def head_object(self, key: str) -> ObjectMetadata | None:
        try:
            response = await asyncio.to_thread(
                self._client.head_object,
                Bucket=self._configuration.bucket,
                Key=key,
            )
        except CosServiceError as exc:
            if _status_code(exc) == 404:
                return None
            raise _request_error(exc) from exc
        except CosClientError as exc:
            raise _request_error(exc) from exc
        headers = {str(name).lower(): str(value) for name, value in response.items()}
        try:
            size = int(headers["content-length"])
        except (KeyError, ValueError) as exc:
            raise TencentCosRequestError(200, "InvalidMetadata", None, retryable=False) from exc
        mime_type = headers.get("content-type", "application/octet-stream").split(";", 1)[0].strip().lower()
        return ObjectMetadata(headers.get("x-cos-meta-sha256"), size, mime_type)

    async def put_object(self, key: str, content: bytes, mime_type: str, sha256: str) -> None:
        try:
            await asyncio.to_thread(
                self._client.put_object,
                Bucket=self._configuration.bucket,
                Body=content,
                Key=key,
                EnableMD5=True,
                StorageClass="DEFAULT",
                ContentType=mime_type,
                CacheControl="public, max-age=31536000, immutable",
                Metadata={"x-cos-meta-sha256": sha256},
            )
        except (CosServiceError, CosClientError) as exc:
            raise _request_error(exc) from exc


def _build_sdk_client(configuration: TencentCosConfiguration) -> CosSdkClient:
    config = CosConfig(
        Region=configuration.region,
        SecretId=configuration.secret_id,
        SecretKey=configuration.secret_key,
        Token=None,
        Scheme="https",
    )
    return cast(CosSdkClient, CosS3Client(config))


def _request_error(exc: Exception) -> TencentCosRequestError:
    if isinstance(exc, CosServiceError):
        status = _status_code(exc)
        code = str(exc.get_error_code() or "Unknown")
        request_id = str(exc.get_request_id()) if exc.get_request_id() else None
        retryable = status in {408, 425, 429} or status >= 500
        return TencentCosRequestError(status, code, request_id, retryable=retryable)
    return TencentCosRequestError(None, type(exc).__name__, None, retryable=True)


def _status_code(exc: Any) -> int:
    return int(exc.get_status_code())
