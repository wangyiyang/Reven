"""MinIO adapter — implements StoragePort for S3-compatible storage."""

import hashlib
import io
from collections.abc import AsyncIterator

from minio import Minio
from minio.error import S3Error

from reven.kernel.ports.storage import FileDescriptor, StoragePort


class MinioStorageAdapter(StoragePort):
    """MinIO/S3 implementation of StoragePort."""

    def __init__(self, client: Minio) -> None:
        self._client = client

    async def upload(
        self,
        *,
        bucket: str,
        key: str,
        data: bytes,
        mime_type: str | None = None,
    ) -> FileDescriptor:
        sha256 = hashlib.sha256(data).hexdigest()
        if not self._client.bucket_exists(bucket):
            self._client.make_bucket(bucket)

        content_type = mime_type or "application/octet-stream"
        size = len(data)
        self._client.put_object(
            bucket,
            key,
            io.BytesIO(data),
            length=size,
            content_type=content_type,
        )
        return FileDescriptor(
            path=f"{bucket}/{key}",
            size=size,
            sha256_hash=sha256,
            mime_type=content_type,
        )

    async def download(self, *, bucket: str, key: str) -> AsyncIterator[bytes]:
        response = self._client.get_object(bucket, key)
        try:
            while chunk := response.read(8192):
                yield chunk
        finally:
            response.close()
            response.release_conn()

    async def delete(self, *, bucket: str, key: str) -> None:
        try:
            self._client.remove_object(bucket, key)
        except S3Error:
            pass  # idempotent

    async def exists(self, *, bucket: str, key: str) -> bool:
        try:
            self._client.stat_object(bucket, key)
            return True
        except S3Error:
            return False
