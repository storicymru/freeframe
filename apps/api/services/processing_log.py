"""The timing log: when each upload arrived and how long it took to process.

Every function here opens its own session and swallows every error. The log
sits beside the upload and the transcode, and must never be the reason either
of them fails or is left with a broken transaction.
"""
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from ..models.asset import Asset, AssetVersion, MediaFile
from ..models.processing_run import ProcessingRun

logger = logging.getLogger(__name__)


def _session():
    from ..database import SessionLocal
    return SessionLocal()


def _value(enum_or_str) -> Optional[str]:
    if enum_or_str is None:
        return None
    return getattr(enum_or_str, "value", None) or str(enum_or_str)


def _ensure_run(db, version_id: uuid.UUID) -> Optional[ProcessingRun]:
    run = db.query(ProcessingRun).filter(ProcessingRun.version_id == version_id).first()
    if run is not None:
        return run
    version = db.query(AssetVersion).filter(AssetVersion.id == version_id).first()
    if version is None:
        return None
    asset = db.query(Asset).filter(Asset.id == version.asset_id).first()
    media = db.query(MediaFile).filter(MediaFile.version_id == version_id).first()
    run = ProcessingRun(
        version_id=version_id,
        asset_id=version.asset_id,
        project_id=asset.project_id if asset else None,
        asset_name=(asset.name[:255] if asset and asset.name else None),
        asset_type=_value(asset.asset_type) if asset else None,
        original_filename=(media.original_filename[:512] if media and media.original_filename else None),
        mime_type=media.mime_type if media else None,
        file_size_bytes=media.file_size_bytes if media else None,
        upload_started_at=version.created_at,
        attempts=0,
    )
    db.add(run)
    return run


def _write(version_id, change) -> None:
    try:
        db = _session()
    except Exception:  # noqa: BLE001 - a log must not break what it logs
        return
    try:
        run = _ensure_run(db, uuid.UUID(str(version_id)))
        if run is not None:
            change(db, run)
            db.commit()
    except Exception:  # noqa: BLE001
        logger.debug("processing log write failed for version %s", version_id, exc_info=True)
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            pass
    finally:
        try:
            db.close()
        except Exception:  # noqa: BLE001
            pass


def record_upload_completed(version_id) -> None:
    """The upload is assembled and about to be queued for processing."""
    def change(db, run):
        if run.upload_completed_at is None:
            run.upload_completed_at = datetime.now(timezone.utc)
    _write(version_id, change)


def record_processing_started(version_id) -> None:
    """A worker picked the version up. Counted once per attempt."""
    def change(db, run):
        if run.processing_started_at is None:
            run.processing_started_at = datetime.now(timezone.utc)
        run.attempts = (run.attempts or 0) + 1
    _write(version_id, change)


def record_preview_ready(version_id, kind: str) -> None:
    """The quick preview is published: the video is watchable from here."""
    def change(db, run):
        if run.preview_ready_at is None:
            run.preview_ready_at = datetime.now(timezone.utc)
            run.preview_kind = kind
    _write(version_id, change)


def record_processing_finished(version_id, ok: bool, error: Optional[str] = None) -> None:
    """Processing ended, well or badly. Picks up what the transcode learned
    about the file (length, frame size) while it is there."""
    def change(db, run):
        run.processing_completed_at = datetime.now(timezone.utc)
        run.outcome = "ready" if ok else "failed"
        run.error = (error or None) and error[:2000]
        media = db.query(MediaFile).filter(MediaFile.version_id == run.version_id).first()
        if media is not None:
            run.duration_seconds = media.duration_seconds
            run.width = media.width
            run.height = media.height
            run.fps = media.fps
            run.file_size_bytes = media.file_size_bytes or run.file_size_bytes
    _write(version_id, change)


def _seconds(start: Optional[datetime], end: Optional[datetime]) -> Optional[float]:
    if start is None or end is None:
        return None
    return round((end - start).total_seconds(), 1)


def describe(run: ProcessingRun) -> dict:
    """One row of the timing report, with the durations worked out."""
    upload = _seconds(run.upload_started_at, run.upload_completed_at)
    queued = _seconds(run.upload_completed_at, run.processing_started_at)
    processing = _seconds(run.processing_started_at, run.processing_completed_at)
    size = run.file_size_bytes
    return {
        "version_id": str(run.version_id),
        "asset_id": str(run.asset_id),
        "project_id": str(run.project_id) if run.project_id else None,
        "asset_name": run.asset_name,
        "asset_type": run.asset_type,
        "original_filename": run.original_filename,
        "mime_type": run.mime_type,
        "file_size_bytes": size,
        "duration_seconds": run.duration_seconds,
        "width": run.width,
        "height": run.height,
        "fps": run.fps,
        "upload_started_at": run.upload_started_at,
        "upload_completed_at": run.upload_completed_at,
        "processing_started_at": run.processing_started_at,
        "processing_completed_at": run.processing_completed_at,
        "outcome": run.outcome,
        "attempts": run.attempts,
        "error": run.error,
        "preview_ready_at": run.preview_ready_at,
        "preview_kind": run.preview_kind,
        # From the worker picking it up to the video being watchable.
        "preview_seconds": _seconds(run.processing_started_at, run.preview_ready_at),
        "upload_seconds": upload,
        "queued_seconds": queued,
        "processing_seconds": processing,
        # Megabytes a second while uploading, and processing time as a share of
        # the video's own length (0.5 = half as long as the video).
        "upload_mb_per_second": round(size / 1_000_000 / upload, 1) if size and upload else None,
        "processing_per_video_second": (
            round(processing / run.duration_seconds, 2) if processing and run.duration_seconds else None
        ),
    }
