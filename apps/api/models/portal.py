import uuid
from datetime import datetime
from typing import Optional
from sqlalchemy import DateTime, func, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
try:
    from ..database import Base
except ImportError:
    from database import Base


class ProjectClient(Base):
    """A client account's access to one project through the client portal.

    Deliberately not a ProjectMember. Membership opens every project route;
    a client must reach nothing but the portal, so their access lives in its
    own table that only the portal reads. No foreign keys: a row pointing at a
    deleted project or user grants nothing (the portal joins to live rows), and
    the retention GC is not held up by it.
    """
    __tablename__ = "project_clients"
    __table_args__ = (UniqueConstraint("project_id", "user_id", name="uq_project_clients_project_user"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    invited_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
