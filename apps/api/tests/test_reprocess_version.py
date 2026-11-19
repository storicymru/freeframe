"""Making a version's playback copies again from the master already stored.

For a video uploaded before the quality list changed: once 4K is switched on,
what is already there has no 4K copy until it is processed again. Nothing is
uploaded, the version stays watchable meanwhile, and the timing of the upload
itself is not written over. Over HTTP against real Postgres.
"""
from datetime import datetime, timedelta, timezone

import pytest

from apps.api.models.asset import AssetType, ProcessingStatus
from apps.api.models.activity import ActivityLog
from apps.api.models.processing_run import ProcessingRun
from apps.api.models.project import ProjectRole
from apps.api.services import processing_log, version_stack


@pytest.fixture
def owner(seed):
    return seed.user(name="Olwen Owner")


@pytest.fixture
def project(seed, owner):
    return seed.project(owner, name="Nightmode")


@pytest.fixture
def sent(monkeypatch):
    """What was handed to the worker, and a master that is in storage."""
    import apps.api.tasks.celery_app as celery_app
    calls = []
    monkeypatch.setattr(celery_app, "send_task_safe", lambda task, *args: calls.append(args))
    monkeypatch.setattr(version_stack, "head_object_size", lambda key: 17_000)
    return calls


def _path(asset, version):
    return f"/assets/{asset.id}/versions/{version.id}/reprocess"


def _run(db, version):
    db.expire_all()
    return db.query(ProcessingRun).filter(ProcessingRun.version_id == version.id).first()


def test_the_owner_sends_a_ready_version_back_to_the_worker(seed, as_user, owner, project, sent, live_db):
    asset = seed.media(project, owner, versions=2)
    v2 = seed.versions_of(asset)[1]

    answer = as_user(owner).post(_path(asset, v2))

    assert answer.status_code == 202
    assert answer.json()["version_number"] == 2
    assert sent == [(str(asset.id), str(v2.id))]
    # It stays watchable on the copies it has.
    assert seed.versions_of(asset)[1].processing_status == ProcessingStatus.ready
    run = _run(live_db, v2)
    assert run.reprocess_requested_at is not None and run.reprocess_completed_at is None
    assert run.reprocess_qualities
    assert live_db.query(ActivityLog).filter(
        ActivityLog.asset_id == asset.id, ActivityLog.action == "version_reprocess").count() == 1


def test_only_the_owner_or_an_admin_may(seed, as_user, owner, project, admin, sent):
    asset = seed.media(project, owner)
    v1 = seed.versions_of(asset)[0]
    editor = seed.user(name="Ed Editor")
    seed.member(project, editor, ProjectRole.editor)

    assert as_user(editor).post(_path(asset, v1)).status_code == 403
    assert as_user(seed.user(name="Nobody")).post(_path(asset, v1)).status_code == 403
    assert sent == []
    assert as_user(admin).post(_path(asset, v1)).status_code == 202


def test_asking_twice_does_not_start_two(seed, as_user, owner, project, sent, live_db):
    asset = seed.media(project, owner)
    v1 = seed.versions_of(asset)[0]
    assert as_user(owner).post(_path(asset, v1)).status_code == 202

    assert as_user(owner).post(_path(asset, v1)).status_code == 409
    assert len(sent) == 1

    # One that never finished stops blocking once it is older than any transcode.
    run = _run(live_db, v1)
    run.reprocess_requested_at = datetime.now(timezone.utc) - version_stack.REPROCESS_WINDOW - timedelta(minutes=1)
    live_db.flush()
    assert as_user(owner).post(_path(asset, v1)).status_code == 202


@pytest.mark.parametrize("status", [ProcessingStatus.uploading, ProcessingStatus.processing, ProcessingStatus.failed])
def test_a_version_that_is_not_ready_is_refused(seed, as_user, owner, project, sent, status):
    asset = seed.media(project, owner)
    seed.version(asset, owner, number=2, status=status)
    assert as_user(owner).post(_path(asset, seed.versions_of(asset)[1])).status_code == 409
    assert sent == []


def test_refused_when_the_master_is_gone_or_storage_does_not_answer(
    seed, as_user, owner, project, sent, monkeypatch, live_db,
):
    asset = seed.media(project, owner)
    v1 = seed.versions_of(asset)[0]

    monkeypatch.setattr(version_stack, "head_object_size", lambda key: None)
    assert as_user(owner).post(_path(asset, v1)).status_code == 409

    def unreachable(key):
        raise RuntimeError("storage down")
    monkeypatch.setattr(version_stack, "head_object_size", unreachable)
    assert as_user(owner).post(_path(asset, v1)).status_code == 503

    assert sent == []
    run = _run(live_db, v1)
    assert run is None or run.reprocess_requested_at is None


def test_only_video_and_only_a_live_version(seed, as_user, owner, project, sent, live_db):
    asset = seed.media(project, owner, versions=2)
    v1, v2 = seed.versions_of(asset)
    seed.trash(v1)
    assert as_user(owner).post(_path(asset, v1)).status_code == 404

    asset.asset_type = AssetType.image
    live_db.flush()
    assert as_user(owner).post(_path(asset, v2)).status_code == 422
    assert sent == []


# ── The timing log ────────────────────────────────────────────────────────────

def test_a_reprocess_is_timed_beside_the_upload_not_over_it(seed, owner, project, live_db, monkeypatch):
    asset = seed.media(project, owner)
    v1 = seed.versions_of(asset)[0]
    monkeypatch.setattr(processing_log, "_session", lambda: live_db)
    monkeypatch.setattr(live_db, "close", lambda: None)

    processing_log.record_processing_started(v1.id)
    processing_log.record_processing_finished(v1.id, ok=True)
    first = _run(live_db, v1)
    original = (first.processing_started_at, first.processing_completed_at, first.outcome, first.attempts)

    processing_log.record_reprocess_requested(live_db, v1.id, "2160p,1080p,720p,360p")
    live_db.flush()
    processing_log.record_processing_started(v1.id)
    processing_log.record_processing_finished(v1.id, ok=True)

    run = _run(live_db, v1)
    assert (run.processing_started_at, run.processing_completed_at, run.outcome, run.attempts) == original
    assert run.reprocess_outcome == "ready"
    assert run.reprocess_started_at is not None and run.reprocess_completed_at >= run.reprocess_started_at
    row = processing_log.describe(run)
    assert row["reprocess_qualities"] == "2160p,1080p,720p,360p"
    assert row["reprocess_seconds"] is not None
    # Finished, so the next ordinary event is the upload's again and another may be asked for.
    assert processing_log.reprocessing(run) is False
