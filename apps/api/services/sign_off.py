"""Client sign-off: the rules every route shares.

An asset is signed off while it has a SignOff row that has not been reopened.
While it is, it is locked: no new versions, no new comments. A share link that
asks for a sign-off (`require_sign_off`) hands out downloads, original
included, only once the asset is signed off.
"""
import uuid
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from ..models.asset import Asset
from ..models.share import ShareLink
from ..models.sign_off import SignOff

SIGNED_OFF_DETAIL = (
    "This has been signed off by the client and is locked. "
    "A project admin can reopen it to make changes."
)


def sign_off_statement(asset_name: str, version_number: int) -> str:
    """The words a signer agrees to. Stored on the record exactly as shown."""
    return (
        f"I approve version {version_number} of “{asset_name}” as final "
        "and confirm that no further changes are required."
    )


def active_sign_off(db: Session, asset_id: uuid.UUID) -> Optional[SignOff]:
    """The sign-off in force for an asset, or None."""
    record = (
        db.query(SignOff)
        .filter(SignOff.asset_id == asset_id, SignOff.reopened_at.is_(None))
        .order_by(SignOff.created_at.desc())
        .first()
    )
    # Only a real record locks anything. This is the gate in front of every
    # upload and comment, so anything else a session hands back reads as "not
    # signed off" rather than as a lock.
    return record if isinstance(record, SignOff) else None


def ensure_not_signed_off(db: Session, asset_id: uuid.UUID) -> None:
    """Refuse a change to a signed-off asset. Call before adding a version or a comment."""
    if active_sign_off(db, asset_id) is not None:
        raise HTTPException(status_code=409, detail=SIGNED_OFF_DETAIL)


def _asks_for_sign_off(link: ShareLink) -> bool:
    return getattr(link, "require_sign_off", False) is True


def sign_off_unlocks_download(db: Session, link: ShareLink, asset: Asset) -> bool:
    """Whether this link's sign-off requirement has been met for this asset,
    which is what turns its downloads on."""
    if not _asks_for_sign_off(link):
        return False
    return active_sign_off(db, asset.id) is not None


def share_download_allowed(db: Session, link: ShareLink, asset: Asset) -> bool:
    """Whether a share link may hand out a download of this asset.

    A link that requires a sign-off withholds every download until the asset is
    signed off, whatever its own download switch says: the point of the
    requirement is that the file is released by the signature. Any other link
    follows its download switch as before.
    """
    if _asks_for_sign_off(link):
        return active_sign_off(db, asset.id) is not None
    return bool(link.allow_download)
