import re
import uuid
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field, field_validator

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class SignOffCreate(BaseModel):
    """What a client submits on a share link to sign a video off."""
    name: str = Field(min_length=2, max_length=255)
    email: str = Field(min_length=3, max_length=255)
    # The tick box. Signing without it is refused rather than assumed.
    agree: bool
    # The version on screen when they signed. Omitted, the latest ready version.
    version_id: Optional[uuid.UUID] = None

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 2:
            raise ValueError("Enter your full name")
        return v

    @field_validator("email")
    @classmethod
    def _email_shape(cls, v: str) -> str:
        v = v.strip()
        if not _EMAIL.match(v):
            raise ValueError("Enter a valid email address")
        return v


class ShareSignOffStatus(BaseModel):
    """What a share page shows about an asset's sign-off. No email address:
    anyone with the link can read this."""
    # Whether this link asks for a sign-off at all.
    required: bool
    signed_off: bool
    signer_name: Optional[str] = None
    signed_at: Optional[datetime] = None
    version_number: Optional[int] = None
    # The words the next signer will be agreeing to (or the ones already agreed).
    statement: Optional[str] = None


class SignOffRecord(BaseModel):
    """The full record, for project members."""
    id: uuid.UUID
    asset_id: uuid.UUID
    version_id: uuid.UUID
    version_number: int
    asset_name: str
    signer_name: str
    signer_email: str
    # Set when they signed while signed in to the client portal.
    signer_user_id: Optional[uuid.UUID] = None
    statement: str
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    created_at: datetime
    reopened_at: Optional[datetime] = None
    reopened_by: Optional[uuid.UUID] = None
    reopen_reason: Optional[str] = None
    model_config = {"from_attributes": True}


class AssetSignOffState(BaseModel):
    """An asset's sign-off state for the team: the one in force, and the history."""
    signed_off: bool
    current: Optional[SignOffRecord] = None
    history: list[SignOffRecord] = []


class SignOffReopen(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=1000)
