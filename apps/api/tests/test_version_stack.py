"""Tidying, deleting, releasing and stacking a video's versions.

Over HTTP against real Postgres, like the admin panel tests: what matters here
is which rows move and which stay, and a mock session cannot show that.
"""
import uuid

import pytest

from apps.api.models.activity import ActivityLog, Notification, NotificationType
from apps.api.models.approval import Approval
from apps.api.models.asset import Asset, AssetStatus, AssetVersion, ProcessingStatus
from apps.api.models.comment import Comment
from apps.api.models.processing_run import ProcessingRun
from apps.api.models.project import ProjectRole
from apps.api.models.share import ShareLink
from apps.api.models.sign_off import SignOff


@pytest.fixture
def owner(seed):
    return seed.user(name="Olwen Owner")


@pytest.fixture
def project(seed, owner):
    return seed.project(owner, name="Swansea Bay City Deal")


def _sign_off(db, asset, version, reopened=False):
    from datetime import datetime, timezone
    row = SignOff(
        asset_id=asset.id, version_id=version.id, asset_name=asset.name,
        version_number=version.version_number, signer_name="Carys Evans",
        signer_email="carys@example.test", statement="I approve this version.",
        reopened_at=datetime.now(timezone.utc) if reopened else None,
    )
    db.add(row)
    db.flush()
    return row


def _live_numbers(seed, asset):
    return [v.version_number for v in seed.versions_of(asset) if v.deleted_at is None]


# ── who may ───────────────────────────────────────────────────────────────────

def test_only_the_owner_or_an_admin_may_manage_versions(seed, as_user, owner, project, admin):
    asset = seed.media(project, owner, versions=3)
    editor = seed.user(name="Ed Editor")
    seed.member(project, editor, ProjectRole.editor)
    stranger = seed.user(name="Nobody")
    path = f"/assets/{asset.id}/versions/tidy"

    assert as_user(editor).get(path).status_code == 403
    assert as_user(editor).post(path, json={"confirm_count": 2}).status_code == 403
    assert as_user(stranger).get(path).status_code == 403
    assert as_user(owner).get(path).status_code == 200
    assert as_user(admin).get(path).status_code == 200
    assert _live_numbers(seed, asset) == [1, 2, 3]


def test_a_client_account_is_refused(seed, as_user, owner, project, live_db):
    """The real sign-in path refuses a client everything outside the portal;
    here it is enough that being a client never grants ownership."""
    asset = seed.media(project, owner, versions=2)
    client_user = seed.user(name="Carys Client")
    client_user.is_client = True
    live_db.flush()
    assert as_user(client_user).post(
        f"/assets/{asset.id}/versions/tidy", json={"confirm_count": 1},
    ).status_code == 403


# ── tidy ──────────────────────────────────────────────────────────────────────

def test_the_plan_prices_each_version_and_keeps_the_latest(seed, as_user, owner, project):
    asset = seed.media(project, owner, versions=3, original=1_000, derived=500)
    plan = as_user(owner).get(f"/assets/{asset.id}/versions/tidy").json()

    assert [(v["version_number"], v["action"], v["bytes"]) for v in plan["versions"]] == [
        (1, "remove", 1_500), (2, "remove", 1_500), (3, "keep", 1_500),
    ]
    assert plan["remove_count"] == 2 and plan["remove_bytes"] == 3_000 and plan["total_bytes"] == 4_500


def test_tidy_trashes_all_but_the_latest_and_records_it(seed, as_user, owner, project, live_db):
    asset = seed.media(project, owner, versions=3)
    response = as_user(owner).post(f"/assets/{asset.id}/versions/tidy", json={"confirm_count": 2})

    assert response.status_code == 200
    assert _live_numbers(seed, asset) == [3]
    # In the trash, not gone: the rows are still there to restore.
    assert len(seed.versions_of(asset)) == 3
    log = live_db.query(ActivityLog).filter(ActivityLog.asset_id == asset.id, ActivityLog.action == "versions_tidied").one()
    assert log.payload["numbers"] == [1, 2] and log.user_id == owner.id


def test_tidy_refuses_a_count_that_no_longer_matches(seed, as_user, owner, project):
    asset = seed.media(project, owner, versions=3)
    response = as_user(owner).post(f"/assets/{asset.id}/versions/tidy", json={"confirm_count": 1})
    assert response.status_code == 409
    assert _live_numbers(seed, asset) == [1, 2, 3]


def test_tidy_keeps_the_signed_off_version_even_when_it_is_not_the_latest(seed, as_user, owner, project, live_db):
    asset = seed.media(project, owner, versions=4)
    versions = seed.versions_of(asset)
    _sign_off(live_db, asset, versions[1])

    plan = as_user(owner).get(f"/assets/{asset.id}/versions/tidy").json()
    assert [(v["version_number"], v["action"]) for v in plan["versions"]] == [
        (1, "remove"), (2, "keep"), (3, "remove"), (4, "keep"),
    ]
    as_user(owner).post(f"/assets/{asset.id}/versions/tidy", json={"confirm_count": 2})
    assert _live_numbers(seed, asset) == [2, 4]


def test_a_reopened_sign_off_protects_nothing(seed, as_user, owner, project, live_db):
    asset = seed.media(project, owner, versions=3)
    _sign_off(live_db, asset, seed.versions_of(asset)[0], reopened=True)
    assert as_user(owner).get(f"/assets/{asset.id}/versions/tidy").json()["remove_count"] == 2


def test_tidy_keeps_the_newest_watchable_version_and_leaves_uploads_alone(seed, as_user, owner, project):
    asset = seed.asset(project, owner)
    seed.version(asset, owner, number=1)
    seed.version(asset, owner, number=2)
    seed.version(asset, owner, number=3, status=ProcessingStatus.failed)
    seed.version(asset, owner, number=4, status=ProcessingStatus.uploading)

    plan = as_user(owner).get(f"/assets/{asset.id}/versions/tidy").json()
    assert [(v["version_number"], v["action"]) for v in plan["versions"]] == [
        (1, "remove"), (2, "keep"), (3, "remove"), (4, "keep"),
    ]


def test_tidy_never_empties_a_video_with_nothing_watchable(seed, as_user, owner, project):
    asset = seed.asset(project, owner)
    seed.version(asset, owner, number=1, status=ProcessingStatus.failed)
    seed.version(asset, owner, number=2, status=ProcessingStatus.failed)
    assert as_user(owner).get(f"/assets/{asset.id}/versions/tidy").json()["remove_count"] == 0


def test_a_single_version_has_nothing_to_tidy(seed, as_user, owner, project):
    asset = seed.media(project, owner, versions=1)
    response = as_user(owner).post(f"/assets/{asset.id}/versions/tidy", json={"confirm_count": 0})
    assert response.status_code == 200 and response.json()["remove_count"] == 0
    assert _live_numbers(seed, asset) == [1]


# ── tidy a whole project ──────────────────────────────────────────────────────

def test_project_tidy_covers_finished_videos_only_by_default(seed, as_user, owner, project, live_db):
    working = seed.media(project, owner, name="working", versions=3)
    delivered = seed.media(project, owner, name="delivered", versions=3, original=2_000)
    delivered.status = AssetStatus.approved
    signed = seed.media(project, owner, name="signed", versions=2)
    _sign_off(live_db, signed, seed.versions_of(signed)[1])
    elsewhere = seed.media(seed.project(owner, name="other"), owner, versions=3)
    live_db.flush()

    plan = as_user(owner).get(f"/projects/{project.id}/versions/tidy").json()
    assert sorted(a["asset_name"] for a in plan["assets"]) == ["delivered", "signed"]
    assert plan["remove_count"] == 3 and plan["remove_bytes"] == 2 * 2_000 + 1_000

    done = as_user(owner).post(f"/projects/{project.id}/versions/tidy", json={"confirm_count": 3})
    assert done.status_code == 200
    assert _live_numbers(seed, delivered) == [3]
    assert _live_numbers(seed, signed) == [2]
    assert _live_numbers(seed, working) == [1, 2, 3]
    assert _live_numbers(seed, elsewhere) == [1, 2, 3]


def test_project_tidy_can_cover_every_video(seed, as_user, owner, project):
    one = seed.media(project, owner, name="one", versions=2)
    two = seed.media(project, owner, name="two", versions=3)
    plan = as_user(owner).get(f"/projects/{project.id}/versions/tidy?scope=all").json()
    assert plan["remove_count"] == 3
    as_user(owner).post(f"/projects/{project.id}/versions/tidy", json={"confirm_count": 3, "scope": "all"})
    assert _live_numbers(seed, one) == [2] and _live_numbers(seed, two) == [3]


def test_project_tidy_refuses_a_stale_count_and_an_unknown_scope(seed, as_user, owner, project):
    seed.media(project, owner, versions=2)
    client = as_user(owner)
    assert client.post(f"/projects/{project.id}/versions/tidy", json={"confirm_count": 5, "scope": "all"}).status_code == 409
    assert client.get(f"/projects/{project.id}/versions/tidy?scope=everything").status_code == 422
    assert client.post(f"/projects/{project.id}/versions/tidy", json={"confirm_count": 0, "scope": "everything"}).status_code == 422


# ── delete one version ────────────────────────────────────────────────────────

def test_delete_one_version(seed, as_user, owner, project):
    asset = seed.media(project, owner, versions=3, original=700, derived=300)
    middle = seed.versions_of(asset)[1]
    response = as_user(owner).delete(f"/assets/{asset.id}/versions/{middle.id}")
    assert response.status_code == 200 and response.json()["bytes"] == 1_000
    assert _live_numbers(seed, asset) == [1, 3]


def test_the_latest_version_can_be_deleted_and_the_one_before_takes_over(seed, as_user, owner, project):
    asset = seed.media(project, owner, versions=2)
    latest = seed.versions_of(asset)[1]
    assert as_user(owner).delete(f"/assets/{asset.id}/versions/{latest.id}").status_code == 200
    assert _live_numbers(seed, asset) == [1]


def test_delete_refuses_the_only_version_a_signed_one_and_one_in_flight(seed, as_user, owner, project, live_db):
    client = as_user(owner)
    single = seed.media(project, owner, name="single", versions=1)
    assert client.delete(f"/assets/{single.id}/versions/{seed.versions_of(single)[0].id}").status_code == 409

    signed = seed.media(project, owner, name="signed", versions=2)
    v1 = seed.versions_of(signed)[0]
    _sign_off(live_db, signed, v1)
    assert client.delete(f"/assets/{signed.id}/versions/{v1.id}").status_code == 409

    busy = seed.asset(project, owner, name="busy")
    seed.version(busy, owner, number=1)
    uploading, _ = seed.version(busy, owner, number=2, status=ProcessingStatus.processing)
    assert client.delete(f"/assets/{busy.id}/versions/{uploading.id}").status_code == 409

    assert client.delete(f"/assets/{single.id}/versions/{uuid.uuid4()}").status_code == 404
    # A version named under the wrong video is not found, not deleted.
    assert client.delete(f"/assets/{single.id}/versions/{v1.id}").status_code == 404
    assert _live_numbers(seed, signed) == [1, 2]


# ── release ───────────────────────────────────────────────────────────────────

def _comment(db, asset, version, author, body="tighten this cut"):
    comment = Comment(asset_id=asset.id, version_id=version.id, author_id=author.id, body=body)
    db.add(comment)
    db.flush()
    return comment


def test_release_makes_a_video_of_its_own_and_takes_its_records(seed, as_user, owner, project, live_db):
    folder = seed.folder(project, owner, name="Edits")
    asset = seed.media(project, owner, name="Launch film", versions=3, folder=folder)
    v2 = seed.versions_of(asset)[1]
    kept_comment = _comment(live_db, asset, seed.versions_of(asset)[2], owner, "stays")
    moved_comment = _comment(live_db, asset, v2, owner, "goes")
    live_db.add(Approval(asset_id=asset.id, version_id=v2.id, user_id=owner.id))
    live_db.add(Notification(user_id=owner.id, type=NotificationType.comment, asset_id=asset.id, comment_id=moved_comment.id))
    live_db.add(ProcessingRun(version_id=v2.id, asset_id=asset.id, attempts=1))
    live_db.flush()

    response = as_user(owner).post(f"/assets/{asset.id}/versions/{v2.id}/release", json={})
    assert response.status_code == 200
    new_id = uuid.UUID(response.json()["asset_id"])
    released = live_db.query(Asset).filter(Asset.id == new_id).one()

    assert released.name == "Launch film (v2)"
    assert (released.project_id, released.folder_id, released.status) == (project.id, folder.id, AssetStatus.draft)
    assert _live_numbers(seed, asset) == [1, 3]
    assert [(v.id, v.version_number) for v in seed.versions_of(released)] == [(v2.id, 1)]
    live_db.expire_all()
    assert live_db.get(Comment, moved_comment.id).asset_id == new_id
    assert live_db.get(Comment, kept_comment.id).asset_id == asset.id
    assert live_db.query(Approval).filter(Approval.version_id == v2.id).one().asset_id == new_id
    assert live_db.query(Notification).filter(Notification.comment_id == moved_comment.id).one().asset_id == new_id
    assert live_db.query(ProcessingRun).filter(ProcessingRun.version_id == v2.id).one().asset_id == new_id


def test_release_takes_the_name_it_is_given(seed, as_user, owner, project):
    asset = seed.media(project, owner, versions=2)
    v1 = seed.versions_of(asset)[0]
    response = as_user(owner).post(f"/assets/{asset.id}/versions/{v1.id}/release", json={"name": "  Social cut  "})
    assert response.json()["name"] == "Social cut"


def test_release_refuses_the_only_version_a_signed_video_and_one_in_flight(seed, as_user, owner, project, live_db):
    client = as_user(owner)
    single = seed.media(project, owner, name="single", versions=1)
    assert client.post(f"/assets/{single.id}/versions/{seed.versions_of(single)[0].id}/release", json={}).status_code == 409

    signed = seed.media(project, owner, name="signed", versions=2)
    _sign_off(live_db, signed, seed.versions_of(signed)[1])
    assert client.post(f"/assets/{signed.id}/versions/{seed.versions_of(signed)[0].id}/release", json={}).status_code == 409

    busy = seed.asset(project, owner, name="busy")
    seed.version(busy, owner, number=1)
    uploading, _ = seed.version(busy, owner, number=2, status=ProcessingStatus.uploading)
    assert client.post(f"/assets/{busy.id}/versions/{uploading.id}/release", json={}).status_code == 409


# ── stack ─────────────────────────────────────────────────────────────────────

def test_stacking_adds_the_other_video_as_the_newest_versions(seed, as_user, owner, project, live_db):
    target = seed.media(project, owner, name="Episode 3", versions=2)
    source = seed.media(project, owner, name="Episode 3 FINAL", versions=2)
    source_versions = seed.versions_of(source)
    comment = _comment(live_db, source, source_versions[1], owner)
    link = ShareLink(asset_id=source.id, token=f"t-{uuid.uuid4()}", created_by=owner.id)
    live_db.add(link)
    live_db.flush()

    response = as_user(owner).post(f"/assets/{target.id}/stack", json={"source_asset_id": str(source.id)})
    assert response.status_code == 200
    assert response.json()["version_numbers"] == [3, 4]

    live_db.expire_all()
    assert [(v.id, v.version_number) for v in seed.versions_of(target)][2:] == [
        (source_versions[0].id, 3), (source_versions[1].id, 4),
    ]
    assert live_db.get(Comment, comment.id).asset_id == target.id
    assert live_db.get(ShareLink, link.id).asset_id == target.id
    assert live_db.get(Asset, source.id).deleted_at is not None
    assert live_db.query(ActivityLog).filter(ActivityLog.asset_id == target.id, ActivityLog.action == "versions_stacked").count() == 1


def test_stacking_numbers_past_versions_already_in_the_trash(seed, as_user, owner, project):
    target = seed.asset(project, owner, name="target")
    seed.version(target, owner, number=1)
    seed.version(target, owner, number=2, deleted=True)
    source = seed.media(project, owner, name="source", versions=1)
    response = as_user(owner).post(f"/assets/{target.id}/stack", json={"source_asset_id": str(source.id)})
    # v2 is in the trash and still owns its number.
    assert response.json()["version_numbers"] == [3]


def test_stacking_leaves_the_sources_trashed_versions_behind(seed, as_user, owner, project):
    target = seed.media(project, owner, name="target", versions=1)
    source = seed.asset(project, owner, name="source")
    gone, _ = seed.version(source, owner, number=1, deleted=True)
    seed.version(source, owner, number=2)
    as_user(owner).post(f"/assets/{target.id}/stack", json={"source_asset_id": str(source.id)})
    assert [v.id for v in seed.versions_of(source)] == [gone.id]
    assert _live_numbers(seed, target) == [1, 2]


def test_stacking_refuses_what_it_should(seed, as_user, owner, project, live_db):
    client = as_user(owner)
    target = seed.media(project, owner, name="target", versions=1)

    def stack(source):
        return client.post(f"/assets/{target.id}/stack", json={"source_asset_id": str(source.id)}).status_code

    assert stack(target) == 422
    assert stack(seed.media(seed.project(owner, name="other"), owner, versions=1)) == 409
    assert client.post(f"/assets/{target.id}/stack", json={"source_asset_id": str(uuid.uuid4())}).status_code == 404
    assert stack(seed.asset(project, owner, name="deleted", deleted=True)) == 404

    from apps.api.models.asset import AssetType
    audio = seed.media(project, owner, name="audio", versions=1)
    audio.asset_type = AssetType.audio
    live_db.flush()
    assert stack(audio) == 409

    busy = seed.asset(project, owner, name="busy")
    seed.version(busy, owner, number=1, status=ProcessingStatus.processing)
    assert stack(busy) == 409

    empty = seed.asset(project, owner, name="empty")
    assert stack(empty) == 409

    signed_source = seed.media(project, owner, name="signed", versions=1)
    _sign_off(live_db, signed_source, seed.versions_of(signed_source)[0])
    assert stack(signed_source) == 409

    _sign_off(live_db, target, seed.versions_of(target)[0])
    assert stack(seed.media(project, owner, name="fine", versions=1)) == 409
    assert _live_numbers(seed, target) == [1]


def test_a_released_version_can_be_stacked_back(seed, as_user, owner, project, live_db):
    asset = seed.media(project, owner, name="Film", versions=3)
    v2 = seed.versions_of(asset)[1]
    client = as_user(owner)
    released_id = client.post(f"/assets/{asset.id}/versions/{v2.id}/release", json={}).json()["asset_id"]
    response = client.post(f"/assets/{asset.id}/stack", json={"source_asset_id": released_id})
    assert response.status_code == 200 and response.json()["version_numbers"] == [4]
    live_db.expire_all()
    assert _live_numbers(seed, asset) == [1, 3, 4]
