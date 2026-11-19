"""Managing a video's versions: tidy, delete one, release one, stack two videos.

Owner-only on the project (or an administrator). What each action does and
refuses is in `services/version_stack.py`; this file is the HTTP face of it.
"""
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import get_db
from ..middleware.auth import get_current_user
from ..models.asset import Asset
from ..models.project import ProjectRole
from ..models.user import User
from ..services import version_stack
from ..services.permissions import require_live_project, require_project_role

router = APIRouter(tags=["version-stack"])


class TidyRequest(BaseModel):
    # How many versions the person was told would go. A page that has moved on
    # cannot remove a different set than was confirmed.
    confirm_count: int = Field(ge=0)


class ProjectTidyRequest(TidyRequest):
    scope: str = "finished"


class ReleaseRequest(BaseModel):
    name: Optional[str] = Field(default=None, max_length=255)


class StackRequest(BaseModel):
    source_asset_id: uuid.UUID


def _may_manage(db: Session, project_id: uuid.UUID, user: User) -> None:
    """The project's owner, or an administrator. Editors add versions; taking
    them away or restructuring a video is the owner's call."""
    if user.is_superadmin is True:
        require_live_project(db, project_id)
        return
    require_project_role(db, project_id, user, ProjectRole.owner)


def _asset(db: Session, asset_id: uuid.UUID) -> Asset:
    asset = db.query(Asset).filter(Asset.id == asset_id, Asset.deleted_at.is_(None)).first()
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found")
    return asset


def _refuse(error: version_stack.StackError) -> HTTPException:
    return HTTPException(status_code=error.status_code, detail=error.detail)


@router.get("/assets/{asset_id}/versions/tidy")
def asset_tidy_plan(
    asset_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Every live version of the video with its size, and whether a tidy would
    keep or remove it. Reads only."""
    asset = _asset(db, asset_id)
    _may_manage(db, asset.project_id, current_user)
    return version_stack.tidy_plan(db, asset)


@router.post("/assets/{asset_id}/versions/tidy")
def tidy_asset_versions(
    asset_id: uuid.UUID,
    body: TidyRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Keep the latest version and move the rest to the trash."""
    asset = _asset(db, asset_id)
    _may_manage(db, asset.project_id, current_user)
    plan = version_stack.tidy_plan(db, asset)
    if plan["remove_count"] != body.confirm_count:
        raise HTTPException(status_code=409, detail="The versions changed since you looked. Check again and confirm.")
    result = version_stack.tidy_asset(db, asset, current_user)
    db.commit()
    return result


@router.delete("/assets/{asset_id}/versions/{version_id}")
def delete_asset_version(
    asset_id: uuid.UUID,
    version_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Move one version to the trash."""
    asset = _asset(db, asset_id)
    _may_manage(db, asset.project_id, current_user)
    try:
        result = version_stack.delete_version(db, asset, version_id, current_user)
    except version_stack.StackError as error:
        raise _refuse(error)
    db.commit()
    return result


@router.post("/assets/{asset_id}/versions/{version_id}/reprocess", status_code=202)
def reprocess_asset_version(
    asset_id: uuid.UUID,
    version_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Make a version's playback copies again from its stored master, with the
    quality list the instance has now. Nothing is uploaded."""
    asset = _asset(db, asset_id)
    _may_manage(db, asset.project_id, current_user)
    try:
        version = version_stack.reprocess_version(db, asset, version_id, current_user)
    except version_stack.StackError as error:
        raise _refuse(error)
    db.commit()
    # After the commit: the worker reads the request from the database.
    from ..tasks.celery_app import send_task_safe
    from ..tasks.transcode_tasks import process_asset
    send_task_safe(process_asset, str(asset.id), str(version.id))
    return {"version_id": version.id, "version_number": version.version_number, "reprocessing": True}


@router.post("/assets/{asset_id}/versions/{version_id}/release")
def release_asset_version(
    asset_id: uuid.UUID,
    version_id: uuid.UUID,
    body: ReleaseRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Take one version out of the stack as a video of its own."""
    asset = _asset(db, asset_id)
    _may_manage(db, asset.project_id, current_user)
    try:
        released = version_stack.release_version(db, asset, version_id, current_user, body.name)
    except version_stack.StackError as error:
        raise _refuse(error)
    db.commit()
    return {"asset_id": released.id, "name": released.name, "project_id": released.project_id}


@router.post("/assets/{asset_id}/stack")
def stack_onto_asset(
    asset_id: uuid.UUID,
    body: StackRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Put another video on top of this one, as its newest versions."""
    target = _asset(db, asset_id)
    _may_manage(db, target.project_id, current_user)
    source = db.query(Asset).filter(Asset.id == body.source_asset_id, Asset.deleted_at.is_(None)).first()
    if source is None:
        raise HTTPException(status_code=404, detail="The video to stack was not found")
    try:
        result = version_stack.stack_assets(db, target, source, current_user)
    except version_stack.StackError as error:
        raise _refuse(error)
    db.commit()
    return result


@router.get("/projects/{project_id}/versions/tidy")
def project_tidy_plan(
    project_id: uuid.UUID,
    scope: str = Query("finished", pattern="^(finished|all)$"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """What a tidy of the whole project would remove, video by video."""
    _may_manage(db, project_id, current_user)
    return version_stack.project_tidy_plan(db, project_id, scope)


@router.post("/projects/{project_id}/versions/tidy")
def tidy_project_versions(
    project_id: uuid.UUID,
    body: ProjectTidyRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Tidy every finished video in the project (or every video, with scope=all)."""
    _may_manage(db, project_id, current_user)
    try:
        plan = version_stack.project_tidy_plan(db, project_id, body.scope)
    except version_stack.StackError as error:
        raise _refuse(error)
    if plan["remove_count"] != body.confirm_count:
        raise HTTPException(status_code=409, detail="The versions changed since you looked. Check again and confirm.")
    result = version_stack.tidy_project(db, project_id, current_user, body.scope)
    db.commit()
    return result
