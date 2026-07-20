"""Importing domain — file registration service.

上传 → SHA-256 去重 → MinIO 不可变落盘 → source_file 记录
"""

import hashlib

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from reven.importing.models import SourceFile, SourceFileStatus
from reven.kernel.ports.storage import StoragePort

_FILE_BUCKET = "reven-files"


class FileRegistrationService:
    """Register an uploaded file: dedup → store → record."""

    def __init__(self, storage: StoragePort, session: AsyncSession) -> None:
        self._storage = storage
        self._session = session

    async def register(
        self,
        *,
        filename: str,
        data: bytes,
        mime_type: str | None = None,
    ) -> SourceFile:
        """Register a file: dedup by SHA-256, upload to MinIO, persist record."""
        sha256_hash = hashlib.sha256(data).hexdigest()

        # Dedup: skip if same hash already registered
        existing = await self._session.execute(select(SourceFile).where(SourceFile.sha256_hash == sha256_hash))
        existing_file = existing.scalar_one_or_none()
        if existing_file is not None:
            return existing_file

        # Upload to MinIO with SHA-256 as immutable key
        storage_key = f"uploads/{sha256_hash[:2]}/{sha256_hash[2:4]}/{sha256_hash}"
        descriptor = await self._storage.upload(
            bucket=_FILE_BUCKET,
            key=storage_key,
            data=data,
            mime_type=mime_type,
        )

        # Persist metadata
        source_file = SourceFile(
            original_filename=filename,
            sha256_hash=sha256_hash,
            storage_path=f"{_FILE_BUCKET}/{storage_key}",
            file_size=descriptor.size,
            mime_type=descriptor.mime_type,
            status=SourceFileStatus.PENDING,
        )
        self._session.add(source_file)
        await self._session.commit()
        await self._session.refresh(source_file)
        return source_file
