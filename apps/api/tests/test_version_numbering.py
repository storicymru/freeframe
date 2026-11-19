"""Version numbers: never handed out twice, and never spent on an upload nobody saw.

A cancelled or reclaimed upload gives its number back, so the stack reads v1,
v2, v3 with no hole. A version in the trash keeps its number, because it can be
restored. The rest of this note is why the trash has to be counted at all.

`uq_asset_versions_asset_version` spans `(asset_id, version_number)` and knows
nothing about `deleted_at`, so a soft-deleted version still owns its number. A
handler that numbers by counting only the *live* versions therefore hands back a
number the constraint is still holding, and the insert dies with an
`IntegrityError` — on every retry, permanently.

Reaching it needs no discard feature and no unusual use. `_reap_stale_uploads`
soft-deletes a version whose transfer stopped, so an asset that has had a single
upload reclaimed refuses the next one from then on.

There are two handlers that create versions and they are near-verbatim copies, so
every test here is parameterized over both. Fixing one and not the other is the
failure this file exists to prevent.
"""
import uuid

import pytest

import apps.api.routers.upload as upload_module
import apps.api.routers.assets as assets_module
from apps.api.models.asset import ProcessingStatus


def _seed(real_db, monkeypatch):
    """An owner, a project, and the monkeypatching both handlers need."""
    from apps.api.models.user import User
    from apps.api.models.project import Project, ProjectType

    owner = User(email=f"vn-{uuid.uuid4()}@t.local", name="t")
    real_db.add(owner)
    real_db.flush()
    project = Project(name="t", project_type=ProjectType.personal, created_by=owner.id)
    real_db.add(project)
    real_db.flush()

    for mod in (upload_module, assets_module):
        monkeypatch.setattr(mod, "create_multipart_upload", lambda k, m: "an-upload",
                            raising=False)
        monkeypatch.setattr(mod, "upload_guard_error", lambda db, n: None, raising=False)
        monkeypatch.setattr(mod, "choose_part_size", lambda db, n: (10 * 1024 * 1024, None), raising=False)
        monkeypatch.setattr(mod, "require_project_role", lambda *a, **k: None, raising=False)

    return owner, project


def _call(path, real_db, owner, project, asset):
    """Create a version through whichever handler `path` names."""
    from apps.api.schemas.upload import InitiateUploadRequest

    body = InitiateUploadRequest(
        project_id=project.id,
        asset_id=asset.id if path == "initiate_upload" else None,
        asset_name="clip",
        original_filename="clip.mp4",
        mime_type="video/mp4",
        file_size_bytes=1024,
    )
    if path == "initiate_upload":
        return upload_module.initiate_upload(body, db=real_db, current_user=owner)
    return assets_module.initiate_new_version(
        asset.id, body, db=real_db, current_user=owner
    )


def _asset_with_versions(real_db, owner, project, rows):
    """An asset carrying `(version_number, is_deleted[, status])` rows."""
    from datetime import datetime, timezone
    from apps.api.models.asset import Asset, AssetType, AssetVersion

    asset = Asset(project_id=project.id, name="t", asset_type=AssetType.video,
                  created_by=owner.id)
    real_db.add(asset)
    real_db.flush()
    for number, is_deleted, *status in rows:
        version = AssetVersion(
            asset_id=asset.id,
            version_number=number,
            processing_status=status[0] if status else ProcessingStatus.ready,
            created_by=owner.id,
            deleted_at=datetime.now(timezone.utc) if is_deleted else None,
        )
        real_db.add(version)
    real_db.flush()
    return asset


def _numbers(real_db, asset):
    """Every row's number on the asset, lowest first."""
    from apps.api.models.asset import AssetVersion
    real_db.expire_all()
    return sorted(n for (n,) in real_db.query(AssetVersion.version_number).filter(
        AssetVersion.asset_id == asset.id))


def _created_number(real_db, result):
    from apps.api.models.asset import AssetVersion
    return real_db.query(AssetVersion).filter(AssetVersion.id == result.version_id).first().version_number


@pytest.mark.parametrize("path", ["initiate_upload", "initiate_new_version"])
def test_a_version_in_the_trash_keeps_its_number(real_db, monkeypatch, path):
    """v2 was seen and then removed; it can be restored, so the next is v3."""
    owner, project = _seed(real_db, monkeypatch)
    asset = _asset_with_versions(real_db, owner, project, [(1, False), (2, True)])

    result = _call(path, real_db, owner, project, asset)

    assert _created_number(real_db, result) == 3, (
        f"{path} reissued the number of a version in the trash, which "
        "uq_asset_versions_asset_version still holds"
    )


@pytest.mark.parametrize("path", ["initiate_upload", "initiate_new_version"])
def test_numbering_still_follows_the_live_versions_when_none_are_deleted(
    real_db, monkeypatch, path
):
    """The ordinary case has to keep working: v1 and v2 live means the next is v3."""
    owner, project = _seed(real_db, monkeypatch)
    asset = _asset_with_versions(real_db, owner, project, [(1, False), (2, False)])

    assert _created_number(real_db, _call(path, real_db, owner, project, asset)) == 3


@pytest.mark.parametrize("path", ["initiate_upload", "initiate_new_version"])
def test_every_version_in_the_trash_still_numbers_past_them(real_db, monkeypatch, path):
    owner, project = _seed(real_db, monkeypatch)
    asset = _asset_with_versions(real_db, owner, project, [(1, True)])

    assert _created_number(real_db, _call(path, real_db, owner, project, asset)) == 2


# ── An upload that never arrived does not spend a number ──────────────────────

@pytest.mark.parametrize("path", ["initiate_upload", "initiate_new_version"])
def test_a_cancelled_upload_gives_its_number_to_the_next_one(real_db, monkeypatch, path):
    """The report: v3 live, v4 cancelled part-way, and the next upload came in as v5."""
    from apps.api.models.asset import AssetVersion
    from apps.api.tasks.cleanup_tasks import _dispose_version_files

    owner, project = _seed(real_db, monkeypatch)
    asset = _asset_with_versions(real_db, owner, project, [(1, False), (2, False), (3, False)])
    cancelled = _call(path, real_db, owner, project, asset)
    assert _created_number(real_db, cancelled) == 4

    version = real_db.query(AssetVersion).filter(AssetVersion.id == cancelled.version_id).first()
    _dispose_version_files(real_db, version)
    real_db.flush()

    assert _created_number(real_db, _call(path, real_db, owner, project, asset)) == 4
    assert _numbers(real_db, asset) == [-1, 1, 2, 3, 4]


def test_two_cancelled_uploads_on_one_asset_do_not_collide(real_db, monkeypatch):
    """Each disposed row still has to hold something unique under the constraint."""
    from apps.api.models.asset import AssetVersion
    from apps.api.tasks.cleanup_tasks import _dispose_version_files

    owner, project = _seed(real_db, monkeypatch)
    asset = _asset_with_versions(real_db, owner, project, [(1, False)])
    for _ in range(2):
        made = _call("initiate_upload", real_db, owner, project, asset)
        assert _created_number(real_db, made) == 2
        _dispose_version_files(
            real_db, real_db.query(AssetVersion).filter(AssetVersion.id == made.version_id).first())
        real_db.flush()

    assert _numbers(real_db, asset) == [-2, -1, 1]


# ── The rows already there (the migration) ────────────────────────────────────

def _migration():
    import importlib.util
    from pathlib import Path
    path = next((Path(__file__).parents[1] / "alembic" / "versions").glob("e3f6a9b2c4d5_*.py"))
    spec = importlib.util.spec_from_file_location("release_numbers_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_existing_holes_left_by_dead_uploads_are_closed(real_db, monkeypatch):
    """v3 live, a cancelled v4 in the trash, v5 live: v5 becomes v4."""
    U = ProcessingStatus.uploading
    owner, project = _seed(real_db, monkeypatch)
    asset = _asset_with_versions(
        real_db, owner, project, [(1, False), (2, True, U), (3, False), (4, True, U), (5, False)])
    # A version someone removed is not a hole: it can come back to its number.
    untouched = _asset_with_versions(real_db, owner, project, [(1, False), (2, True), (3, False)])

    _migration().release_and_close(real_db.connection())

    assert _numbers(real_db, asset) == [-2, -1, 1, 2, 3]
    assert _numbers(real_db, untouched) == [1, 2, 3]
    # And it is safe to run where there is nothing left to do.
    assert _migration().release_and_close(real_db.connection()) == 0


def test_a_signed_off_video_keeps_the_numbers_people_approved(real_db, monkeypatch):
    """The sign-off statement quotes the number, so nothing above the hole moves."""
    from apps.api.models.asset import AssetVersion
    from apps.api.models.sign_off import SignOff

    owner, project = _seed(real_db, monkeypatch)
    asset = _asset_with_versions(
        real_db, owner, project, [(1, False), (2, True, ProcessingStatus.uploading), (3, False)])
    v3 = real_db.query(AssetVersion).filter(
        AssetVersion.asset_id == asset.id, AssetVersion.version_number == 3).first()
    real_db.add(SignOff(
        asset_id=asset.id, version_id=v3.id, asset_name="t", version_number=3,
        signer_name="c", signer_email="c@t.local", statement="I approve version 3",
    ))
    real_db.flush()

    _migration().release_and_close(real_db.connection())

    assert _numbers(real_db, asset) == [-1, 1, 3]
