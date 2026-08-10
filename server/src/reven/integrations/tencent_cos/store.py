import hashlib
import re
from dataclasses import dataclass
from typing import Protocol

from reven.config import Settings
from reven.integrations.tencent_cos.client import ObjectMetadata, TencentCosClient
from reven.integrations.tencent_cos.configuration import TencentCosConfiguration, load_tencent_cos_configuration

_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
_MIME_PATTERN = re.compile(r"[a-z0-9][a-z0-9!#$&^_.+-]*/[a-z0-9][a-z0-9!#$&^_.+-]*")


class AssetArchiveError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class TencentCosObjectClient(Protocol):
    async def verify_bucket(self) -> None: ...
    async def head_object(self, key: str) -> ObjectMetadata | None: ...
    async def put_object(self, key: str, content: bytes, mime_type: str, sha256: str) -> None: ...
    async def aclose(self) -> None: ...


@dataclass(frozen=True)
class ArchivedAsset:
    key: str
    sha256: str
    mime_type: str
    size: int
    public_url: str
    reused: bool


class TencentCosAssetStore:
    def __init__(self, client: TencentCosObjectClient, configuration: TencentCosConfiguration) -> None:
        self._client = client
        self._configuration = configuration

    async def verify_connection(self) -> None:
        await self._client.verify_bucket()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def archive(self, content: bytes, *, sha256: str, mime_type: str) -> ArchivedAsset:
        normalized_mime = mime_type.strip().lower()
        self._validate(content, sha256, normalized_mime)
        key = f"{self._configuration.asset_prefix}/{sha256[:2]}/{sha256}"
        existing = await self._client.head_object(key)
        if existing is not None:
            self._verify_existing(existing, sha256, normalized_mime, len(content))
            return self._result(key, sha256, normalized_mime, len(content), reused=True)
        await self._client.put_object(key, content, normalized_mime, sha256)
        return self._result(key, sha256, normalized_mime, len(content), reused=False)

    @staticmethod
    def _validate(content: bytes, sha256: str, mime_type: str) -> None:
        if _SHA256_PATTERN.fullmatch(sha256) is None:
            raise AssetArchiveError("invalid_digest", "资产 SHA-256 格式无效")
        if hashlib.sha256(content).hexdigest() != sha256:
            raise AssetArchiveError("digest_mismatch", "资产内容与 SHA-256 不一致")
        if _MIME_PATTERN.fullmatch(mime_type) is None:
            raise AssetArchiveError("invalid_mime_type", "资产 MIME 类型无效")

    @staticmethod
    def _verify_existing(metadata: ObjectMetadata, sha256: str, mime_type: str, size: int) -> None:
        if metadata.sha256 != sha256 or metadata.size != size or metadata.mime_type != mime_type:
            raise AssetArchiveError("object_conflict", "同一内容地址已存在，但对象元数据不一致")

    def _result(self, key: str, sha256: str, mime_type: str, size: int, *, reused: bool) -> ArchivedAsset:
        return ArchivedAsset(
            key,
            sha256,
            mime_type,
            size,
            f"{self._configuration.public_base_url}/{key}",
            reused,
        )


def build_tencent_cos_asset_store(settings: Settings) -> TencentCosAssetStore:
    configuration = load_tencent_cos_configuration(settings)
    return TencentCosAssetStore(TencentCosClient(configuration), configuration)
