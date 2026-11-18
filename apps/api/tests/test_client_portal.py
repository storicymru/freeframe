"""The client portal.

A client account sees its own library and nothing else in the app. The team
invites clients per project; a client signs in by a one-time link, then by
emailed code. What a client can do to an asset runs on the project's portal
link through the share routes, so the tests here are mostly about who gets in
and what they can reach.
"""
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from apps.api.models.asset import AssetStatus, AssetType
from apps.api.models.portal import ProjectClient
from apps.api.models.sign_off import SignOff
from apps.api.models.user import User, UserStatus
from apps.api.services import portal as rules
from apps.api.services import sign_off as sign_off_rules


def _user(is_client=False, **overrides):
    user = MagicMock()
    user.id = uuid.uuid4()
    user.email = "carys@client.example" if is_client else "james@studio.example"
    user.name = "Carys Evans" if is_client else "James Owen"
    user.is_client = is_client
    user.is_superadmin = False
    user.status = UserStatus.active
    user.deleted_at = None
    user.token_version = 1
    user.email_verified = True
    user.invite_token = None
    user.invite_token_expires_at = None
    for key, value in overrides.items():
        setattr(user, key, value)
    return user


def _portal_link(project_id=None):
    link = MagicMock()
    link.id = uuid.uuid4()
    link.token = "portal-token"
    link.project_id = project_id or uuid.uuid4()
    link.folder_id = None
    link.asset_id = None
    link.is_portal = True
    link.require_sign_off = True
    link.allow_download = False
    link.visibility = "secure"
    link.password_hash = None
    link.show_versions = False
    link.created_by = uuid.uuid4()
    return link


def _asset(status=AssetStatus.in_review, project_id=None):
    asset = MagicMock()
    asset.id = uuid.uuid4()
    asset.name = "Hero Spot"
    asset.asset_type = AssetType.video
    asset.project_id = project_id or uuid.uuid4()
    asset.folder_id = None
    asset.created_by = uuid.uuid4()
    asset.status = status
    return asset


# ─────────────────────────────────── a client account reaches the portal and nothing else

@pytest.mark.parametrize("path, allowed", [
    ("/portal", True),
    ("/auth/me", True),
    ("/auth/refresh", True),
    ("/share/some-token/stream/abc", True),
    ("/share/some-token/sign-off/abc", True),
    ("/stream/hls/master.m3u8", True),
    ("/instance/branding", True),
    # The rest of the app, including routes that only ask for "signed in".
    ("/projects", False),
    ("/projects/123/members", False),
    ("/users/search", False),
    ("/assets/123", False),
    ("/upload/initiate", False),
    ("/me/assets", False),
    ("/admin/users", False),
    ("/portalx", False),
])
def test_what_a_client_account_may_call(path, allowed):
    assert rules.client_may_call(path) is allowed


def _current_user(user, path):
    from apps.api.middleware import auth

    request = MagicMock()
    request.url.path = path
    credentials = MagicMock()
    credentials.credentials = "token"
    with patch.object(auth, "decode_token", return_value={"type": "access", "sub": str(user.id)}), \
         patch.object(auth, "get_user_by_id", return_value=user):
        return auth.get_current_user(credentials, MagicMock(), request)


def test_a_client_is_refused_everywhere_but_the_portal():
    client_user = _user(is_client=True)
    assert _current_user(client_user, "/portal") is client_user
    for path in ("/projects", "/users/search", "/assets/123/comments", "/upload/initiate"):
        with pytest.raises(HTTPException) as refused:
            _current_user(client_user, path)
        assert refused.value.status_code == 403


def test_a_team_account_is_not_touched_by_the_client_rule():
    member = _user(is_client=False)
    for path in ("/projects", "/users/search", "/portal"):
        assert _current_user(member, path) is member


# ─────────────────────────────────── who may open a project's portal link

def test_the_portal_link_needs_a_signed_in_client_or_member_of_that_project():
    link = _portal_link()
    client_user = _user(is_client=True)

    with pytest.raises(HTTPException) as anonymous:
        rules.require_portal_access(MagicMock(), link, None)
    assert anonymous.value.status_code == 403

    with patch.object(rules, "is_project_client", return_value=True):
        rules.require_portal_access(MagicMock(), link, client_user)  # their project: in

    with patch.object(rules, "is_project_client", return_value=False), \
         patch("apps.api.services.permissions.get_project_member", return_value=None):
        with pytest.raises(HTTPException) as other:
            # A client of a different project, holding this project's token.
            rules.require_portal_access(MagicMock(), link, client_user)
    assert other.value.status_code == 403

    with patch.object(rules, "is_project_client", return_value=False), \
         patch("apps.api.services.permissions.get_project_member", return_value=MagicMock()):
        rules.require_portal_access(MagicMock(), link, _user())  # the team can look


def test_only_a_real_row_makes_someone_a_client_of_a_project():
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = MagicMock()
    assert rules.is_project_client(db, uuid.uuid4(), uuid.uuid4()) is False
    db.query.return_value.filter.return_value.first.return_value = ProjectClient(
        project_id=uuid.uuid4(), user_id=uuid.uuid4(),
    )
    assert rules.is_project_client(db, uuid.uuid4(), uuid.uuid4()) is True


@patch("apps.api.services.permissions.validate_share_link")
def test_every_share_route_checks_portal_access(mock_validate):
    from apps.api.services.permissions import validate_share_link_with_session

    link = _portal_link()
    mock_validate.return_value = link
    stranger = _user(is_client=True)
    with patch("apps.api.services.portal.is_project_client", return_value=False), \
         patch("apps.api.services.permissions.get_project_member", return_value=None):
        with pytest.raises(HTTPException) as refused:
            validate_share_link_with_session(MagicMock(), "portal-token", current_user=stranger)
    assert refused.value.status_code == 403


# ─────────────────────────────────── what a client sees: nothing in draft

@pytest.mark.parametrize("status, visible", [
    (AssetStatus.draft, False),
    (AssetStatus.in_review, True),
    (AssetStatus.rejected, True),
    (AssetStatus.approved, True),
    (AssetStatus.archived, True),
])
def test_a_client_sees_everything_but_drafts(status, visible):
    asset = _asset(status)
    if visible:
        rules.require_client_visible(asset)
    else:
        with pytest.raises(HTTPException) as hidden:
            rules.require_client_visible(asset)
        assert hidden.value.status_code == 404


def test_a_draft_cannot_be_reached_through_the_portal_link_by_its_id():
    from apps.api.services.permissions import validate_asset_in_share

    link = _portal_link()
    draft = _asset(AssetStatus.draft, project_id=link.project_id)
    with pytest.raises(HTTPException) as hidden:
        validate_asset_in_share(MagicMock(), link, draft)
    assert hidden.value.status_code == 404


@patch("apps.api.routers.share.validate_share_link_with_session")
def test_the_portal_link_cannot_list_the_whole_project(mock_validate, client, mock_db):
    """The share listing knows nothing of the draft filter; the portal lists
    a client's assets itself."""
    mock_validate.return_value = _portal_link()
    response = client.get("/share/portal-token/assets")
    assert response.status_code == 403


# ─────────────────────────────────── downloads in the portal

@pytest.mark.parametrize("status, signed, expected", [
    (AssetStatus.in_review, False, False),   # still in review: nothing to take away
    (AssetStatus.rejected, False, False),
    (AssetStatus.approved, True, True),      # signed off here
    (AssetStatus.approved, False, True),     # delivered by the team, never signed here
    (AssetStatus.archived, False, True),     # historic work
])
def test_delivered_work_downloads_from_the_portal(status, signed, expected):
    link = _portal_link()
    asset = _asset(status)
    record = SignOff(asset_id=asset.id) if signed else None
    with patch.object(sign_off_rules, "active_sign_off", return_value=record):
        assert sign_off_rules.share_download_allowed(MagicMock(), link, asset) is expected
        # And what it releases is the original.
        assert sign_off_rules.sign_off_unlocks_download(MagicMock(), link, asset) is expected


def test_an_ordinary_sign_off_link_is_not_opened_by_a_status_alone():
    """Only the portal treats "approved" as delivered. A team member marking an
    asset approved must not open the download on a client's sign-off link."""
    link = _portal_link()
    link.is_portal = False
    with patch.object(sign_off_rules, "active_sign_off", return_value=None):
        assert sign_off_rules.share_download_allowed(MagicMock(), link, _asset(AssetStatus.approved)) is False


# ─────────────────────────────────── inviting a client

_INVITE = {"name": "Carys Evans", "email": "Carys@Client.Example"}


@patch("apps.api.routers.portal.send_task_safe")
@patch("apps.api.routers.portal.get_or_create_portal_link")
@patch("apps.api.routers.portal.get_email_owner", return_value=None)
@patch("apps.api.routers.portal._live_project")
@patch("apps.api.routers.portal.require_project_role")
def test_inviting_makes_a_client_account_and_emails_a_sign_in_link(
    mock_role, mock_project, mock_owner, mock_link, mock_send, client, mock_db, auth_headers,
):
    project = MagicMock()
    project.id = uuid.uuid4()
    project.name = "Swansea Bay City Deal"
    mock_project.return_value = project
    added = []
    mock_db.add.side_effect = added.append

    def _refresh(obj):
        if isinstance(obj, User) and obj.id is None:
            obj.id = uuid.uuid4()
    mock_db.refresh.side_effect = _refresh
    mock_db.flush.side_effect = lambda: [setattr(o, "id", uuid.uuid4()) for o in added if isinstance(o, User) and o.id is None]

    response = client.post(f"/projects/{project.id}/clients", headers=auth_headers, json=_INVITE)

    assert response.status_code == 201, response.text
    new_user = next(o for o in added if isinstance(o, User))
    assert new_user.is_client is True
    assert new_user.email == "carys@client.example"  # stored lowercase
    assert new_user.status == UserStatus.active
    assert new_user.password_hash is None
    row = next(o for o in added if isinstance(o, ProjectClient))
    assert row.project_id == project.id and row.user_id == new_user.id

    body = response.json()
    assert body["has_signed_in"] is False
    assert "/portal/enter/" in body["portal_link"]
    sent = mock_send.call_args.kwargs
    assert sent["to_email"] == "carys@client.example"
    assert sent["project_name"] == "Swansea Bay City Deal"
    assert sent["portal_link"] == body["portal_link"]


@patch("apps.api.routers.portal.send_task_safe")
@patch("apps.api.routers.portal.get_email_owner")
@patch("apps.api.routers.portal._live_project")
@patch("apps.api.routers.portal.require_project_role")
def test_a_team_account_cannot_be_made_a_client(
    mock_role, mock_project, mock_owner, mock_send, client, mock_db, auth_headers,
):
    """Turning a team login into a client account would lock them out of the app."""
    mock_owner.return_value = _user(is_client=False)
    response = client.post(f"/projects/{uuid.uuid4()}/clients", headers=auth_headers, json=_INVITE)
    assert response.status_code == 400
    assert "team account" in response.json()["detail"]
    mock_db.add.assert_not_called()
    mock_send.assert_not_called()


@patch("apps.api.routers.portal.require_project_role")
def test_inviting_needs_an_editor_of_the_project(mock_role, client, mock_db, auth_headers):
    mock_role.side_effect = HTTPException(status_code=403, detail="Requires editor role or higher")
    response = client.post(f"/projects/{uuid.uuid4()}/clients", headers=auth_headers, json=_INVITE)
    assert response.status_code == 403
    mock_db.add.assert_not_called()


# ─────────────────────────────────── the one-time sign-in link

def _exchange(client, mock_db, user):
    mock_db.query.return_value.filter.return_value.first.return_value = user
    mock_db.first.return_value = user
    return client.post("/auth/client-link", json={"token": "a-long-one-time-token"})


def test_the_invite_link_signs_a_client_in_once(client, mock_db):
    user = _user(
        is_client=True, email_verified=False, invite_token="a-long-one-time-token",
        invite_token_expires_at=datetime.now(timezone.utc) + timedelta(days=3),
    )
    response = _exchange(client, mock_db, user)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["access_token"] and body["refresh_token"]
    assert body["needs_password"] is False
    # Spent: the same link signs nobody in again.
    assert user.invite_token is None
    assert user.email_verified is True


@pytest.mark.parametrize("overrides", [
    {"is_client": False},                                                      # a team invite token is not a sign-in link
    {"status": UserStatus.deactivated},
    {"invite_token_expires_at": datetime.now(timezone.utc) - timedelta(minutes=1)},
])
def test_a_link_that_should_not_work_signs_nobody_in(overrides, client, mock_db):
    fields = dict(is_client=True, invite_token="a-long-one-time-token",
                  invite_token_expires_at=datetime.now(timezone.utc) + timedelta(days=3))
    fields.update(overrides)
    response = _exchange(client, mock_db, _user(**fields))
    assert response.status_code == 404
    assert "access_token" not in response.json()


def test_an_unknown_link_signs_nobody_in(client, mock_db):
    response = _exchange(client, mock_db, None)
    assert response.status_code == 404


# ─────────────────────────────────── the home page, and signing off while signed in

def test_the_portal_home_is_for_client_accounts(client, mock_db, auth_headers, test_user):
    test_user.is_client = False
    response = client.get("/portal", headers=auth_headers)
    assert response.status_code == 403


@patch("apps.api.routers.sign_off.event_service")
@patch("apps.api.routers.sign_off.send_task_safe")
@patch("apps.api.routers.sign_off._version_to_sign")
@patch("apps.api.routers.sign_off.active_sign_off")
@patch("apps.api.routers.sign_off._get_asset")
@patch("apps.api.routers.sign_off.validate_asset_in_share")
@patch("apps.api.routers.sign_off.validate_share_link_with_session")
def test_a_signed_in_client_signs_as_their_account_not_as_what_was_typed(
    mock_validate, mock_in_share, mock_get_asset, mock_active, mock_version,
    mock_send, mock_events, client, mock_db,
):
    from apps.api.main import app
    from apps.api.middleware.auth import get_optional_user

    client_user = _user(is_client=True)
    asset = _asset()
    link = _portal_link(asset.project_id)
    version = MagicMock()
    version.id = uuid.uuid4()
    version.version_number = 2
    mock_validate.return_value = link
    mock_get_asset.return_value = asset
    mock_version.return_value = version
    added = []
    mock_db.add.side_effect = added.append
    mock_active.side_effect = lambda db, asset_id: next((r for r in added if isinstance(r, SignOff)), None)

    app.dependency_overrides[get_optional_user] = lambda: client_user
    try:
        response = client.post(
            f"/share/portal-token/sign-off/{asset.id}",
            json={"name": "Somebody Else", "email": "other@example.com", "agree": True},
        )
    finally:
        app.dependency_overrides.pop(get_optional_user, None)

    assert response.status_code == 201, response.text
    record = next(r for r in added if isinstance(r, SignOff))
    assert record.signer_name == "Carys Evans"
    assert record.signer_email == "carys@client.example"
    assert record.signer_user_id == client_user.id
    client_mail = next(c.kwargs for c in mock_send.call_args_list if "share_url" in c.kwargs)
    assert client_mail["to_email"] == "carys@client.example"
    assert client_mail["share_url"].endswith("/portal")
