"""Client portal.

A client signs in and sees their own library: what needs their review, what
has been delivered, and the archive, for each project they are a client of.
The team invites clients per project. Everything a client does to an asset
(watch, comment, sign off, download) runs on the project's portal link through
the share routes; this router adds only the home page and the invitations.
"""
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..middleware.auth import get_current_user
from ..middleware.rate_limit import rate_limit
from ..models.asset import Asset, AssetStatus, AssetVersion, ProcessingStatus
from ..models.portal import ProjectClient
from ..models.project import Project, ProjectRole
from ..models.sign_off import SignOff
from ..models.user import User, UserStatus
from ..schemas.auth import TokenResponse
from ..schemas.portal import (
    ClientInvite,
    ClientLinkExchange,
    PortalAsset,
    PortalHome,
    PortalProject,
    ProjectClientResponse,
)
from ..services.auth_service import create_access_token, create_refresh_token, get_email_owner
from ..services.permissions import folder_chain_is_live, require_project_role
from ..services.portal import (
    CLIENT_DELIVERED_STATUSES,
    CLIENT_VISIBLE_STATUSES,
    get_or_create_portal_link,
)
from ..services.s3_service import generate_presigned_get_url
from ..tasks.celery_app import send_task_safe
from ..tasks.email_tasks import send_client_portal_invite_email
from .share import _get_latest_media_file, _latest_version_comment_count

router = APIRouter(tags=["client-portal"])

CLIENT_LINK_DAYS = 7


def _new_client_link(user: User) -> None:
    user.invite_token = secrets.token_urlsafe(48)
    user.invite_token_expires_at = datetime.now(timezone.utc) + timedelta(days=CLIENT_LINK_DAYS)


def _client_link_url(user: User) -> str:
    return f"{settings.frontend_url}/portal/enter/{user.invite_token}"


def _client_response(user: User, row: ProjectClient) -> ProjectClientResponse:
    link_live = bool(
        user.invite_token
        and (user.invite_token_expires_at is None or user.invite_token_expires_at > datetime.now(timezone.utc))
    )
    return ProjectClientResponse(
        user_id=user.id,
        name=user.name,
        email=user.email,
        has_signed_in=bool(user.email_verified),
        invited_at=row.created_at,
        portal_link=_client_link_url(user) if link_live else None,
    )


def _send_invite(user: User, inviter: User, project: Project) -> None:
    send_task_safe(
        send_client_portal_invite_email,
        to_email=user.email,
        client_name=user.name,
        inviter_name=inviter.name or "The team",
        project_name=project.name,
        portal_link=_client_link_url(user),
        expiry_days=CLIENT_LINK_DAYS,
    )


def _live_project(db: Session, project_id: uuid.UUID) -> Project:
    project = db.query(Project).filter(Project.id == project_id, Project.deleted_at.is_(None)).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


# ── Team side: who the project's clients are ──────────────────────────────────

@router.get("/projects/{project_id}/clients", response_model=list[ProjectClientResponse])
def list_project_clients(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_project_role(db, project_id, current_user, ProjectRole.editor)
    rows = (
        db.query(ProjectClient, User)
        .join(User, User.id == ProjectClient.user_id)
        .filter(ProjectClient.project_id == project_id, User.deleted_at.is_(None))
        .order_by(ProjectClient.created_at)
        .all()
    )
    return [_client_response(user, row) for row, user in rows]


@router.post("/projects/{project_id}/clients", response_model=ProjectClientResponse, status_code=status.HTTP_201_CREATED)
def invite_project_client(
    project_id: uuid.UUID,
    body: ClientInvite,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Invite a person at the client to this project's portal. Makes their
    client account if they have none, and emails them a link that signs them in."""
    require_project_role(db, project_id, current_user, ProjectRole.editor)
    project = _live_project(db, project_id)

    user = get_email_owner(db, body.email)
    if user is not None and user.deleted_at is not None:
        raise HTTPException(status_code=400, detail="This email belonged to a deleted user and can't be invited again")
    if user is not None and user.is_client is not True:
        # A team account sees projects through membership, not the portal.
        raise HTTPException(status_code=400, detail="This email belongs to a team account. Add them as a project member instead.")
    if user is not None and user.status == UserStatus.deactivated:
        raise HTTPException(status_code=400, detail="This client account has been deactivated")

    if user is None:
        user = User(
            email=body.email,
            name=body.name,
            # Active from the start: a client never sets a password, they sign
            # in by this link and afterwards by emailed code.
            status=UserStatus.active,
            is_client=True,
        )
        db.add(user)
        db.flush()

    existing = db.query(ProjectClient).filter(
        ProjectClient.project_id == project_id, ProjectClient.user_id == user.id,
    ).first()
    if isinstance(existing, ProjectClient):
        raise HTTPException(status_code=409, detail="They are already a client of this project")

    row = ProjectClient(project_id=project_id, user_id=user.id, invited_by=current_user.id)
    db.add(row)
    get_or_create_portal_link(db, project, current_user.id)
    _new_client_link(user)
    db.commit()
    db.refresh(user)
    db.refresh(row)

    _send_invite(user, current_user, project)
    return _client_response(user, row)


@router.post("/projects/{project_id}/clients/{user_id}/resend", response_model=ProjectClientResponse)
def resend_client_invite(
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Email the client a fresh sign-in link. The new link replaces the old one."""
    require_project_role(db, project_id, current_user, ProjectRole.editor)
    project = _live_project(db, project_id)
    found = (
        db.query(ProjectClient, User)
        .join(User, User.id == ProjectClient.user_id)
        .filter(ProjectClient.project_id == project_id, ProjectClient.user_id == user_id, User.deleted_at.is_(None))
        .first()
    )
    if not found:
        raise HTTPException(status_code=404, detail="Client not found on this project")
    row, user = found
    _new_client_link(user)
    db.commit()
    db.refresh(user)
    _send_invite(user, current_user, project)
    return _client_response(user, row)


@router.delete("/projects/{project_id}/clients/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_project_client(
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Take a client off this project. Their account, comments and sign-offs stay."""
    require_project_role(db, project_id, current_user, ProjectRole.editor)
    row = db.query(ProjectClient).filter(
        ProjectClient.project_id == project_id, ProjectClient.user_id == user_id,
    ).first()
    if not isinstance(row, ProjectClient):
        raise HTTPException(status_code=404, detail="Client not found on this project")
    db.delete(row)
    db.commit()


# ── Client side ───────────────────────────────────────────────────────────────

@router.post(
    "/auth/client-link",
    response_model=TokenResponse,
    dependencies=[Depends(rate_limit("client_link", 10, 600))],
)
def exchange_client_link(body: ClientLinkExchange, db: Session = Depends(get_db)):
    """Sign a client in with the one-time link from their invitation.

    Used once, then gone: a link that is forwarded or found later signs nobody
    in, and they are sent to sign in by emailed code instead.
    """
    user = db.query(User).filter(User.invite_token == body.token, User.deleted_at.is_(None)).first()
    if (
        not user
        or user.is_client is not True
        or user.status == UserStatus.deactivated
        or (user.invite_token_expires_at and user.invite_token_expires_at < datetime.now(timezone.utc))
    ):
        raise HTTPException(status_code=404, detail="This link has been used or has expired")

    user.invite_token = None
    user.invite_token_expires_at = None
    user.email_verified = True  # the link reached their mailbox
    user.status = UserStatus.active
    db.commit()

    return TokenResponse(
        access_token=create_access_token(str(user.id), token_version=user.token_version),
        refresh_token=create_refresh_token(str(user.id), token_version=user.token_version),
        needs_password=False,
    )


def _portal_asset(db: Session, asset: Asset, sign_offs: dict) -> PortalAsset:
    media = _get_latest_media_file(db, asset.id)
    version_number = None
    if media is not None and media.version_id:
        version = db.query(AssetVersion).filter(AssetVersion.id == media.version_id).first()
        version_number = version.version_number if version else None
    signed = sign_offs.get(asset.id)
    return PortalAsset(
        id=asset.id,
        name=asset.name,
        asset_type=asset.asset_type.value if hasattr(asset.asset_type, "value") else str(asset.asset_type),
        status=asset.status.value if hasattr(asset.status, "value") else str(asset.status),
        thumbnail_url=generate_presigned_get_url(media.s3_key_thumbnail) if media is not None and media.s3_key_thumbnail else None,
        duration_seconds=media.duration_seconds if media is not None else None,
        version_number=version_number,
        updated_at=asset.updated_at,
        comment_count=_latest_version_comment_count(db, asset.id),
        signed_off_by=signed.signer_name if signed else None,
        signed_off_at=signed.created_at if signed else None,
    )


@router.get("/portal", response_model=PortalHome)
def portal_home(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """A client's library: for each project they are a client of, what needs
    their review, what has been delivered, and the archive."""
    if current_user.is_client is not True:
        raise HTTPException(status_code=403, detail="The client portal is for client accounts")

    projects = (
        db.query(Project)
        .join(ProjectClient, ProjectClient.project_id == Project.id)
        .filter(ProjectClient.user_id == current_user.id, Project.deleted_at.is_(None))
        .order_by(Project.name)
        .all()
    )

    out: list[PortalProject] = []
    for project in projects:
        link = get_or_create_portal_link(db, project, project.created_by)
        assets = (
            db.query(Asset)
            .filter(
                Asset.project_id == project.id,
                Asset.deleted_at.is_(None),
                Asset.status.in_(CLIENT_VISIBLE_STATUSES),
            )
            .order_by(Asset.updated_at.desc())
            .all()
        )
        # An asset under a trashed folder is trashed too.
        assets = [a for a in assets if not a.folder_id or folder_chain_is_live(db, a.folder_id)]
        # Only what has a version ready to play is worth showing a client.
        ready_ids = {
            row[0] for row in db.query(AssetVersion.asset_id).filter(
                AssetVersion.asset_id.in_([a.id for a in assets] or [uuid.uuid4()]),
                AssetVersion.deleted_at.is_(None),
                AssetVersion.processing_status == ProcessingStatus.ready,
            ).distinct().all()
        }
        assets = [a for a in assets if a.id in ready_ids]

        sign_offs = {
            s.asset_id: s for s in db.query(SignOff).filter(
                SignOff.asset_id.in_([a.id for a in assets] or [uuid.uuid4()]),
                SignOff.reopened_at.is_(None),
            ).all()
        }

        section = PortalProject(id=project.id, name=project.name, token=link.token)
        for asset in assets:
            card = _portal_asset(db, asset, sign_offs)
            if asset.status == AssetStatus.archived:
                section.archive.append(card)
            elif asset.status in CLIENT_DELIVERED_STATUSES:
                section.delivered.append(card)
            else:
                section.needs_review.append(card)
        out.append(section)
    db.commit()  # a portal link made on first visit

    return PortalHome(viewer_name=current_user.name, viewer_email=current_user.email, projects=out)
