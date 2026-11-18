import uuid
import sys
import os
import asyncio
import json
import logging

# Ensure the workspace root is on the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

from celery.exceptions import Retry

from .celery_app import celery_app
from ..database import SessionLocal
from ..models.asset import AssetVersion, MediaFile, ProcessingStatus, AssetType
from ..models.asset import Asset
from ..services.s3_service import get_s3_client
from ..config import settings

log = logging.getLogger("celery.transcode")


def _run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def process_asset(self, asset_id: str, version_id: str):
    """Main processing task dispatched after upload completes."""
    db = SessionLocal()
    try:
        version = db.query(AssetVersion).filter(AssetVersion.id == uuid.UUID(version_id)).first()
        if not version:
            return  # version already cleaned up

        asset = db.query(Asset).filter(Asset.id == uuid.UUID(asset_id)).first()
        if not asset:
            if version:
                version.processing_status = ProcessingStatus.failed
                db.commit()
            return

        media_file = db.query(MediaFile).filter(MediaFile.version_id == version.id).first()
        if not media_file:
            version.processing_status = ProcessingStatus.failed
            db.commit()
            return

        # Reset to processing status before each attempt. Not once a quick
        # preview is published: the version is watchable on it, and a retry of
        # the full ladder behind it is no reason to take that away.
        if not _has_preview(media_file):
            version.processing_status = ProcessingStatus.processing
            db.commit()
        # The timing report. Its own session, never raises.
        from ..services.processing_log import record_processing_finished, record_processing_started
        record_processing_started(version_id)

        output_prefix = f"processed/{asset.project_id}/{asset_id}/{version_id}"
        s3 = get_s3_client()

        # Whether this read of the source is the last one there will be. The
        # handler below reads this same flag to decide `failed` -- but that
        # happens after the transcode has already returned, and the transcoder
        # needs to know beforehand: a check that cannot be certain has to give
        # way on the last attempt rather than spend the master. One flag for
        # both is deliberate, so they cannot drift apart. See TranscodeJob.
        final_attempt = self.request.retries >= self.max_retries

        try:
            if asset.asset_type in (AssetType.video,):
                _process_video(
                    db, asset, version, media_file, s3, output_prefix,
                    final_attempt=final_attempt,
                )
            elif asset.asset_type == AssetType.audio:
                _process_audio(db, asset, version, media_file, s3, output_prefix)
            elif asset.asset_type in (AssetType.image, AssetType.image_carousel):
                _process_image(db, asset, version, media_file, s3, output_prefix)

            version.processing_status = ProcessingStatus.ready
            db.commit()
            record_processing_finished(version_id, ok=True)

            # Publish SSE event (best-effort)
            _publish_event(str(asset.project_id), "transcode_complete", {
                "asset_id": asset_id,
                "version_id": version_id,
            })

        except Exception as exc:
            def _record_failure() -> None:
                from packages.transcoder.redact import redact_presigned_urls

                record_processing_finished(version_id, ok=False, error=redact_presigned_urls(str(exc)))
                if _has_preview(media_file):
                    # The full ladder never arrived, but the quick preview is
                    # published and plays. Leave the version on it rather than
                    # replace something watchable with "failed".
                    log.error(
                        "version %s: the full ladder failed and it stays on its quick preview: %s",
                        version_id, redact_presigned_urls(str(exc)),
                    )
                    return
                version.processing_status = ProcessingStatus.failed
                db.commit()
                # Every subscriber to the project's stream receives this, not
                # only the uploader, so never let a presigned URL through.
                _publish_event(str(asset.project_id), "transcode_failed", {
                    "asset_id": asset_id,
                    "version_id": version_id,
                    "error": redact_presigned_urls(str(exc)),
                })

            # `failed` is written only when nothing more is coming. Writing it
            # before every retry made the version oscillate
            # failed -> processing -> failed for the whole ladder (three retries
            # a minute apart) while its raw object sat there intact, so
            # /upload/complete's retry guard, the reaper and the client each got
            # a different answer depending on when they asked.
            if final_attempt:
                _record_failure()
                raise

            try:
                raise self.retry(exc=exc)
            except Retry:
                # Scheduled. Leave the version at `processing`: that is true, and
                # the next attempt will move it on.
                raise
            except Exception:
                # self.retry() raises Reject when the broker will not take the
                # message, so the retry never gets queued and nothing else will
                # run for this version. Leaving it at `processing` here is what
                # stranded uploads before -- record the failure we already know
                # about rather than leaving it for the sweep to find.
                _record_failure()
                raise

    finally:
        db.close()


PREVIEW_SUFFIX = "/preview"
# Below this an upload processes quickly enough that a preview pass would only
# add work.
PREVIEW_MIN_BYTES = 200 * 1024 * 1024
# How long a replaced preview is kept, for anyone still playing it.
PREVIEW_KEEP_SECONDS = 45 * 60


def _has_preview(media_file) -> bool:
    """Whether this file is currently published on its quick preview."""
    key = getattr(media_file, "s3_key_processed", None)
    return isinstance(key, str) and key.endswith(PREVIEW_SUFFIX)


def _store_result(media_file, result, *, download: bool = True) -> None:
    """Point the MediaFile at what a transcode produced."""
    media_file.s3_key_processed = result.hls_prefix
    # None when the remux failed. Recorded either way so a re-run of a version
    # that once had a download rung and now does not stops advertising it.
    media_file.s3_key_download = result.mp4_key if download else None
    if result.thumbnail_keys:
        media_file.s3_key_thumbnail = result.thumbnail_keys[0]
    if result.duration_seconds:
        media_file.duration_seconds = result.duration_seconds
    if result.width:
        media_file.width = result.width
    if result.height:
        media_file.height = result.height
    if result.fps:
        media_file.fps = result.fps


def _publish_quick_preview(db, asset, version, media_file, transcoder, output_prefix) -> bool:
    """Make the video watchable before the full ladder is built.

    A stream copy of the upload where that is possible (browser-safe H.264 at
    1080p or under: no encoding, so it takes as long as reading the file),
    otherwise one 720p rendition. The version is marked `ready` on it and the
    ladder that follows replaces it.

    Never raises and never leaves the version worse off: whatever goes wrong
    here, the caller carries on to the ordinary transcode as if this had not
    been tried.
    """
    from packages.transcoder.base import TranscodeJob
    from ..services.processing_log import record_preview_ready
    from ..services.s3_service import delete_prefix

    prefix = f"{output_prefix}{PREVIEW_SUFFIX}"

    def _job(**kwargs):
        return TranscodeJob(
            media_id=str(asset.id), version_id=str(version.id),
            input_s3_key=media_file.s3_key_raw, output_s3_prefix=prefix, **kwargs,
        )

    try:
        kind = "copy"
        # "1080p" is clamped to a smaller source, so this is "the source's own
        # size" for anything up to 1080p, and declined for anything larger.
        result = _run_async(transcoder.transcode(_job(qualities=["1080p"], copy_only=True)))
        if result.no_video_stream:
            return False
        if not result.success:
            kind = "720p"
            result = _run_async(transcoder.transcode(_job(qualities=["720p"])))
        if not result.success or result.no_video_stream or not result.hls_prefix:
            log.info("version %s: no quick preview (%s); building the ladder", version.id, result.error)
            try:
                delete_prefix(prefix + "/")
            except Exception:  # noqa: BLE001
                pass
            return False
        _store_result(media_file, result, download=False)
        version.processing_status = ProcessingStatus.ready
        db.commit()
    except Exception:  # noqa: BLE001 - the preview is a bonus, never a failure
        log.warning("version %s: quick preview failed; building the ladder", version.id, exc_info=True)
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            pass
        return False

    record_preview_ready(version.id, kind)
    log.info("version %s: watchable on a quick preview (%s)", version.id, kind)
    _publish_event(str(asset.project_id), "transcode_complete", {
        "asset_id": str(asset.id), "version_id": str(version.id), "preview": True,
    })
    return True


@celery_app.task(name="apps.api.tasks.transcode_tasks.delete_preview_outputs")
def delete_preview_outputs(prefix: str):
    """Remove a quick preview once the full ladder has replaced it.

    Runs a while after the swap so anyone still playing the preview finishes on
    it. Refuses anything that is not a preview folder, and anything a MediaFile
    still points at (the ladder failed and the version stayed on its preview).
    """
    from ..services.s3_service import delete_prefix

    if not (isinstance(prefix, str) and prefix.startswith("processed/") and prefix.endswith(PREVIEW_SUFFIX)):
        return
    db = SessionLocal()
    try:
        in_use = db.query(MediaFile).filter(MediaFile.s3_key_processed == prefix).first()
        if in_use is not None:
            return
    finally:
        db.close()
    delete_prefix(prefix + "/")


def _process_video(
    db, asset, version, media_file, s3, output_prefix, *,
    final_attempt: bool = False,
):
    from packages.transcoder.ffmpeg_transcoder import FFmpegTranscoder, parse_qualities
    from packages.transcoder.base import TranscodeJob

    transcoder = FFmpegTranscoder(
        s3, settings.s3_bucket, settings.s3_endpoint, storage_class=settings.s3_storage_class,
    )
    # Progress is cosmetic; the transcode is not. If the broker stops answering,
    # every publish costs the socket timeout, and this runs inside the loop
    # draining ffmpeg's stdout -- so paying it ~100 times would stall the encode
    # behind a full pipe. One failure is enough to stop trying for this job.
    progress_ok = {"enabled": True, "high_water": -1}

    def _on_progress(percent: int) -> None:
        if not progress_ok["enabled"]:
            return
        # A hardware attempt that fails at runtime is retried on the software
        # backend, and the second ffmpeg starts counting from zero. Clamp so the
        # bar never runs backwards from the viewer's point of view.
        if percent <= progress_ok["high_water"]:
            return
        progress_ok["high_water"] = percent
        # The version as well as the asset: two versions of one asset can be
        # transcoding at once, and the uploads panel shows a row for each.
        delivered = _publish_event(str(asset.project_id), "transcode_progress", {
            "asset_id": str(asset.id),
            "version_id": str(version.id),
            "percent": percent,
        })
        if delivered is False:
            progress_ok["enabled"] = False

    job = TranscodeJob(
        media_id=str(asset.id),
        version_id=str(version.id),
        input_s3_key=media_file.s3_key_raw,
        output_s3_prefix=output_prefix,
        qualities=parse_qualities(settings.transcoder_qualities),
        progress_cb=_on_progress,
        final_attempt=final_attempt,
    )
    # A quick watchable version first, where the instance asks for one and the
    # upload is big enough to be worth it. A retry finds the preview already
    # published and goes straight to the ladder.
    had_preview = _has_preview(media_file)
    if (
        settings.transcoder_quick_preview is True
        and not had_preview
        and (getattr(media_file, "file_size_bytes", None) or 0) >= PREVIEW_MIN_BYTES
    ):
        had_preview = _publish_quick_preview(db, asset, version, media_file, transcoder, output_prefix)

    result = _run_async(transcoder.transcode(job))

    if result.no_video_stream:
        # The browser types a .mpg or .mp4 carrying only audio as video/*, so
        # mime_to_asset_type routed it here. The file is perfectly good, it just
        # is not video. Correct the asset and run it through the audio pipeline
        # rather than failing an upload the user had no reason to think was
        # wrong (#82).
        log.info(
            "asset %s has no video stream; re-routing to the audio pipeline",
            asset.id,
        )
        asset.asset_type = AssetType.audio
        db.flush()
        _process_audio(db, asset, version, media_file, s3, output_prefix)
        return

    if not result.success:
        raise RuntimeError(f"Transcode failed: {result.error}")

    preview_prefix = media_file.s3_key_processed if had_preview else None
    _store_result(media_file, result)
    db.flush()
    if preview_prefix and preview_prefix != result.hls_prefix:
        # The ladder is in place. Clear the preview away later, not now: someone
        # may be watching it. If this never runs, the retention GC reclaims it
        # with the rest of the version's folder.
        try:
            delete_preview_outputs.apply_async(args=[preview_prefix], countdown=PREVIEW_KEEP_SECONDS)
        except Exception:  # noqa: BLE001
            log.warning("could not schedule removal of %s", preview_prefix, exc_info=True)


def _process_audio(db, asset, version, media_file, s3, output_prefix):
    from packages.transcoder.image_processor import process_audio
    result = process_audio(
        s3, settings.s3_bucket, media_file.s3_key_raw, output_prefix,
        storage_class=settings.s3_storage_class,
    )
    media_file.s3_key_processed = result.get("mp3_key")
    if result.get("waveform_key"):
        media_file.s3_key_thumbnail = result["waveform_key"]
    if result.get("duration_seconds"):
        media_file.duration_seconds = result["duration_seconds"]
    db.flush()


def _process_image(db, asset, version, media_file, s3, output_prefix):
    from packages.transcoder.image_processor import process_image
    result = process_image(
        s3, settings.s3_bucket, media_file.s3_key_raw, output_prefix,
        storage_class=settings.s3_storage_class,
    )
    media_file.s3_key_processed = result.get("webp_key")
    media_file.s3_key_thumbnail = result.get("thumbnail_key")
    db.flush()


def _publish_event(project_id: str, event_type: str, payload: dict):
    """Publish an SSE event from Celery worker context.

    Delegates to event_service so there is a single emit path; it is pooled and
    already best-effort, which is what this needs.
    """
    from ..services import event_service
    return event_service.publish_sync(project_id, event_type, payload)


def _eligible_media_rows(db):
    """Rows the #124 backfill still needs: (MediaFile, asset_type) pairs."""
    return (
        db.query(MediaFile, Asset.asset_type)
        .join(AssetVersion, MediaFile.version_id == AssetVersion.id)
        .join(Asset, AssetVersion.asset_id == Asset.id)
        .filter(
            AssetVersion.processing_status == ProcessingStatus.ready,
            AssetVersion.deleted_at.is_(None),
            Asset.deleted_at.is_(None),
            MediaFile.duration_seconds.is_(None),
            Asset.asset_type.in_([AssetType.video, AssetType.audio]),
        )
        .all()
    )


@celery_app.task(bind=True)
def backfill_media_metadata(self):
    """One-off backfill for #124: probe raw S3 files to populate missing
    duration/width/height/fps on already-processed media. Idempotent —
    only touches rows where duration_seconds IS NULL."""
    import subprocess
    from packages.transcoder.ffmpeg_transcoder import (
        _PRIMARY_VIDEO_STREAM,
        parse_probe_metadata,
    )
    from packages.transcoder.redact import redact_presigned_urls

    db = SessionLocal()
    updated = skipped = 0
    try:
        rows = _eligible_media_rows(db)
        s3 = get_s3_client()
        for media_file, asset_type in rows:
            row_id = media_file.id
            try:
                url = s3.generate_presigned_url(
                    "get_object",
                    Params={"Bucket": settings.s3_bucket, "Key": media_file.s3_key_raw},
                    ExpiresIn=3600,
                )
                cmd = ["ffprobe", "-v", "error", "-print_format", "json", "-show_format"]
                if asset_type == AssetType.video:
                    cmd += ["-show_streams", "-select_streams", _PRIMARY_VIDEO_STREAM]
                probe = subprocess.run(cmd + [url], capture_output=True, text=True, timeout=300)
                if probe.returncode != 0:
                    skipped += 1
                    continue
                try:
                    data = json.loads(probe.stdout)
                except json.JSONDecodeError:
                    skipped += 1
                    continue
                if asset_type == AssetType.video:
                    meta = parse_probe_metadata(data)
                    if meta is None:
                        skipped += 1
                        continue
                    media_file.duration_seconds = meta.duration_seconds or None
                    media_file.width = meta.width or None
                    media_file.height = meta.height or None
                    media_file.fps = meta.fps or None
                else:
                    duration = float((data.get("format") or {}).get("duration") or 0)
                    media_file.duration_seconds = duration or None
                db.commit()
                updated += 1
            except Exception as exc:
                db.rollback()
                skipped += 1
                # A timeout quotes the probe's argv, presigned URL included.
                log.warning(
                    "backfill: skipping media_file %s: %s",
                    row_id, redact_presigned_urls(str(exc)),
                )
                continue
        return {"updated": updated, "skipped": skipped}
    finally:
        db.close()
