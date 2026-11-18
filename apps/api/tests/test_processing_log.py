"""The timing log never gets in the way, and reports durations correctly."""
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from apps.api.models.processing_run import ProcessingRun
import pytest

from apps.api.services import processing_log


@pytest.fixture
def mock_user():
    """Signs every request in as this team account."""
    from apps.api.main import app
    from apps.api.middleware.auth import get_current_user
    user = MagicMock()
    user.id = uuid.uuid4()
    user.is_client = False
    user.is_superadmin = False
    app.dependency_overrides[get_current_user] = lambda: user
    try:
        yield user
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_describe_works_out_the_durations():
    start = datetime(2026, 11, 18, 3, 11, 6, tzinfo=timezone.utc)
    run = ProcessingRun(
        version_id=uuid.uuid4(), asset_id=uuid.uuid4(), asset_name="PYG",
        file_size_bytes=493_406_646, duration_seconds=76.0, width=3840, height=2160,
        upload_started_at=start,
        upload_completed_at=start + timedelta(seconds=37),
        processing_started_at=start + timedelta(seconds=38),
        processing_completed_at=start + timedelta(seconds=76),
        outcome="ready", attempts=1,
    )
    row = processing_log.describe(run)
    assert row["upload_seconds"] == 37.0
    assert row["queued_seconds"] == 1.0
    assert row["processing_seconds"] == 38.0
    assert row["processing_per_video_second"] == 0.5
    assert row["upload_mb_per_second"] == 13.3


def test_describe_leaves_gaps_for_a_run_still_in_flight():
    run = ProcessingRun(version_id=uuid.uuid4(), asset_id=uuid.uuid4(), attempts=0,
                        upload_started_at=datetime.now(timezone.utc))
    row = processing_log.describe(run)
    assert row["upload_seconds"] is None and row["processing_seconds"] is None
    assert row["processing_per_video_second"] is None


def test_a_database_that_cannot_be_reached_is_swallowed():
    with patch.object(processing_log, "_session", side_effect=RuntimeError("no database")):
        processing_log.record_upload_completed(uuid.uuid4())
        processing_log.record_processing_started(uuid.uuid4())
        processing_log.record_processing_finished(uuid.uuid4(), ok=False, error="boom")


def test_a_failing_write_rolls_back_and_closes():
    db = MagicMock()
    db.query.side_effect = RuntimeError("broken")
    with patch.object(processing_log, "_session", return_value=db):
        processing_log.record_processing_started(uuid.uuid4())
    db.rollback.assert_called_once()
    db.close.assert_called_once()


def test_finishing_records_the_outcome_and_what_the_file_turned_out_to_be():
    run = ProcessingRun(version_id=uuid.uuid4(), asset_id=uuid.uuid4(), attempts=1)
    media = MagicMock(duration_seconds=76.2, width=3840, height=2160, fps=25.0, file_size_bytes=5)
    db = MagicMock()
    db.query.return_value.filter.return_value.first.side_effect = [run, media]
    with patch.object(processing_log, "_session", return_value=db):
        processing_log.record_processing_finished(run.version_id, ok=True)
    assert run.outcome == "ready" and run.processing_completed_at is not None
    assert (run.duration_seconds, run.width, run.height) == (76.2, 3840, 2160)
    db.commit.assert_called_once()


def test_the_report_is_for_admins(client, mock_user, mock_db):
    mock_user.is_superadmin = False
    assert client.get("/admin/processing-runs").status_code == 403
    mock_user.is_superadmin = True
    mock_db.query.return_value.order_by.return_value.limit.return_value.all.return_value = []
    response = client.get("/admin/processing-runs")
    assert response.status_code == 200 and response.json() == []
