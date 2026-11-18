import uuid
from datetime import datetime
from typing import Optional
from sqlalchemy import BigInteger, DateTime, Float, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
try:
    from ..database import Base
except ImportError:
    from database import Base


class ProcessingRun(Base):
    """How long one upload took to arrive and to process: one row per version.

    A log for tuning, not a record anything depends on. It is written
    best-effort beside the real work and read only by the admin report, so a
    missing row or a half-filled one is harmless.
    """
    __tablename__ = "processing_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # No foreign keys: the log outlives what it measured, and the retention GC
    # must be free to hard-delete the asset and version without this in the way.
    version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, unique=True)
    asset_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    project_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    asset_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    asset_type: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    original_filename: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    mime_type: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    file_size_bytes: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    duration_seconds: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    width: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    height: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    fps: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # The four moments. Upload start is when the version was created.
    upload_started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    upload_completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    processing_started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    processing_completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    # With the quick preview on: when the video first became watchable, and
    # how ("copy" of the upload, or a "720p" encode). Empty without one.
    preview_ready_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    preview_kind: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    # When the preview's files were cleared away after the ladder replaced
    # them. Empty while they are still there, which is how the sweep finds them.
    preview_removed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    # "ready" or "failed" once processing has ended; empty while it runs.
    outcome: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
