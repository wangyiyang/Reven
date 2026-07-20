"""Storage port — abstract interface for object storage.

领域层依赖此端口，而非具体适配器。
适配器层面实现此接口（依赖方向: adapters → 端口 ← 领域）。
"""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator


class FileDescriptor:
    """Metadata about a stored file."""

    def __init__(
        self,
        *,
        path: str,
        size: int,
        sha256_hash: str,
        mime_type: str | None = None,
    ) -> None:
        self.path = path
        self.size = size
        self.sha256_hash = sha256_hash
        self.mime_type = mime_type


class StoragePort(ABC):
    """Port for object storage operations."""

    @abstractmethod
    async def upload(
        self,
        *,
        bucket: str,
        key: str,
        data: bytes,
        mime_type: str | None = None,
    ) -> FileDescriptor:
        """Upload bytes to storage, return file descriptor."""
        ...

    @abstractmethod
    async def download(self, *, bucket: str, key: str) -> AsyncIterator[bytes]:
        """Stream file content from storage.

        Implement as async generator: ``async def download(...): yield chunk``
        """
        ...
        # This is intentionally empty — subclasses should ``yield`` chunks.
        # mypy: declared as async so callers ``async for``, subclass yields.
        if False:  # pragma: no cover
            yield b""

    @abstractmethod
    async def delete(self, *, bucket: str, key: str) -> None:
        """Delete a file from storage."""
        ...

    @abstractmethod
    async def exists(self, *, bucket: str, key: str) -> bool:
        """Check if a file exists in storage."""
        ...
