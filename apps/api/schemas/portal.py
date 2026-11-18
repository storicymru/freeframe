import re
import uuid
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field, field_validator

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class ClientInvite(BaseModel):
    """A person at the client, invited to a project's portal."""
    name: str = Field(min_length=2, max_length=255)
    email: str = Field(min_length=3, max_length=255)

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 2:
            raise ValueError("Enter their name")
        return v

    @field_validator("email")
    @classmethod
    def _email_shape(cls, v: str) -> str:
        # Stored lowercase, like every other new account.
        v = v.strip().lower()
        if not _EMAIL.match(v):
            raise ValueError("Enter a valid email address")
        return v


class ProjectClientResponse(BaseModel):
    user_id: uuid.UUID
    name: str
    email: str
    # False until they have opened the portal for the first time.
    has_signed_in: bool
    invited_at: Optional[datetime] = None
    # The one-time sign-in link, while it is still usable: for the team to
    # copy and send themselves. Never returned to a client.
    portal_link: Optional[str] = None


class ClientLinkExchange(BaseModel):
    token: str = Field(min_length=10, max_length=200)


class PortalAsset(BaseModel):
    id: uuid.UUID
    name: str
    asset_type: str
    status: str
    thumbnail_url: Optional[str] = None
    duration_seconds: Optional[float] = None
    version_number: Optional[int] = None
    updated_at: Optional[datetime] = None
    comment_count: int = 0
    signed_off_by: Optional[str] = None
    signed_off_at: Optional[datetime] = None


class PortalProject(BaseModel):
    """One client's library: a project, as its client sees it."""
    id: uuid.UUID
    name: str
    # The portal link's token: what the review screen and downloads run on.
    token: str
    needs_review: list[PortalAsset] = []
    delivered: list[PortalAsset] = []
    archive: list[PortalAsset] = []


class PortalHome(BaseModel):
    viewer_name: str
    viewer_email: str
    projects: list[PortalProject] = []
