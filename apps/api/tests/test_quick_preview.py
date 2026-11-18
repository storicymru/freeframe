"""The quick preview: a watchable version first, the full ladder behind it."""
import functools
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from apps.api.models.asset import ProcessingStatus
from apps.api.models.processing_run import ProcessingRun
from apps.api.tasks import transcode_tasks
from apps.api.tasks.transcode_tasks import _has_preview, _process_video, sweep_replaced_previews
from apps.api.tests import test_source_copy
from packages.transcoder.base import TranscodeJob, TranscodeResult

PREFIX = "processed/p/a/v"
BIG = 2 * 1024 * 1024 * 1024


def _ok(prefix, mp4=None):
    return TranscodeResult(
        success=True, hls_prefix=prefix, mp4_key=mp4, thumbnail_keys=[f"{prefix}/thumbnail.jpg"],
        duration_seconds=2722.0, width=1920, height=1080, fps=25.0,
    )


def _run(results, *, enabled=True, size=BIG, processed=None):
    """Run _process_video with the transcoder answering `results` in order.
    Returns (jobs it was given, media_file, version, statuses seen at each call, scheduled)."""
    media_file = MagicMock(s3_key_raw="raw/x.mp4", s3_key_processed=processed, s3_key_download=None,
                           s3_key_thumbnail=None, file_size_bytes=size)
    version = MagicMock(processing_status=ProcessingStatus.processing)
    jobs, statuses = [], []
    queue = list(results)

    async def transcode(job):
        jobs.append(job)
        statuses.append((version.processing_status, media_file.s3_key_processed, media_file.s3_key_download))
        return queue.pop(0)

    with patch("packages.transcoder.ffmpeg_transcoder.FFmpegTranscoder") as MockT, \
         patch.object(transcode_tasks.settings, "transcoder_quick_preview", enabled), \
         patch.object(transcode_tasks, "_publish_event") as events, \
         patch("apps.api.services.processing_log.record_preview_ready") as recorded, \
         patch("apps.api.services.s3_service.delete_prefix") as deleted:
        scheduled = MagicMock()
        MockT.return_value.transcode = transcode
        _process_video(MagicMock(), MagicMock(), version, media_file, MagicMock(), PREFIX)
    return jobs, media_file, version, statuses, scheduled, recorded, events, deleted


def test_off_by_default_is_one_transcode_as_before():
    jobs, media_file, _, _, scheduled, recorded, _, _ = _run([_ok(PREFIX, "d.mp4")], enabled=False)
    assert len(jobs) == 1 and jobs[0].copy_only is False
    assert media_file.s3_key_processed == PREFIX and media_file.s3_key_download == "d.mp4"
    scheduled.assert_not_called()
    recorded.assert_not_called()


def test_a_copyable_upload_is_watchable_before_the_ladder_starts():
    jobs, media_file, version, statuses, scheduled, recorded, events, _ = _run(
        [_ok(f"{PREFIX}/preview", "should-not-be-offered.mp4"), _ok(PREFIX, "d.mp4")])

    assert [(j.qualities, j.copy_only, j.output_s3_prefix) for j in jobs[:1]] == [(["1080p"], True, f"{PREFIX}/preview")]
    assert jobs[1].copy_only is False and jobs[1].output_s3_prefix == PREFIX
    # By the time the ladder starts, the version is ready on the preview, and
    # no download is offered from it.
    assert statuses[1] == (ProcessingStatus.ready, f"{PREFIX}/preview", None)
    recorded.assert_called_once()
    assert recorded.call_args[0][1] == "copy"
    assert events.call_args_list[0][0][1] == "transcode_complete"
    # Afterwards it is on the ladder. The preview's files are left for the
    # sweep, so nothing is deleted while someone may still be playing them.
    assert media_file.s3_key_processed == PREFIX and media_file.s3_key_download == "d.mp4"
    assert media_file.s3_key_thumbnail == f"{PREFIX}/thumbnail.jpg"


def test_an_upload_that_cannot_be_copied_gets_a_720p_preview():
    declined = TranscodeResult(success=False, copy_declined=True, error="no")
    jobs, _, _, statuses, _, recorded, _, _ = _run([declined, _ok(f"{PREFIX}/preview"), _ok(PREFIX)])
    assert [(j.qualities, j.copy_only) for j in jobs[:2]] == [(["1080p"], True), (["720p"], False)]
    assert statuses[2][0] == ProcessingStatus.ready
    assert recorded.call_args[0][1] == "720p"


def test_a_preview_that_fails_changes_nothing_and_the_ladder_still_runs():
    failed = TranscodeResult(success=False, error="boom")
    jobs, media_file, _, statuses, scheduled, recorded, _, deleted = _run([failed, failed, _ok(PREFIX, "d.mp4")])
    assert len(jobs) == 3
    assert statuses[2] == (ProcessingStatus.processing, None, None)
    assert media_file.s3_key_processed == PREFIX
    recorded.assert_not_called()
    scheduled.assert_not_called()
    deleted.assert_called_once_with(f"{PREFIX}/preview/")


def test_a_preview_that_raises_is_swallowed():
    jobs, media_file, _, _, _, _, _, _ = _run([RuntimeError("x"), _ok(PREFIX)])
    # The first answer is not a result at all; the ladder still lands.
    assert media_file.s3_key_processed == PREFIX


def test_a_small_upload_skips_the_preview():
    jobs, _, _, _, scheduled, _, _, _ = _run([_ok(PREFIX)], size=50 * 1024 * 1024)
    assert len(jobs) == 1 and jobs[0].copy_only is False
    scheduled.assert_not_called()


def test_a_retry_with_the_preview_in_place_goes_straight_to_the_ladder():
    jobs, media_file, _, _, scheduled, recorded, _, _ = _run([_ok(PREFIX)], processed=f"{PREFIX}/preview")
    assert len(jobs) == 1 and jobs[0].copy_only is False
    recorded.assert_not_called()
    assert media_file.s3_key_processed == PREFIX


def test_a_failed_ladder_leaves_the_preview_in_place():
    with pytest.raises(RuntimeError):
        _run([_ok(f"{PREFIX}/preview"), TranscodeResult(success=False, error="boom")])


def test_has_preview():
    assert _has_preview(MagicMock(s3_key_processed=f"{PREFIX}/preview"))
    assert not _has_preview(MagicMock(s3_key_processed=PREFIX))
    assert not _has_preview(MagicMock(s3_key_processed=None))
    assert not _has_preview(MagicMock())


# ── clearing a replaced preview away ─────────────────────────────────────────
#
# Against real Postgres: which runs the sweep picks is a query.

def _run_row(db, seed, *, completed_minutes_ago, kind="copy", outcome="ready", on_preview=False, removed=False):
    owner = seed.user()
    asset = seed.asset(seed.project(owner), owner)
    version, media = seed.version(asset, owner, s3_keys=True)
    ladder = f"processed/p/{asset.id}/{version.id}"
    media.s3_key_processed = f"{ladder}/preview" if on_preview else ladder
    now = datetime.now(timezone.utc)
    done = now - timedelta(minutes=completed_minutes_ago)
    run = ProcessingRun(
        version_id=version.id, asset_id=asset.id, attempts=1, preview_kind=kind,
        preview_ready_at=done, processing_completed_at=done, outcome=outcome,
        preview_removed_at=now if removed else None,
    )
    db.add(run)
    db.flush()
    return run, media, ladder


def test_the_sweep_clears_a_replaced_preview_and_measures_again(live_db, seed):
    run, media, ladder = _run_row(live_db, seed, completed_minutes_ago=60)
    with patch("apps.api.services.s3_service.delete_prefix") as deleted, \
         patch("apps.api.services.s3_service.prefix_size_bytes", return_value=4_242) as measured:
        assert sweep_replaced_previews(live_db) == 1
    deleted.assert_called_once_with(f"{ladder}/preview/")
    measured.assert_called_once_with(ladder)
    assert media.derived_size_bytes == 4_242
    assert run.preview_removed_at is not None


def test_the_sweep_runs_again_only_for_what_is_still_there(live_db, seed):
    _run_row(live_db, seed, completed_minutes_ago=60)
    with patch("apps.api.services.s3_service.delete_prefix") as deleted, \
         patch("apps.api.services.s3_service.prefix_size_bytes", return_value=1):
        assert sweep_replaced_previews(live_db) == 1
        assert sweep_replaced_previews(live_db) == 0
    assert deleted.call_count == 1


def test_the_sweep_leaves_what_it_should(live_db, seed):
    recent, _, _ = _run_row(live_db, seed, completed_minutes_ago=5)
    still_on_preview, _, _ = _run_row(live_db, seed, completed_minutes_ago=60, on_preview=True)
    no_preview, _, _ = _run_row(live_db, seed, completed_minutes_ago=60, kind=None)
    failed, _, _ = _run_row(live_db, seed, completed_minutes_ago=60, outcome="failed")
    done_already, _, _ = _run_row(live_db, seed, completed_minutes_ago=60, removed=True)
    with patch("apps.api.services.s3_service.delete_prefix") as deleted, \
         patch("apps.api.services.s3_service.prefix_size_bytes", return_value=1):
        assert sweep_replaced_previews(live_db) == 0
    deleted.assert_not_called()
    assert recent.preview_removed_at is None and still_on_preview.preview_removed_at is None


def test_the_sweep_survives_a_storage_error_and_tries_again_next_time(live_db, seed):
    run, _, _ = _run_row(live_db, seed, completed_minutes_ago=60)
    live_db.rollback = live_db.flush  # keep the seeded rows; the test's own rollback still applies
    with patch("apps.api.services.s3_service.delete_prefix", side_effect=RuntimeError("storage down")):
        assert sweep_replaced_previews(live_db) == 0
    assert run.preview_removed_at is None


def test_the_sweep_is_scheduled_on_the_maintenance_queue():
    from apps.api.tasks.celery_app import celery_app
    entries = [e for e in celery_app.conf.beat_schedule.values() if e["task"] == "sweep_replaced_previews"]
    assert len(entries) == 1
    assert celery_app.conf.task_routes["sweep_replaced_previews"] == {"queue": "maintenance"}
    assert "sweep_replaced_previews" in celery_app.tasks


# ── the transcoder's copy-only mode ──────────────────────────────────────────

def _copy_only(*args, **kwargs):
    with patch.object(test_source_copy, "TranscodeJob", functools.partial(TranscodeJob, copy_only=True)):
        return test_source_copy._transcode(*args, **kwargs)


def test_copy_only_remuxes_a_copyable_source_without_the_setting():
    cmd, result, _ = _copy_only(["1080p"], source=(1920, 1080), source_copy=None)
    assert result.success and test_source_copy._copies(cmd)


def test_copy_only_declines_a_larger_source_instead_of_encoding():
    # No HLS command is run at all, so the helper has no first one to return.
    with pytest.raises(IndexError):
        _copy_only(["1080p"], source=(3840, 2160), source_copy=None, hls_commands=0)


def test_copy_only_declines_when_the_remux_fails():
    with patch.object(test_source_copy, "TranscodeJob", functools.partial(TranscodeJob, copy_only=True)):
        _, result, commands = test_source_copy._transcode(
            ["1080p"], source=(1920, 1080), source_copy=None, remux_fails=True, hls_commands=1)
    assert result.success is False and result.copy_declined is True
