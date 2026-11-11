"""Client sign-off on a share link.

A link can ask the client to sign the video off. Signing records who agreed to
what and when, locks the asset (no new versions or comments), opens the link's
downloads with the original as the delivery, and emails the client and the
team. The project's owner can reopen it; the record is kept.
"""
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from apps.api.models.asset import AssetStatus, AssetType
from apps.api.models.sign_off import SignOff
from apps.api.services import sign_off as rules


def _link(require_sign_off=True, allow_download=False):
    link = MagicMock()
    link.id = uuid.uuid4()
    link.token = "some-token"
    link.created_by = uuid.uuid4()
    link.allow_download = allow_download
    link.require_sign_off = require_sign_off
    link.show_versions = False
    link.permission = "comment"
    return link


def _asset():
    asset = MagicMock()
    asset.id = uuid.uuid4()
    asset.name = "Hero Spot"
    asset.asset_type = AssetType.video
    asset.project_id = uuid.uuid4()
    asset.created_by = uuid.uuid4()
    asset.status = AssetStatus.in_review
    return asset


def _version(number=3):
    version = MagicMock()
    version.id = uuid.uuid4()
    version.version_number = number
    return version


def _record(asset, version_number=3, **overrides):
    fields = dict(
        id=uuid.uuid4(),
        asset_id=asset.id,
        version_id=uuid.uuid4(),
        share_link_id=uuid.uuid4(),
        asset_name=asset.name,
        version_number=version_number,
        signer_name="Carys Evans",
        signer_email="carys@client.example",
        statement=rules.sign_off_statement(asset.name, version_number),
        ip_address="203.0.113.9",
        user_agent="Browser",
        created_at=datetime(2026, 11, 11, 10, 30, tzinfo=timezone.utc),
        reopened_at=None,
        reopened_by=None,
        reopen_reason=None,
    )
    fields.update(overrides)
    return SignOff(**fields)


_BODY = {"name": "Carys Evans", "email": "carys@client.example", "agree": True}


# ─────────────────────────────────── the rules

def test_the_statement_names_the_version_and_the_asset():
    text = rules.sign_off_statement("Hero Spot", 3)
    assert "version 3" in text
    assert "Hero Spot" in text
    assert "final" in text


def test_only_a_real_record_counts_as_signed_off():
    """The check sits in front of every upload and comment. A session that hands
    back anything but a SignOff row must read as "not signed off", or an
    unrelated failure would lock every asset."""
    db = MagicMock()
    db.query.return_value.filter.return_value.order_by.return_value.first.return_value = MagicMock()
    assert rules.active_sign_off(db, uuid.uuid4()) is None

    asset = _asset()
    record = _record(asset)
    db.query.return_value.filter.return_value.order_by.return_value.first.return_value = record
    assert rules.active_sign_off(db, asset.id) is record


def test_a_signed_off_asset_refuses_changes():
    asset = _asset()
    with patch.object(rules, "active_sign_off", return_value=_record(asset)):
        with pytest.raises(HTTPException) as refused:
            rules.ensure_not_signed_off(MagicMock(), asset.id)
    assert refused.value.status_code == 409

    with patch.object(rules, "active_sign_off", return_value=None):
        rules.ensure_not_signed_off(MagicMock(), asset.id)  # no error


@pytest.mark.parametrize(
    "require_sign_off, allow_download, signed, expected",
    [
        # An ordinary link follows its own switch, signed off or not.
        (False, False, False, False),
        (False, True, False, True),
        (False, False, True, False),
        # A link that asks for a sign-off releases the file by the signature
        # alone: nothing before it, whatever the download switch says.
        (True, False, False, False),
        (True, True, False, False),
        (True, False, True, True),
        (True, True, True, True),
    ],
)
def test_when_a_share_link_may_hand_out_a_download(require_sign_off, allow_download, signed, expected):
    asset = _asset()
    link = _link(require_sign_off=require_sign_off, allow_download=allow_download)
    with patch.object(rules, "active_sign_off", return_value=_record(asset) if signed else None):
        assert rules.share_download_allowed(MagicMock(), link, asset) is expected


# ─────────────────────────────────── signing, on the share link

def _sign(client, asset, body=None):
    return client.post(f"/share/some-token/sign-off/{asset.id}", json=body or _BODY)


@patch("apps.api.routers.sign_off.validate_share_link_with_session")
def test_a_link_that_does_not_ask_for_it_cannot_be_signed(mock_validate, client, mock_db):
    mock_validate.return_value = _link(require_sign_off=False)
    response = _sign(client, _asset())
    assert response.status_code == 403
    mock_db.add.assert_not_called()


@patch("apps.api.routers.sign_off.validate_share_link_with_session")
def test_signing_needs_the_box_ticked(mock_validate, client, mock_db):
    mock_validate.return_value = _link()
    response = _sign(client, _asset(), {**_BODY, "agree": False})
    assert response.status_code == 400
    mock_db.add.assert_not_called()


@pytest.mark.parametrize("body", [
    {**_BODY, "name": " "},
    {**_BODY, "email": "not-an-email"},
    {"name": "Carys Evans", "email": "carys@client.example"},  # no tick at all
])
@patch("apps.api.routers.sign_off.validate_share_link_with_session")
def test_a_sign_off_needs_a_name_an_email_and_the_tick(mock_validate, body, client, mock_db):
    mock_validate.return_value = _link()
    response = _sign(client, _asset(), body)
    assert response.status_code == 422
    mock_db.add.assert_not_called()


@patch("apps.api.routers.sign_off.active_sign_off")
@patch("apps.api.routers.sign_off._get_asset")
@patch("apps.api.routers.sign_off.validate_asset_in_share")
@patch("apps.api.routers.sign_off.validate_share_link_with_session")
def test_an_asset_cannot_be_signed_off_twice(
    mock_validate, mock_in_share, mock_get_asset, mock_active, client, mock_db,
):
    asset = _asset()
    mock_validate.return_value = _link()
    mock_get_asset.return_value = asset
    mock_active.return_value = _record(asset)

    response = _sign(client, asset)

    assert response.status_code == 409
    mock_db.add.assert_not_called()


@patch("apps.api.routers.sign_off.event_service")
@patch("apps.api.routers.sign_off.send_task_safe")
@patch("apps.api.routers.sign_off._version_to_sign")
@patch("apps.api.routers.sign_off.active_sign_off")
@patch("apps.api.routers.sign_off._get_asset")
@patch("apps.api.routers.sign_off.validate_asset_in_share")
@patch("apps.api.routers.sign_off.validate_share_link_with_session")
def test_signing_records_it_locks_the_asset_and_emails_everyone(
    mock_validate, mock_in_share, mock_get_asset, mock_active, mock_version,
    mock_send, mock_events, client, mock_db,
):
    asset = _asset()
    link = _link()
    version = _version(3)
    mock_validate.return_value = link
    mock_get_asset.return_value = asset
    mock_version.return_value = version
    added = []
    mock_db.add.side_effect = added.append

    # Not signed off when the request arrives; signed off once the row is in.
    def _active(db, asset_id):
        return next((r for r in added if isinstance(r, SignOff)), None)
    mock_active.side_effect = _active

    member = MagicMock()
    member.email = "james@studio.example"
    mock_db.all.return_value = [member]

    response = client.post(
        f"/share/some-token/sign-off/{asset.id}",
        json=_BODY,
        headers={"X-Real-IP": "203.0.113.9", "User-Agent": "TestBrowser/1.0"},
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["signed_off"] is True
    assert body["signer_name"] == "Carys Evans"
    assert body["version_number"] == 3
    assert "signer_email" not in body  # the share page never echoes an address

    record = next(r for r in added if isinstance(r, SignOff))
    assert record.asset_id == asset.id
    assert record.version_id == version.id
    assert record.share_link_id == link.id
    assert record.signer_name == "Carys Evans"
    assert record.signer_email == "carys@client.example"
    assert record.statement == rules.sign_off_statement("Hero Spot", 3)
    assert record.ip_address == "203.0.113.9"
    assert record.user_agent == "TestBrowser/1.0"
    assert asset.status == AssetStatus.approved

    sent = {call.args[0].name.rsplit(".", 1)[-1]: call.kwargs for call in mock_send.call_args_list}
    client_mail = sent["send_sign_off_confirmation_email"]
    assert client_mail["to_email"] == "carys@client.example"
    assert client_mail["share_url"].endswith("/share/some-token")
    assert client_mail["statement"] == record.statement
    team_mail = sent["send_sign_off_team_email"]
    assert team_mail["to_email"] == "james@studio.example"
    assert team_mail["signer_email"] == "carys@client.example"


@patch("apps.api.routers.sign_off._version_to_sign")
@patch("apps.api.routers.sign_off.active_sign_off")
@patch("apps.api.routers.sign_off._get_asset")
@patch("apps.api.routers.sign_off.validate_asset_in_share")
@patch("apps.api.routers.sign_off.validate_share_link_with_session")
def test_the_share_page_can_read_the_state_without_the_signers_email(
    mock_validate, mock_in_share, mock_get_asset, mock_active, mock_version, client, mock_db,
):
    asset = _asset()
    mock_validate.return_value = _link()
    mock_get_asset.return_value = asset
    mock_version.return_value = _version(3)

    mock_active.return_value = None
    waiting = client.get(f"/share/some-token/sign-off/{asset.id}").json()
    assert waiting["required"] is True
    assert waiting["signed_off"] is False
    assert waiting["statement"] == rules.sign_off_statement("Hero Spot", 3)

    mock_active.return_value = _record(asset)
    signed = client.get(f"/share/some-token/sign-off/{asset.id}").json()
    assert signed["signed_off"] is True
    assert signed["signer_name"] == "Carys Evans"
    assert "carys@client.example" not in str(signed)


# ─────────────────────────────────── what signing unlocks: the download

def _media_file():
    media = MagicMock()
    media.version_id = uuid.uuid4()
    media.s3_key_raw = "raw/p/a/v/original.mov"
    media.s3_key_processed = "processed/p/a/v"
    media.s3_key_download = "processed/p/a/v/download.mp4"
    media.s3_key_thumbnail = None
    media.original_filename = "Hero Spot.mov"
    media.file_size_bytes = 5_000_000_000
    media.duration_seconds = 12.0
    return media


@patch("apps.api.routers.share.share_download_allowed", return_value=False)
@patch("apps.api.routers.share._get_asset")
@patch("apps.api.routers.share.validate_asset_in_share")
@patch("apps.api.routers.share.validate_share_link_with_session")
def test_nothing_can_be_downloaded_before_the_sign_off(
    mock_validate, mock_in_share, mock_get_asset, mock_allowed, client, mock_db,
):
    asset = _asset()
    # Even with the link's own download switch on.
    mock_validate.return_value = _link(require_sign_off=True, allow_download=True)
    mock_get_asset.return_value = asset

    listing = client.get(f"/share/some-token/downloads/{asset.id}")
    download = client.get(f"/share/some-token/stream/{asset.id}?download=true")

    assert listing.status_code == 403
    assert download.status_code == 403
    assert "signed off" in download.json()["detail"]


@patch("apps.api.routers.share._log_share_activity")
@patch("apps.api.routers.share.generate_presigned_get_url")
@patch("apps.api.routers.share._get_latest_media_file")
@patch("apps.api.routers.share.sign_off_unlocks_download", return_value=True)
@patch("apps.api.routers.share.share_download_allowed", return_value=True)
@patch("apps.api.routers.share._get_asset")
@patch("apps.api.routers.share.validate_asset_in_share")
@patch("apps.api.routers.share.validate_share_link_with_session")
def test_a_signed_off_video_downloads_as_its_original(
    mock_validate, mock_in_share, mock_get_asset, mock_allowed, mock_unlocks,
    mock_latest, mock_presign, mock_log, client, mock_db,
):
    """The original is the delivery, even where the instance keeps originals
    from share-link visitors, and without the client having to ask for it."""
    asset = _asset()
    mock_validate.return_value = _link(require_sign_off=True, allow_download=False)
    mock_get_asset.return_value = asset
    mock_latest.return_value = _media_file()
    mock_presign.return_value = "https://s3.example.com/original.mov?sig=x"

    with patch("apps.api.services.downloads.get_allow_original_downloads", return_value=False):
        response = client.get(f"/share/some-token/stream/{asset.id}?download=true")

    assert response.status_code == 200, response.text
    assert mock_presign.call_args_list[0][0][0] == "raw/p/a/v/original.mov"
    assert mock_log.call_args.kwargs["rendition"] == "original"


# ─────────────────────────────────── what signing locks

@patch("apps.api.routers.comments.ensure_not_signed_off")
@patch("apps.api.routers.comments._get_asset")
@patch("apps.api.routers.comments.validate_asset_in_share")
@patch("apps.api.routers.comments.validate_share_link_with_session")
def test_a_signed_off_asset_takes_no_more_comments_from_the_link(
    mock_validate, mock_in_share, mock_get_asset, mock_ensure, client, mock_db,
):
    asset = _asset()
    link = _link()
    link.asset_id = asset.id
    mock_validate.return_value = link
    mock_get_asset.return_value = asset
    mock_ensure.side_effect = HTTPException(status_code=409, detail=rules.SIGNED_OFF_DETAIL)

    response = client.post(
        "/share/some-token/comment",
        json={"body": "One more thing", "guest_name": "Carys", "guest_email": "carys@client.example"},
    )

    assert response.status_code == 409
    mock_ensure.assert_called_once_with(mock_db, asset.id)
    mock_db.add.assert_not_called()


@patch("apps.api.routers.upload.ensure_not_signed_off")
@patch("apps.api.routers.upload.require_project_role")
@patch("apps.api.routers.upload.choose_part_size", return_value=(10 * 1024 * 1024, None))
@patch("apps.api.routers.upload.upload_guard_error", return_value=None)
def test_a_signed_off_asset_takes_no_new_version(
    mock_guard, mock_parts, mock_role, mock_ensure, client, mock_db, auth_headers,
):
    asset = _asset()
    mock_db.first.side_effect = [MagicMock(), asset]  # the project, then the asset
    mock_ensure.side_effect = HTTPException(status_code=409, detail=rules.SIGNED_OFF_DETAIL)

    response = client.post(
        "/upload/initiate",
        headers=auth_headers,
        json={
            "project_id": str(asset.project_id),
            "asset_id": str(asset.id),
            "asset_name": "Hero Spot",
            "original_filename": "hero-v4.mov",
            "mime_type": "video/quicktime",
            "file_size_bytes": 1024,
        },
    )

    assert response.status_code == 409, response.text
    mock_ensure.assert_called_once_with(mock_db, asset.id)


# ─────────────────────────────────── the team's side

@patch("apps.api.routers.sign_off.active_sign_off")
@patch("apps.api.routers.sign_off.require_project_role")
@patch("apps.api.routers.sign_off._get_asset")
def test_only_the_owner_can_reopen(mock_get_asset, mock_role, mock_active, client, mock_db, auth_headers):
    asset = _asset()
    mock_get_asset.return_value = asset
    mock_role.side_effect = HTTPException(status_code=403, detail="Requires owner role or higher")

    response = client.post(f"/assets/{asset.id}/sign-off/reopen", headers=auth_headers, json={})

    assert response.status_code == 403
    from apps.api.models.project import ProjectRole
    assert mock_role.call_args.args[3] == ProjectRole.owner
    mock_active.assert_not_called()


@patch("apps.api.routers.sign_off.event_service")
@patch("apps.api.routers.sign_off.require_asset_access")
@patch("apps.api.routers.sign_off.active_sign_off")
@patch("apps.api.routers.sign_off.require_project_role")
@patch("apps.api.routers.sign_off._get_asset")
def test_reopening_unlocks_and_keeps_the_record(
    mock_get_asset, mock_role, mock_active, mock_access, mock_events,
    client, mock_db, auth_headers, test_user,
):
    asset = _asset()
    asset.status = AssetStatus.approved
    record = _record(asset)
    mock_get_asset.return_value = asset
    mock_active.return_value = record
    mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [record]

    response = client.post(
        f"/assets/{asset.id}/sign-off/reopen",
        headers=auth_headers,
        json={"reason": "Client asked for a new end card"},
    )

    assert response.status_code == 200, response.text
    assert record.reopened_at is not None
    assert record.reopened_by == test_user.id
    assert record.reopen_reason == "Client asked for a new end card"
    assert asset.status == AssetStatus.in_review
    body = response.json()
    assert body["signed_off"] is False
    assert body["current"] is None
    # Still on file, with who signed and why it was reopened.
    assert body["history"][0]["signer_email"] == "carys@client.example"
    assert body["history"][0]["reopen_reason"] == "Client asked for a new end card"


@patch("apps.api.routers.sign_off.active_sign_off", return_value=None)
@patch("apps.api.routers.sign_off.require_project_role")
@patch("apps.api.routers.sign_off._get_asset")
def test_there_is_nothing_to_reopen_on_an_unsigned_asset(
    mock_get_asset, mock_role, mock_active, client, mock_db, auth_headers,
):
    mock_get_asset.return_value = _asset()
    response = client.post(f"/assets/{uuid.uuid4()}/sign-off/reopen", headers=auth_headers, json={})
    assert response.status_code == 409
