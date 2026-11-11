"""Client sign-off.

A client on a share link that asks for it signs a video off: name, email and a
tick against a fixed statement. That records who agreed to what and when,
locks the asset (no new versions or comments), turns the link's downloads on
for it, and emails the client and the team. A project admin can reopen it.
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..middleware.auth import get_current_user, get_optional_user
from ..middleware.rate_limit import rate_limit
from ..models.activity import ActivityAction, ActivityLog, Notification, NotificationType
from ..models.asset import Asset, AssetStatus, AssetVersion, ProcessingStatus
from ..models.project import ProjectRole
from ..models.share import ShareActivityAction, ShareLink, ShareLinkActivity
from ..models.sign_off import SignOff
from ..models.user import User
from ..schemas.sign_off import (
    AssetSignOffState,
    ShareSignOffStatus,
    SignOffCreate,
    SignOffRecord,
    SignOffReopen,
)
from ..services import event_service
from ..services.permissions import (
    require_asset_access,
    require_project_role,
    validate_asset_in_share,
    validate_share_link_with_session,
)
from ..services.sign_off import active_sign_off, sign_off_statement
from ..tasks.celery_app import send_task_safe
from ..tasks.email_tasks import send_sign_off_confirmation_email, send_sign_off_team_email

router = APIRouter(tags=["sign-off"])


def _get_asset(db: Session, asset_id: uuid.UUID) -> Asset:
    asset = db.query(Asset).filter(Asset.id == asset_id, Asset.deleted_at.is_(None)).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    return asset


def _version_to_sign(db: Session, link: ShareLink, asset: Asset, version_id: Optional[uuid.UUID]) -> AssetVersion:
    """The version a signature applies to: the one named, when the link shows
    versions and it is a ready version of this asset; otherwise the latest
    ready one, which is what the page plays."""
    ready = db.query(AssetVersion).filter(
        AssetVersion.asset_id == asset.id,
        AssetVersion.deleted_at.is_(None),
        AssetVersion.processing_status == ProcessingStatus.ready,
    )
    version = None
    if version_id is not None and link.show_versions:
        version = ready.filter(AssetVersion.id == version_id).first()
    if version is None:
        version = ready.order_by(AssetVersion.version_number.desc()).first()
    if version is None:
        raise HTTPException(status_code=404, detail="Nothing is ready to sign off yet")
    return version


def _client_ip(request: Request) -> Optional[str]:
    # X-Real-IP is set by the reverse proxy; see middleware/rate_limit.py.
    ip = request.headers.get("x-real-ip") or (request.client.host if request.client else None)
    return ip[:64] if ip else None


def _share_status(db: Session, link: ShareLink, asset: Asset, version: Optional[AssetVersion]) -> ShareSignOffStatus:
    current = active_sign_off(db, asset.id)
    if current is not None:
        return ShareSignOffStatus(
            required=link.require_sign_off is True,
            signed_off=True,
            signer_name=current.signer_name,
            signed_at=current.created_at,
            version_number=current.version_number,
            statement=current.statement,
        )
    return ShareSignOffStatus(
        required=link.require_sign_off is True,
        signed_off=False,
        version_number=version.version_number if version else None,
        statement=sign_off_statement(asset.name, version.version_number) if version else None,
    )


# ── Client side: on a share link ──────────────────────────────────────────────

@router.get("/share/{token}/sign-off/{asset_id}", response_model=ShareSignOffStatus)
def get_share_sign_off(
    token: str,
    asset_id: uuid.UUID,
    version_id: Optional[uuid.UUID] = Query(default=None),
    share_session: Optional[str] = Query(None, alias="share_session"),
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_user),
):
    """Public endpoint — optional auth. Whether this asset is signed off, and
    the statement a signer agrees to."""
    link = validate_share_link_with_session(db, token, share_session=share_session, current_user=current_user)
    asset = _get_asset(db, asset_id)
    validate_asset_in_share(db, link, asset)
    try:
        version = _version_to_sign(db, link, asset, version_id)
    except HTTPException:
        version = None
    return _share_status(db, link, asset, version)


@router.post(
    "/share/{token}/sign-off/{asset_id}",
    response_model=ShareSignOffStatus,
    status_code=201,
    # No sign-in, and each call can send two emails.
    dependencies=[Depends(rate_limit("share_sign_off", 5, 600))],
)
def sign_off_asset(
    token: str,
    asset_id: uuid.UUID,
    body: SignOffCreate,
    request: Request,
    share_session: Optional[str] = Query(None, alias="share_session"),
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_user),
):
    """Public endpoint — optional auth. Sign an asset off on a share link."""
    link = validate_share_link_with_session(db, token, share_session=share_session, current_user=current_user)
    if link.require_sign_off is not True:
        raise HTTPException(status_code=403, detail="This share link does not ask for a sign-off")
    if not body.agree:
        raise HTTPException(status_code=400, detail="Tick the box to confirm you approve this version")

    asset = _get_asset(db, asset_id)
    validate_asset_in_share(db, link, asset)

    if active_sign_off(db, asset.id) is not None:
        raise HTTPException(status_code=409, detail="This has already been signed off")

    version = _version_to_sign(db, link, asset, body.version_id)
    statement = sign_off_statement(asset.name, version.version_number)

    record = SignOff(
        asset_id=asset.id,
        version_id=version.id,
        share_link_id=link.id,
        asset_name=asset.name,
        version_number=version.version_number,
        signer_name=body.name,
        signer_email=body.email,
        statement=statement,
        ip_address=_client_ip(request),
        user_agent=(request.headers.get("user-agent") or "")[:500] or None,
    )
    db.add(record)
    asset.status = AssetStatus.approved
    db.add(ShareLinkActivity(
        share_link_id=link.id,
        action=ShareActivityAction.approved,
        actor_email=body.email,
        actor_name=body.name,
        asset_id=asset.id,
        asset_name=asset.name,
    ))

    # Tell the people who shared and made it. In-app for both, by email too.
    team_ids = {link.created_by, asset.created_by}
    for user_id in team_ids:
        db.add(Notification(user_id=user_id, type=NotificationType.approval, asset_id=asset.id))
    db.commit()
    db.refresh(record)

    share_url = f"{settings.frontend_url}/share/{link.token}"
    signed_at = (record.created_at or datetime.now(timezone.utc)).strftime("%d %B %Y at %H:%M UTC")
    send_task_safe(
        send_sign_off_confirmation_email,
        to_email=body.email,
        signer_name=body.name,
        asset_name=asset.name,
        version_number=version.version_number,
        statement=statement,
        signed_at=signed_at,
        share_url=share_url,
    )
    asset_link = f"{settings.frontend_url}/projects/{asset.project_id}/assets/{asset.id}"
    for member in db.query(User).filter(User.id.in_(team_ids)).all():
        send_task_safe(
            send_sign_off_team_email,
            to_email=member.email,
            signer_name=body.name,
            signer_email=body.email,
            asset_name=asset.name,
            version_number=version.version_number,
            signed_at=signed_at,
            asset_link=asset_link,
        )

    event_service.publish_sync(asset.project_id, "sign_off_updated", {
        "asset_id": str(asset.id),
        "signed_off": True,
    })

    return _share_status(db, link, asset, version)


# ── Team side ─────────────────────────────────────────────────────────────────

@router.get("/assets/{asset_id}/sign-off", response_model=AssetSignOffState)
def get_asset_sign_off(
    asset_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """The asset's sign-off in force, and every one before it."""
    asset = _get_asset(db, asset_id)
    require_asset_access(db, asset, current_user)
    records = (
        db.query(SignOff)
        .filter(SignOff.asset_id == asset.id)
        .order_by(SignOff.created_at.desc())
        .all()
    )
    current = next((r for r in records if r.reopened_at is None), None)
    return AssetSignOffState(
        signed_off=current is not None,
        current=SignOffRecord.model_validate(current) if current else None,
        history=[SignOffRecord.model_validate(r) for r in records],
    )


@router.post("/assets/{asset_id}/sign-off/reopen", response_model=AssetSignOffState)
def reopen_asset(
    asset_id: uuid.UUID,
    body: SignOffReopen,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Unlock a signed-off asset. The project's owner or an instance admin
    only. The sign-off record is kept, marked with who reopened it and why."""
    asset = _get_asset(db, asset_id)
    if not current_user.is_superadmin:
        require_project_role(db, asset.project_id, current_user, ProjectRole.owner)

    current = active_sign_off(db, asset.id)
    if current is None:
        raise HTTPException(status_code=409, detail="This is not signed off")

    current.reopened_at = datetime.now(timezone.utc)
    current.reopened_by = current_user.id
    current.reopen_reason = (body.reason or "").strip() or None
    asset.status = AssetStatus.in_review
    db.add(ActivityLog(user_id=current_user.id, asset_id=asset.id, action=ActivityAction.rejected))
    db.commit()

    event_service.publish_sync(asset.project_id, "sign_off_updated", {
        "asset_id": str(asset.id),
        "signed_off": False,
    })

    return get_asset_sign_off(asset_id, db, current_user)
