"""Cylch: the studio's project app, connected with a key.

Cylch is where a client's branding lives: their logo and one or two colours,
set once on the client. A Cylch project linked to a project here sends that
branding across, so a review page carries the client's logo without anyone
setting it twice. Cylch can also make the project here in the first place.

It connects with a key rather than an account. An administrator makes the key
in Settings and pastes it into Cylch; the key is shown once and only its
SHA-256 is stored. Making another replaces it, and removing it switches the
integration off. A key is narrower than an account by construction: it is
accepted on the routes in this file and nowhere else, so it can list projects,
make a project, and set a project's logo and colours. It cannot read footage,
comments or people, and it cannot delete anything but a logo it replaces.

The key is sent as `Authorization: Bearer adb_cylch_...`. It is not a session
token: `get_current_user` never sees it, so no other route can be reached
with it.
"""
import hashlib
import hmac
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from ..database import get_db
from ..middleware.rate_limit import rate_limit
from ..models.instance_settings import InstanceSettings
from ..models.project import Project, ProjectMember, ProjectRole, ProjectType
from ..models.user import User, UserStatus
from ..routers.branding import _get_or_create_branding
from ..routers.instance_settings import get_or_create_instance_settings
from ..routers.users import require_admin
from ..schemas.branding import _validate_hex_color
from ..services import s3_service
from ..services.owned_keys import is_project_logo_key, project_logo_prefix

router = APIRouter(prefix="/integrations/cylch", tags=["cylch"])

KEY_PREFIX = "adb_cylch_"
MAX_LOGO_BYTES = 2 * 1024 * 1024
# How often a use of the key is written down. Every request would be a write
# per request; this is enough to answer "is Cylch still talking to us?".
_USED_AT_EVERY = timedelta(minutes=1)


def _hash(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _image_kind(data: bytes) -> Optional[tuple[str, str]]:
    """(extension, content type) for the three picture types a logo may be,
    read from the bytes themselves: the Content-Type header is the sender's
    word, and this file is served back to browsers."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png", "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "jpg", "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp", "image/webp"
    return None


# ── The key itself: administrators only ──────────────────────────────────────

class CylchStatus(BaseModel):
    has_key: bool
    made_at: Optional[datetime] = None
    used_at: Optional[datetime] = None


class CylchKeyMade(CylchStatus):
    # The only time the key is ever sent. It is not stored and cannot be read back.
    key: str


def _status(row: InstanceSettings) -> CylchStatus:
    has = bool(row.cylch_key_hash)
    return CylchStatus(has_key=has, made_at=row.cylch_key_made_at if has else None,
                       used_at=row.cylch_key_used_at if has else None)


@router.get("", response_model=CylchStatus)
def cylch_status(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    return _status(get_or_create_instance_settings(db))


@router.post("/key", response_model=CylchKeyMade, status_code=status.HTTP_201_CREATED)
def make_cylch_key(db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    """Make a key, replacing any there was: the old one stops working at once."""
    row = get_or_create_instance_settings(db)
    key = KEY_PREFIX + secrets.token_urlsafe(32)
    row.cylch_key_hash = _hash(key)
    row.cylch_key_made_by = admin.id
    row.cylch_key_made_at = datetime.now(timezone.utc)
    row.cylch_key_used_at = None
    db.commit()
    return CylchKeyMade(has_key=True, made_at=row.cylch_key_made_at, used_at=None, key=key)


@router.delete("/key", status_code=status.HTTP_204_NO_CONTENT)
def remove_cylch_key(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    row = get_or_create_instance_settings(db)
    row.cylch_key_hash = None
    row.cylch_key_made_by = None
    row.cylch_key_made_at = None
    row.cylch_key_used_at = None
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── What the key opens ───────────────────────────────────────────────────────

def require_cylch_key(request: Request, db: Session = Depends(get_db)) -> InstanceSettings:
    """The settings row, for a request that carries the current key. 401 for
    anything else, with one message: a caller is not told whether there is a
    key at all."""
    refused = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not a valid Cylch key")
    header = request.headers.get("authorization") or ""
    scheme, _, given = header.partition(" ")
    given = given.strip()
    if scheme.lower() != "bearer" or not given.startswith(KEY_PREFIX):
        raise refused
    row = db.query(InstanceSettings).first()
    stored = getattr(row, "cylch_key_hash", None)
    if not isinstance(stored, str) or not stored or not hmac.compare_digest(stored, _hash(given)):
        raise refused
    now = datetime.now(timezone.utc)
    last = row.cylch_key_used_at
    if not isinstance(last, datetime) or now - last > _USED_AT_EVERY:
        row.cylch_key_used_at = now
        db.commit()
    return row


# Guessing a 256-bit key is not a real attack, but a loop that tries is noise
# worth stopping early. Generous enough for Cylch sending a client's branding
# to every project of theirs at once.
_limited = Depends(rate_limit("cylch_key", 240, 60))


def _live_project(db: Session, project_id: uuid.UUID) -> Project:
    project = db.query(Project).filter(Project.id == project_id, Project.deleted_at.is_(None)).first()
    if not isinstance(project, Project):
        raise HTTPException(status_code=404, detail="Project not found")
    return project


class CylchProject(BaseModel):
    id: uuid.UUID
    name: str


class CylchProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: Optional[str] = Field(default=None, max_length=2000)


class CylchBranding(BaseModel):
    """A partial update: a colour left out is unchanged, null or "" clears it."""
    primary_color: Optional[str] = None
    secondary_color: Optional[str] = None

    @field_validator("primary_color", "secondary_color", mode="before")
    @classmethod
    def hex_colour(cls, v):
        return _validate_hex_color(v)


class CylchBrandingState(BaseModel):
    project_id: uuid.UUID
    primary_color: Optional[str] = None
    secondary_color: Optional[str] = None
    has_logo: bool = False


def _state(branding) -> CylchBrandingState:
    return CylchBrandingState(
        project_id=branding.project_id, primary_color=branding.primary_color,
        secondary_color=branding.secondary_color,
        has_logo=is_project_logo_key(branding.project_id, branding.logo_s3_key),
    )


@router.get("/projects", response_model=list[CylchProject], dependencies=[_limited])
def list_projects(db: Session = Depends(get_db), _: InstanceSettings = Depends(require_cylch_key)):
    """Every live project, by name: what Cylch offers to link to."""
    rows = db.query(Project).filter(Project.deleted_at.is_(None)).order_by(Project.name).all()
    return [CylchProject(id=p.id, name=p.name) for p in rows]


@router.post("/projects", response_model=CylchProject, status_code=status.HTTP_201_CREATED, dependencies=[_limited])
def create_project(body: CylchProjectCreate, db: Session = Depends(get_db),
                   settings_row: InstanceSettings = Depends(require_cylch_key)):
    """Make a team project. A project needs an owner, and a key is not a
    person: it belongs to the administrator who made the key."""
    owner = db.query(User).filter(User.id == settings_row.cylch_key_made_by).first() if settings_row.cylch_key_made_by else None
    if not isinstance(owner, User) or owner.deleted_at is not None or owner.status == UserStatus.deactivated:
        raise HTTPException(status_code=409, detail="The person who made this key no longer has an account here. Make a new key in Settings.")
    project = Project(name=body.name.strip() or "Untitled", description=body.description,
                      project_type=ProjectType.team, created_by=owner.id)
    db.add(project)
    db.flush()
    db.add(ProjectMember(project_id=project.id, user_id=owner.id, role=ProjectRole.owner))
    db.commit()
    db.refresh(project)
    return CylchProject(id=project.id, name=project.name)


@router.put("/projects/{project_id}/branding", response_model=CylchBrandingState, dependencies=[_limited])
def set_branding(project_id: uuid.UUID, body: CylchBranding, db: Session = Depends(get_db),
                 _: InstanceSettings = Depends(require_cylch_key)):
    _live_project(db, project_id)
    branding = _get_or_create_branding(db, project_id)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(branding, field, value)
    db.commit()
    db.refresh(branding)
    return _state(branding)


@router.put("/projects/{project_id}/logo", response_model=CylchBrandingState, dependencies=[_limited])
async def set_logo(project_id: uuid.UUID, request: Request, db: Session = Depends(get_db),
                   _: InstanceSettings = Depends(require_cylch_key)):
    """The request body is the picture itself: a PNG, JPEG or WebP of up to
    2 MB. It replaces the project's logo, and share pages go back to showing a
    logo rather than the cover."""
    _live_project(db, project_id)
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_LOGO_BYTES:
        raise HTTPException(status_code=413, detail="A logo must be 2 MB or smaller")
    data = await request.body()
    if len(data) > MAX_LOGO_BYTES:
        raise HTTPException(status_code=413, detail="A logo must be 2 MB or smaller")
    kind = _image_kind(data)
    if kind is None:
        raise HTTPException(status_code=415, detail="A logo must be a PNG, JPEG or WebP picture")
    ext, content_type = kind
    branding = _get_or_create_branding(db, project_id)
    old = branding.logo_s3_key
    key = f"{project_logo_prefix(project_id)}{uuid.uuid4()}.{ext}"
    s3_service.put_object(key, data, content_type=content_type, cache_control="max-age=86400")
    branding.logo_s3_key = key
    branding.use_cover_as_logo = False
    db.commit()
    db.refresh(branding)
    # As in routers/branding.py: the old logo goes only once the row no longer
    # names it, and only if it is one this project's upload step issued.
    if old != key and is_project_logo_key(project_id, old):
        try:
            s3_service.delete_object(old)
        except Exception:
            pass
    return _state(branding)
