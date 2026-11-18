"""Client portal: the rules every route shares.

A client account (User.is_client) sees the projects it has a ProjectClient row
for, and in them only the assets the team has put in front of the client:
anything past `draft`. Everything a client does to an asset goes through the
project's portal link, a share link flagged `is_portal`, so the portal inherits
the share stack's rules (public comments only, sign-off, download release)
instead of restating them.
"""
import secrets
import uuid
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from ..models.asset import Asset, AssetStatus
from ..models.portal import ProjectClient
from ..models.project import Project
from ..models.share import ShareLink, SharePermission
from ..models.user import User

# What a client may see. `draft` is the team's own working state.
CLIENT_VISIBLE_STATUSES = (
    AssetStatus.in_review, AssetStatus.rejected, AssetStatus.approved, AssetStatus.archived,
)
# Delivered work: released for download whether or not it was signed off here.
CLIENT_DELIVERED_STATUSES = (AssetStatus.approved, AssetStatus.archived)

# The only API a client account may call. Everything else answers 403 before
# its own checks run, so a route added later is closed to clients by default.
CLIENT_ALLOWED_ROOTS = ("/auth", "/portal", "/share", "/stream", "/instance/branding", "/health")


def client_may_call(path: str) -> bool:
    # A root or something under it: "/portal" and "/portal/x", never "/portalx".
    return any(path == root or path.startswith(root + "/") for root in CLIENT_ALLOWED_ROOTS)


def is_portal_link(link: ShareLink) -> bool:
    return getattr(link, "is_portal", False) is True


def is_project_client(db: Session, project_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    row = db.query(ProjectClient).filter(
        ProjectClient.project_id == project_id, ProjectClient.user_id == user_id,
    ).first()
    return isinstance(row, ProjectClient)


def require_portal_access(db: Session, link: ShareLink, user: Optional[User]) -> None:
    """Who may open a project's portal link: its clients, and its members (so
    the team can look at what the client sees). Nobody else, signed in or not."""
    from .permissions import effective_member  # local: permissions imports this module

    if user is None:
        raise HTTPException(status_code=403, detail="Sign in to open the client portal")
    if is_project_client(db, link.project_id, user.id):
        return
    if effective_member(db, link.project_id, user):
        return
    raise HTTPException(status_code=403, detail="You do not have access to this client portal")


def require_client_visible(asset: Asset) -> None:
    """A portal link reaches only what the team has put in front of the client.
    A draft answers as if it were not there."""
    if asset.status not in CLIENT_VISIBLE_STATUSES:
        raise HTTPException(status_code=404, detail="Asset not found")


def portal_releases_download(link: ShareLink, asset: Asset) -> bool:
    """Delivered work downloads from the portal with or without a sign-off made
    here: finished videos from before the portal, and anything the team marks
    delivered, belong in the client's library too."""
    return is_portal_link(link) and asset.status in CLIENT_DELIVERED_STATUSES


def get_or_create_portal_link(db: Session, project: Project, created_by: uuid.UUID) -> ShareLink:
    """The project's one portal link. Secure (sign-in required), comments on,
    sign-off required: the client reviews and signs off through it."""
    link = db.query(ShareLink).filter(
        ShareLink.project_id == project.id,
        ShareLink.is_portal.is_(True),
        ShareLink.deleted_at.is_(None),
    ).first()
    if isinstance(link, ShareLink):
        return link
    link = ShareLink(
        project_id=project.id,
        token=secrets.token_urlsafe(32),
        created_by=created_by,
        title=f"{project.name} client portal",
        permission=SharePermission.comment,
        visibility="secure",
        allow_download=False,
        require_sign_off=True,
        show_versions=False,
        show_watermark=False,
        is_portal=True,
        is_enabled=True,
        appearance={"layout": "grid", "theme": "dark", "accent_color": None, "open_in_viewer": True, "sort_by": "created_at"},
    )
    db.add(link)
    db.flush()
    return link


def notify_clients_ready_for_review(db: Session, asset: Asset, sender: User) -> int:
    """Email the project's clients that a video is waiting for them in the
    portal. Returns how many were told. Never raises: a mail problem must not
    undo the status change that triggered it."""
    from ..config import settings
    from ..tasks.celery_app import send_task_safe
    from ..tasks.email_tasks import send_client_review_ready_email

    try:
        clients = (
            db.query(User)
            .join(ProjectClient, ProjectClient.user_id == User.id)
            .filter(
                ProjectClient.project_id == asset.project_id,
                User.deleted_at.is_(None),
                User.is_client.is_(True),
            )
            .all()
        )
        project = db.query(Project).filter(Project.id == asset.project_id).first()
        told = 0
        for client in clients:
            if not isinstance(client, User) or getattr(client.status, "value", client.status) == "deactivated":
                continue
            send_task_safe(
                send_client_review_ready_email,
                to_email=client.email,
                client_name=client.name,
                sender_name=sender.name or "The team",
                asset_name=asset.name,
                project_name=project.name if project else "",
                review_link=f"{settings.frontend_url}/portal/review/{asset.id}",
            )
            told += 1
        return told
    except Exception:
        return 0

