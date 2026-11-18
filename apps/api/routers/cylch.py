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

Cylch is also where the team is kept. There is one list of staff, Cylch's, and
this app follows it:

  * `PUT /people` is that list. Everyone on it has an account here with the
    organisation role Cylch gives them; anyone who held an organisation role
    here and is no longer on it is deactivated at once, which ends their
    sessions. That is what happens when someone leaves.
  * `POST /sign-in` lets a person who is signed in to Cylch into this app: it
    answers with a one-time address, good for a minute, that their browser
    opens. Nobody on the team needs a second password.

Both make the key as strong as an administrator's sign-in, which is the point of
Cylch being the one place the team is managed: whoever holds the key decides
who is on the team. Client accounts are outside all of this. They are never
created, changed, signed in or deactivated by Cylch; clients sign in here.
"""
import hashlib
import hmac
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func
from sqlalchemy.orm import Session
from urllib.parse import quote

from ..database import get_db
from ..middleware.rate_limit import rate_limit
from ..models.instance_settings import InstanceSettings
from ..models.project import Project, ProjectMember, ProjectRole, ProjectType
from ..models.user import OrgRole, User, UserStatus
from ..routers.branding import _get_or_create_branding
from ..routers.instance_settings import get_or_create_instance_settings
from ..routers.users import require_admin
from ..schemas.branding import _validate_hex_color
from ..services import s3_service
from ..services.owned_keys import is_project_logo_key, project_logo_prefix
from ..config import settings
from ..schemas.auth import TokenResponse
from ..services.auth_service import create_access_token, create_refresh_token, get_user_by_id
from ..services.redis_service import store_cylch_ticket, take_cylch_ticket

router = APIRouter(prefix="/integrations/cylch", tags=["cylch"])
# What a browser needs for "Sign in with Cylch". No key and no session: the
# one-time ticket is the credential.
auth_router = APIRouter(prefix="/auth/cylch", tags=["cylch"])

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


# ── The team: Cylch's list, and signing in with it ───────────────────────────

class CylchPerson(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    name: str = Field(min_length=1, max_length=255)
    org_role: OrgRole

    @field_validator("email", mode="before")
    @classmethod
    def tidy_email(cls, v):
        v = str(v or "").strip().lower()
        if "@" not in v or " " in v:
            raise ValueError("Not an email address")
        return v


class CylchPeople(BaseModel):
    people: list[CylchPerson] = Field(max_length=500)


class CylchPeopleResult(BaseModel):
    added: int = 0
    updated: int = 0
    reactivated: int = 0
    deactivated: int = 0
    # Addresses on the list that belong to client accounts here, left alone.
    clients_skipped: list[str] = []


class CylchSignIn(CylchPerson):
    # Where in this app to land, e.g. "/projects/<id>". A path here, never an address.
    next: Optional[str] = Field(default=None, max_length=500)


class CylchSignInTicket(BaseModel):
    url: str
    expires_in: int


class CylchHome(BaseModel):
    url: Optional[str] = Field(default=None, max_length=255)

    @field_validator("url", mode="before")
    @classmethod
    def an_address(cls, v):
        if v is None or str(v).strip() == "":
            return None
        v = str(v).strip().rstrip("/")
        local = v.startswith("http://localhost") or v.startswith("http://127.0.0.1")
        if not (v.startswith("https://") or local) or any(c in v for c in " \"'<>"):
            raise ValueError("Cylch's address has to start with https://")
        return v


def _safe_next(path: Optional[str]) -> str:
    """A path inside this app, or the projects list. Never somewhere else."""
    if not path or not path.startswith("/") or path.startswith("//") or "\\" in path or "\n" in path:
        return "/projects"
    return path


def _follow(db: Session, person: CylchPerson, result: CylchPeopleResult) -> Optional[User]:
    """Make this app's account for one person on Cylch's list match the list.
    None for an address that is a client's here: those are not Cylch's."""
    # A deleted account still holds its address, so it is found too and brought back.
    user = db.query(User).filter(func.lower(User.email) == person.email).first()
    if isinstance(user, User) and user.is_client is not False:
        result.clients_skipped.append(person.email)
        return None
    is_admin = person.org_role == OrgRole.admin
    if not isinstance(user, User):
        user = User(email=person.email, name=person.name.strip(), status=UserStatus.active,
                    email_verified=True, org_role=person.org_role, is_superadmin=is_admin)
        db.add(user)
        db.flush()
        result.added += 1
        return user
    changed = False
    if user.deleted_at is not None:
        user.deleted_at = None
        user.status = UserStatus.deactivated  # counted as a reactivation just below
    if user.status != UserStatus.active:
        user.status = UserStatus.active
        user.invite_token = None
        user.invite_token_expires_at = None
        result.reactivated += 1
    if user.org_role != person.org_role or user.is_superadmin is not is_admin:
        user.org_role = person.org_role
        user.is_superadmin = is_admin
        changed = True
    if changed:
        result.updated += 1
    return user


@router.put("/home", status_code=status.HTTP_204_NO_CONTENT, dependencies=[_limited])
def set_cylch_home(body: CylchHome, db: Session = Depends(get_db),
                   settings_row: InstanceSettings = Depends(require_cylch_key)):
    """Cylch says where it lives, so the sign-in page can send people there.
    Null takes the "Sign in with Cylch" button away again."""
    settings_row.cylch_url = body.url
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/people", response_model=CylchPeopleResult, dependencies=[_limited])
def set_people(body: CylchPeople, db: Session = Depends(get_db),
               _: InstanceSettings = Depends(require_cylch_key)):
    """The whole team, as Cylch has it. Anyone here with an organisation role
    who is not on the list is deactivated: that is someone who has left."""
    if not any(p.org_role == OrgRole.admin for p in body.people):
        # An empty or admin-less list would lock everyone out of this app's
        # settings, and is far more likely a fault in the sender than a decision.
        raise HTTPException(status_code=422, detail="The list has no administrator on it, so nothing was changed")
    result = CylchPeopleResult()
    on_list = {p.email for p in body.people}
    for person in body.people:
        _follow(db, person, result)
    team = db.query(User).filter(User.org_role.isnot(None), User.deleted_at.is_(None)).all()
    for user in team:
        if user.is_client is not False or (user.email or "").lower() in on_list:
            continue
        if user.status != UserStatus.deactivated:
            user.status = UserStatus.deactivated
            user.invite_token = None
            user.invite_token_expires_at = None
            # Deactivated accounts are refused already; this also ends any
            # session that outlives a later reactivation.
            user.token_version = (user.token_version or 1) + 1
            result.deactivated += 1
        user.is_superadmin = False
    db.commit()
    return result


@router.post("/sign-in", response_model=CylchSignInTicket, dependencies=[_limited])
def start_sign_in(body: CylchSignIn, db: Session = Depends(get_db),
                  _: InstanceSettings = Depends(require_cylch_key)):
    """A one-time address that signs this person in here. Cylch asks only for
    someone who is signed in to Cylch at that moment, and sends their browser
    to the address straight away: it is good once, for a minute."""
    result = CylchPeopleResult()
    user = _follow(db, body, result)
    if user is None:
        raise HTTPException(status_code=409, detail="That address belongs to a client account here. Clients sign in to Adborth themselves.")
    db.commit()
    ticket = secrets.token_urlsafe(32)
    store_cylch_ticket(_hash(ticket), str(user.id))
    # In the fragment, which browsers do not send to servers or keep in referrers.
    url = f"{settings.frontend_url.rstrip('/')}/auth/cylch?next={quote(_safe_next(body.next), safe='/')}#ticket={ticket}"
    return CylchSignInTicket(url=url, expires_in=60)


class CylchSignInOffer(BaseModel):
    # Where "Sign in with Cylch" goes, or null when there is no such button.
    sign_in_url: Optional[str] = None


class CylchTicket(BaseModel):
    ticket: str = Field(min_length=20, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")


@auth_router.get("", response_model=CylchSignInOffer)
def sign_in_offer(db: Session = Depends(get_db)):
    row = db.query(InstanceSettings).first()
    url = getattr(row, "cylch_url", None)
    has_key = getattr(row, "cylch_key_hash", None)
    if not isinstance(url, str) or not url or not isinstance(has_key, str) or not has_key:
        return CylchSignInOffer()
    return CylchSignInOffer(sign_in_url=f"{url}/adborth/sign-in")


@auth_router.post("/exchange", response_model=TokenResponse,
                  dependencies=[Depends(rate_limit("cylch_ticket", 20, 60))])
def exchange_ticket(body: CylchTicket, db: Session = Depends(get_db)):
    """Swap a ticket for a session. One message for every refusal."""
    refused = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="That sign-in link has expired. Sign in from Cylch again.")
    stored = take_cylch_ticket(_hash(body.ticket))
    if isinstance(stored, bytes):
        stored = stored.decode("ascii", "ignore")
    if not isinstance(stored, str) or not stored:
        raise refused
    try:
        user = get_user_by_id(db, uuid.UUID(stored))
    except ValueError:
        raise refused
    if not user or user.status != UserStatus.active or user.is_client is not False:
        raise refused
    return TokenResponse(
        access_token=create_access_token(str(user.id), token_version=user.token_version),
        refresh_token=create_refresh_token(str(user.id), token_version=user.token_version),
        needs_password=False,
    )
