"""Numbering for asset versions.

Lives here rather than in a router because there are two handlers that create
versions, `upload.initiate_upload` and `assets.initiate_new_version`, and they
are near-verbatim copies of one another. Numbering that drifts between them
hands out different answers for the same asset depending on which route the
client happened to take.
"""
import uuid

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models.asset import AssetVersion, ProcessingStatus

#: A version in one of these is not something a viewer can open: it is an upload
#: in flight or one that died. It is still the newest version by number, which
#: is why "latest" and "the one to show" are not the same question. It lives
#: here because the asset listings and the admin storage panel both have to
#: answer that question the same way: the panel refuses to let the newest
#: version be deleted on its own, and it has to mean the one people see.
UNVIEWABLE_STATUSES = (ProcessingStatus.uploading, ProcessingStatus.failed)


def next_version_number(db: Session, asset_id: uuid.UUID) -> int:
    """The next version number for an asset: one past the highest it holds.

    Counts every version that holds a number, **including the ones in the
    trash**. `uq_asset_versions_asset_version` spans `(asset_id,
    version_number)` and has no view of `deleted_at`, and a version in the trash
    can be restored, so its number is still its own: skipping it here would
    hand out a number the constraint is holding and the insert would fail with
    an `IntegrityError` on every retry.

    An upload that never arrived is the exception. It was cancelled, or its
    transfer stopped and the reaper took it; nobody ever saw it and it can never
    be restored (`restore_rules`), so `release_version_number` takes its number
    away and the next upload gets it. Without that a cancelled upload leaves a
    hole in the stack: v3, then v5.

    A released row holds a number below 1, which is why only numbers above 0
    are counted here.
    """
    highest = db.query(func.max(AssetVersion.version_number)).filter(
        AssetVersion.asset_id == asset_id,
        AssetVersion.version_number > 0,
    ).scalar()
    return (highest or 0) + 1


def release_version_number(db: Session, version: AssetVersion) -> None:
    """Give back the number of an upload that never arrived.

    Called as the upload is disposed of. The row stays, soft-deleted, until the
    retention sweep removes it, and the constraint still wants it to hold
    something unique on its asset, so it takes the next number below zero. No
    listing shows a number below 1 as a version.
    """
    lowest = db.query(func.min(AssetVersion.version_number)).filter(
        AssetVersion.asset_id == version.asset_id,
        AssetVersion.version_number < 0,
    ).scalar()
    version.version_number = (lowest or 0) - 1
    # The session does not autoflush, and the next release on this asset has to
    # see this one.
    db.flush()
