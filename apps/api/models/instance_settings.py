import uuid
from datetime import datetime
from sqlalchemy import BigInteger, Boolean, DateTime, SmallInteger, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
try:
    from ..database import Base
except ImportError:
    from database import Base


class InstanceSettings(Base):
    """Single-row table holding instance-wide (deployment-level) settings.

    Singleton: exactly one row, created lazily via get_or_create in the router.
    storage_limit_bytes == 0 means unlimited (matches MAX_UPLOAD_BYTES).
    upload_part_size_bytes == 0 means parts are sized from each file (see part_size_for).
    allow_original_downloads lets people outside a project (share links, public
    projects, direct shares) download originals; members always can.
    compression_level is how hard review streams are compressed, 1 (highest
    quality) to 5 (smallest files); see packages.transcoder.base.
    """
    __tablename__ = "instance_settings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    storage_limit_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    upload_part_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    allow_original_downloads: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    # NULL rather than a server default of 3, and the distinction is the
    # feature: NULL means "nobody has chosen", which keeps
    # TRANSCODER_CRF_OFFSET in charge of an instance configured that way. A
    # default of 3 would write "balanced" into every row on upgrade.
    compression_level: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    # The key Cylch (the studio's project app) signs its requests with: see
    # routers/cylch.py. Only its SHA-256 is kept, so the key is shown once, when
    # it is made. NULL means no key: the integration is off. made_by is the
    # administrator who made it, and owns the projects Cylch creates.
    cylch_key_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    cylch_key_made_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    cylch_key_made_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cylch_key_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
