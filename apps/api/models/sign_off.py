import uuid
from datetime import datetime
from typing import Optional
from sqlalchemy import String, DateTime, func, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
try:
    from ..database import Base
except ImportError:
    from database import Base


class SignOff(Base):
    """A client's formal sign-off of one version of an asset, made on a share link.

    The row is the record: who signed, what they agreed to, which version, when
    and from where. It is never edited or soft-deleted. Reopening the asset
    fills the `reopened_*` columns and leaves the rest as it was signed, so the
    history of every sign-off survives. An asset is signed off (and locked)
    while it has a row with `reopened_at` empty.
    """
    __tablename__ = "sign_offs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # No foreign keys, on purpose. This is a record of what a client agreed to,
    # so it has to outlive the asset, version, link and user it names: the
    # retention GC hard-deletes those, and a constraint would either block the
    # purge or take the record with it.
    asset_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    share_link_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    # Copied at signing, so the record still reads correctly after a rename.
    asset_name: Mapped[str] = mapped_column(String(255), nullable=False)
    version_number: Mapped[int] = mapped_column(nullable=False)
    signer_name: Mapped[str] = mapped_column(String(255), nullable=False)
    signer_email: Mapped[str] = mapped_column(String(255), nullable=False)
    # The exact words the signer ticked.
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    ip_address: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    reopened_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    reopened_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    reopen_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
