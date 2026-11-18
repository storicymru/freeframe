"""Managing the versions of a video: tidy, delete, release and stack.

A video (an asset) is a stack of versions. Every round of review adds one, and
each carries its own upload and its own transcode, so a finished job can hold
many times the storage of what was delivered. This is the housekeeping:

* **tidy**: keep the version people see and drop the rest,
* **delete** one version,
* **release** a version into a video of its own, and
* **stack** one video onto another, as its newest versions.

Removing is always a soft delete: the version goes to the trash, where an
administrator can restore it, and its storage is freed when the trash is
emptied or the retention window passes. Nothing here deletes an object.

A version a client has signed off is never removed, whatever its position, and
a signed-off video is not restructured until it is reopened: the record of what
was approved has to keep pointing at something.

Every function flushes and leaves the commit to its caller.
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models.activity import Notification
from ..models.approval import Approval
from ..models.asset import Asset, AssetStatus, AssetVersion, MediaFile, ProcessingStatus
from ..models.comment import Comment
from ..models.processing_run import ProcessingRun
from ..models.share import ShareLink
from ..models.sign_off import SignOff
from ..models.user import User
from .activity_service import log_activity
from .sign_off import active_sign_off
from .versions import UNVIEWABLE_STATUSES, next_version_number

#: An upload or a transcode still under way. Left alone by everything here:
#: removing or moving it would pull the row out from under the worker.
IN_FLIGHT = (ProcessingStatus.uploading, ProcessingStatus.processing)

#: What "finished" means for a project-wide tidy: delivered, or put away.
FINISHED_STATUSES = (AssetStatus.approved, AssetStatus.archived)


class StackError(Exception):
    """A request that cannot be carried out, with the answer to give."""

    def __init__(self, detail: str, status_code: int = 409):
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


def live_versions(db: Session, asset_id: uuid.UUID) -> list[AssetVersion]:
    """The asset's versions that are not in the trash, oldest first."""
    return (
        db.query(AssetVersion)
        .filter(AssetVersion.asset_id == asset_id, AssetVersion.deleted_at.is_(None))
        .order_by(AssetVersion.version_number)
        .all()
    )


def version_bytes(db: Session, version_ids: list) -> dict:
    """What each version costs: its upload plus everything made from it."""
    if not version_ids:
        return {}
    rows = (
        db.query(
            MediaFile.version_id,
            func.coalesce(func.sum(MediaFile.file_size_bytes), 0)
            + func.coalesce(func.sum(MediaFile.derived_size_bytes), 0),
        )
        .filter(MediaFile.version_id.in_(version_ids))
        .group_by(MediaFile.version_id)
        .all()
    )
    sizes = {vid: int(total or 0) for vid, total in rows}
    return {vid: sizes.get(vid, 0) for vid in version_ids}


def _signed_version_id(db: Session, asset_id: uuid.UUID) -> Optional[uuid.UUID]:
    record = active_sign_off(db, asset_id)
    return record.version_id if record is not None else None


def tidy_plan(db: Session, asset: Asset) -> dict:
    """What tidying this video would keep and what it would remove.

    Kept: the newest version people can watch, the version a client signed off
    (if there is one), and anything still uploading or processing. Removed:
    every other live version. A video with nothing watchable is left alone, so
    a tidy can never leave a video with nothing to show.
    """
    versions = live_versions(db, asset.id)
    sizes = version_bytes(db, [v.id for v in versions])
    signed = _signed_version_id(db, asset.id)
    watchable = [v for v in versions if v.processing_status not in UNVIEWABLE_STATUSES]
    newest = watchable[-1] if watchable else None

    rows = []
    for version in versions:
        if newest is None:
            action, reason = "keep", "nothing here can be watched yet"
        elif version.id == newest.id:
            action, reason = "keep", "the latest version"
        elif signed is not None and version.id == signed:
            action, reason = "keep", "signed off by the client"
        elif version.processing_status in IN_FLIGHT:
            action, reason = "keep", "still uploading or processing"
        else:
            action, reason = "remove", None
        rows.append({
            "version_id": version.id,
            "version_number": version.version_number,
            "processing_status": getattr(version.processing_status, "value", str(version.processing_status)),
            "bytes": sizes.get(version.id, 0),
            "action": action,
            "reason": reason,
        })
    removing = [r for r in rows if r["action"] == "remove"]
    return {
        "asset_id": asset.id,
        "asset_name": asset.name,
        "versions": rows,
        "remove_count": len(removing),
        "remove_bytes": sum(r["bytes"] for r in removing),
        "total_bytes": sum(r["bytes"] for r in rows),
    }


def _trash_versions(db: Session, version_ids: list) -> None:
    if not version_ids:
        return
    db.query(AssetVersion).filter(
        AssetVersion.id.in_(version_ids), AssetVersion.deleted_at.is_(None),
    ).update({"deleted_at": datetime.now(timezone.utc)}, synchronize_session="fetch")


def tidy_asset(db: Session, asset: Asset, actor: User) -> dict:
    """Carry out `tidy_plan`. Returns the plan that was applied."""
    plan = tidy_plan(db, asset)
    removing = [r for r in plan["versions"] if r["action"] == "remove"]
    if removing:
        _trash_versions(db, [r["version_id"] for r in removing])
        log_activity(
            db, "versions_tidied", user_id=actor.id, project_id=asset.project_id, asset_id=asset.id,
            payload={
                "versions": [str(r["version_id"]) for r in removing],
                "numbers": [r["version_number"] for r in removing],
                "bytes": plan["remove_bytes"],
            },
        )
        db.flush()
    return plan


def project_tidy_plan(db: Session, project_id: uuid.UUID, scope: str = "finished") -> dict:
    """The tidy plan for every video in a project that has something to remove.

    `finished` covers videos that are approved, archived or signed off, which is
    the case this exists for: a job is done, its working versions can go. `all`
    covers every video in the project.
    """
    if scope not in ("finished", "all"):
        raise StackError("scope must be 'finished' or 'all'", 422)
    assets = (
        db.query(Asset)
        .filter(Asset.project_id == project_id, Asset.deleted_at.is_(None))
        .order_by(Asset.name)
        .all()
    )
    plans = []
    for asset in assets:
        if scope == "finished" and asset.status not in FINISHED_STATUSES and active_sign_off(db, asset.id) is None:
            continue
        plan = tidy_plan(db, asset)
        if plan["remove_count"]:
            plans.append(plan)
    return {
        "project_id": project_id,
        "scope": scope,
        "assets": plans,
        "remove_count": sum(p["remove_count"] for p in plans),
        "remove_bytes": sum(p["remove_bytes"] for p in plans),
    }


def tidy_project(db: Session, project_id: uuid.UUID, actor: User, scope: str = "finished") -> dict:
    plan = project_tidy_plan(db, project_id, scope)
    for asset_plan in plan["assets"]:
        asset = db.query(Asset).filter(Asset.id == asset_plan["asset_id"]).first()
        if asset is not None:
            tidy_asset(db, asset, actor)
    return plan


def _live_version(db: Session, asset: Asset, version_id: uuid.UUID) -> AssetVersion:
    version = db.query(AssetVersion).filter(
        AssetVersion.id == version_id, AssetVersion.asset_id == asset.id,
        AssetVersion.deleted_at.is_(None),
    ).first()
    if version is None:
        raise StackError("Version not found", 404)
    return version


def delete_version(db: Session, asset: Asset, version_id: uuid.UUID, actor: User) -> dict:
    """Move one version to the trash.

    Refused for the only version (delete the video instead), for a version a
    client signed off, and for one still uploading or processing.
    """
    version = _live_version(db, asset, version_id)
    if version.processing_status in IN_FLIGHT:
        raise StackError("This version is still uploading or processing. Wait for it to finish, or cancel the upload.")
    if _signed_version_id(db, asset.id) == version.id:
        raise StackError("This version has been signed off. Reopen the sign-off before removing it.")
    if len(live_versions(db, asset.id)) <= 1:
        raise StackError("This is the only version. Delete the video instead.")
    freed = version_bytes(db, [version.id]).get(version.id, 0)
    _trash_versions(db, [version.id])
    log_activity(
        db, "version_deleted", user_id=actor.id, project_id=asset.project_id, asset_id=asset.id,
        payload={"version": str(version.id), "number": version.version_number, "bytes": freed},
    )
    db.flush()
    return {"version_id": version.id, "version_number": version.version_number, "bytes": freed}


def _move_version_records(db: Session, version_ids: list, to_asset_id: uuid.UUID) -> None:
    """Everything recorded against these versions follows them to their new video."""
    if not version_ids:
        return
    comment_ids = [row[0] for row in db.query(Comment.id).filter(Comment.version_id.in_(version_ids)).all()]
    for model in (Comment, Approval, SignOff, ProcessingRun):
        db.query(model).filter(model.version_id.in_(version_ids)).update(
            {"asset_id": to_asset_id}, synchronize_session=False,
        )
    if comment_ids:
        db.query(Notification).filter(Notification.comment_id.in_(comment_ids)).update(
            {"asset_id": to_asset_id}, synchronize_session=False,
        )


def _refuse_if_signed_off(db: Session, asset: Asset) -> None:
    if active_sign_off(db, asset.id) is not None:
        raise StackError(f"“{asset.name}” has been signed off. Reopen the sign-off before changing its versions.")


def release_version(
    db: Session, asset: Asset, version_id: uuid.UUID, actor: User, name: Optional[str] = None,
) -> Asset:
    """Take one version out of the stack and make it a video of its own.

    The new video sits beside the old one (same project and folder), starts as
    a draft at version 1, and takes the version's comments and approvals with
    it. The files are not moved or copied: the version keeps its storage.
    """
    version = _live_version(db, asset, version_id)
    _refuse_if_signed_off(db, asset)
    if version.processing_status in IN_FLIGHT:
        raise StackError("This version is still uploading or processing. Wait for it to finish first.")
    if len(live_versions(db, asset.id)) <= 1:
        raise StackError("This is the only version, so there is nothing to release it from.")

    title = (name or "").strip() or f"{asset.name} (v{version.version_number})"
    released = Asset(
        project_id=asset.project_id,
        folder_id=asset.folder_id,
        name=title[:255],
        asset_type=asset.asset_type,
        status=AssetStatus.draft,
        created_by=actor.id,
    )
    db.add(released)
    db.flush()

    was_number = version.version_number
    version.asset_id = released.id
    version.version_number = 1
    db.flush()
    _move_version_records(db, [version.id], released.id)
    log_activity(
        db, "version_released", user_id=actor.id, project_id=asset.project_id, asset_id=asset.id,
        payload={"version": str(version.id), "number": was_number, "new_asset": str(released.id)},
    )
    log_activity(
        db, "created", user_id=actor.id, project_id=asset.project_id, asset_id=released.id,
        payload={"released_from": str(asset.id), "number": was_number},
    )
    db.flush()
    return released


def stack_assets(db: Session, target: Asset, source: Asset, actor: User) -> dict:
    """Put `source` on top of `target`: its versions become target's newest.

    For a revision that was uploaded as a new video when it should have been a
    new version. The source's versions keep their order and take the next free
    numbers on the target; their comments and approvals come with them; a share
    link to the source now opens the target; and the emptied source goes to the
    trash.
    """
    if source.id == target.id:
        raise StackError("Choose a different video to stack.", 422)
    if source.deleted_at is not None or target.deleted_at is not None:
        raise StackError("Video not found", 404)
    if source.project_id != target.project_id:
        raise StackError("Both videos have to be in the same project.")
    if source.asset_type != target.asset_type:
        raise StackError("Both have to be the same kind of file.")
    _refuse_if_signed_off(db, target)
    _refuse_if_signed_off(db, source)

    moving = live_versions(db, source.id)
    if not moving:
        raise StackError(f"“{source.name}” has no versions to stack.")
    if any(v.processing_status in IN_FLIGHT for v in moving):
        raise StackError(f"“{source.name}” is still uploading or processing. Wait for it to finish first.")

    number = next_version_number(db, target.id)
    numbers = []
    for version in moving:
        version.asset_id = target.id
        version.version_number = number
        numbers.append(number)
        number += 1
        db.flush()
    _move_version_records(db, [v.id for v in moving], target.id)

    # Anyone holding a link to the source should land on the stack it joined.
    db.query(ShareLink).filter(ShareLink.asset_id == source.id).update(
        {"asset_id": target.id}, synchronize_session=False,
    )
    source.deleted_at = datetime.now(timezone.utc)
    target.updated_at = datetime.now(timezone.utc)
    log_activity(
        db, "versions_stacked", user_id=actor.id, project_id=target.project_id, asset_id=target.id,
        payload={
            "source_asset": str(source.id), "source_name": source.name,
            "versions": [str(v.id) for v in moving], "numbers": numbers,
        },
    )
    db.flush()
    return {
        "asset_id": target.id,
        "source_asset_id": source.id,
        "moved_versions": len(moving),
        "version_numbers": numbers,
    }
