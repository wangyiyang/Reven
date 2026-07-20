"""Importing domain — models for file import pipeline."""

import enum
from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from reven.kernel.models.base import Base, TimestampMixin, UUIDPkMixin


class SourceFileStatus(enum.StrEnum):
    PENDING = "pending"
    IMPORTING = "importing"
    COMPLETED = "completed"
    FAILED = "failed"


class BatchStatus(enum.StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class RowStatus(enum.StrEnum):
    RAW = "raw"
    PASSED = "passed"
    SKIPPED = "skipped"
    ERROR = "error"


class JobStatus(enum.StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class SourceFile(Base, UUIDPkMixin, TimestampMixin):
    """登錄的原始文件（不可变落盘后登记）。"""

    __tablename__ = "importing_source_file"

    original_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    sha256_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    storage_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    mime_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[SourceFileStatus] = mapped_column(
        Enum(SourceFileStatus, name="importing_source_file_status"),
        default=SourceFileStatus.PENDING,
        nullable=False,
    )

    batches: Mapped[list["ImportBatch"]] = relationship(back_populates="source_file", cascade="all, delete-orphan")


class ImportBatch(Base, UUIDPkMixin, TimestampMixin):
    """一次导入批次（一个文件可能多次导入重试）。"""

    __tablename__ = "importing_import_batch"

    source_file_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("importing_source_file.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[BatchStatus] = mapped_column(
        Enum(BatchStatus, name="importing_batch_status"),
        default=BatchStatus.PENDING,
        nullable=False,
    )
    total_rows: Mapped[int | None] = mapped_column(Numeric(12, 0), nullable=True)
    passed_rows: Mapped[int | None] = mapped_column(Numeric(12, 0), nullable=True)
    skipped_rows: Mapped[int | None] = mapped_column(Numeric(12, 0), nullable=True)
    error_rows: Mapped[int | None] = mapped_column(Numeric(12, 0), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    source_file: Mapped["SourceFile"] = relationship(back_populates="batches")
    raw_rows: Mapped[list["RawRow"]] = relationship(back_populates="import_batch", cascade="all, delete-orphan")
    jobs: Mapped[list["Job"]] = relationship(back_populates="import_batch", cascade="all, delete-orphan")


class RawRow(Base, UUIDPkMixin, TimestampMixin):
    """解析后的原始网格行（血缘最底层）。"""

    __tablename__ = "importing_raw_row"

    import_batch_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("importing_import_batch.id", ondelete="CASCADE"),
        nullable=False,
    )
    row_number: Mapped[int] = mapped_column(Numeric(12, 0), nullable=False)
    cell_data: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    coordinates: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True, default=dict)
    status: Mapped[RowStatus] = mapped_column(
        Enum(RowStatus, name="importing_row_status"),
        default=RowStatus.RAW,
        nullable=False,
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    import_batch: Mapped["ImportBatch"] = relationship(back_populates="raw_rows")


class Job(Base, UUIDPkMixin, TimestampMixin):
    """队列任务 — FOR UPDATE SKIP LOCKED 消费。"""

    __tablename__ = "importing_job"

    batch_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("importing_import_batch.id", ondelete="SET NULL"),
        nullable=True,
    )
    job_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus, name="importing_job_status"),
        default=JobStatus.QUEUED,
        nullable=False,
        index=True,
    )
    payload: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True, default=dict)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    queued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    import_batch: Mapped["ImportBatch | None"] = relationship(back_populates="jobs")
