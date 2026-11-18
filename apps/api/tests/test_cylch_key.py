"""Cylch connects with a key, and the key opens the Cylch routes and nothing else.

Cylch (the studio's project app) sends a client's logo and colours to the
project they are reviewed in. It could do that signed in as an account, but an
account can do everything its role allows. The key is the narrow version: an
administrator makes it, only its hash is stored, and it is accepted only by
routers/cylch.py. These tests hold that line from both sides: the key does not
work as a session, and a session does not work as the key.
"""
import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

import apps.api.routers.cylch as cylch
from apps.api.models.instance_settings import InstanceSettings
from apps.api.models.project import Project
from apps.api.models.user import User, UserStatus

KEY = cylch.KEY_PREFIX + "k" * 43
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def _settings(key: str | None = KEY, made_by=None, used_at=None):
    return MagicMock(
        cylch_key_hash=hashlib.sha256(key.encode()).hexdigest() if key else None,
        cylch_key_made_by=made_by, cylch_key_made_at=datetime.now(timezone.utc), cylch_key_used_at=used_at,
    )


def _project(pid=None, name="Brand film"):
    p = MagicMock(spec=Project)
    p.id, p.name, p.deleted_at = pid or uuid.uuid4(), name, None
    return p


def _branding(pid, logo=None):
    return MagicMock(project_id=pid, primary_color=None, secondary_color=None, logo_s3_key=logo, use_cover_as_logo=True)


def _key(key: str = KEY):
    return {"Authorization": f"Bearer {key}"}


def test_the_columns_start_empty_so_an_upgrade_switches_nothing_on():
    cols = InstanceSettings.__table__.columns
    for name in ("cylch_key_hash", "cylch_key_made_by", "cylch_key_made_at", "cylch_key_used_at"):
        assert (cols[name].nullable, cols[name].server_default, cols[name].default) == (True, None, None)


@pytest.mark.parametrize("headers", [
    {},                                             # nothing
    {"Authorization": "Bearer " + cylch.KEY_PREFIX + "wrong"},
    {"Authorization": "Basic " + KEY},              # the right key, the wrong scheme
])
def test_without_the_key_the_routes_are_closed(client, mock_db, headers):
    mock_db.first.return_value = _settings()
    assert client.get("/integrations/cylch/projects", headers=headers).status_code == 401


def test_with_no_key_made_nothing_is_accepted(client, mock_db):
    # The integration is off until an administrator makes a key: a NULL hash
    # must not match anything, including an empty key.
    mock_db.first.return_value = _settings(key=None)
    assert client.get("/integrations/cylch/projects", headers=_key()).status_code == 401
    assert client.get("/integrations/cylch/projects", headers=_key(cylch.KEY_PREFIX)).status_code == 401


def test_a_signed_in_session_is_not_the_key(client, auth_headers, mock_db, test_user):
    # Even an administrator's session: the key is the only thing these routes take.
    test_user.is_superadmin = True
    mock_db.first.return_value = _settings()
    assert client.get("/integrations/cylch/projects", headers=auth_headers).status_code == 401


def test_the_key_is_not_a_session(client, mock_db):
    # The other half: a key gets nobody into the rest of the API.
    mock_db.first.return_value = _settings()
    assert client.get("/projects", headers=_key()).status_code == 401
    assert client.get("/auth/me", headers=_key()).status_code == 401


def test_only_an_administrator_makes_or_removes_the_key(client, auth_headers, mock_db, test_user):
    test_user.is_superadmin = False
    mock_db.first.return_value = _settings(key=None)
    assert client.get("/integrations/cylch", headers=auth_headers).status_code == 403
    assert client.post("/integrations/cylch/key", headers=auth_headers).status_code == 403
    assert client.delete("/integrations/cylch/key", headers=auth_headers).status_code == 403


def test_making_a_key_shows_it_once_and_stores_only_its_hash(client, auth_headers, mock_db, test_user):
    test_user.is_superadmin = True
    row = _settings(key=None)
    mock_db.first.return_value = row

    r = client.post("/integrations/cylch/key", headers=auth_headers)
    assert r.status_code == 201
    key = r.json()["key"]

    assert key.startswith(cylch.KEY_PREFIX) and len(key) > len(cylch.KEY_PREFIX) + 40
    assert row.cylch_key_hash == hashlib.sha256(key.encode()).hexdigest()
    assert key not in row.cylch_key_hash
    assert row.cylch_key_made_by == test_user.id
    # And it cannot be read back afterwards.
    assert "key" not in client.get("/integrations/cylch", headers=auth_headers).json()


def test_removing_the_key_switches_the_integration_off(client, auth_headers, mock_db, test_user):
    test_user.is_superadmin = True
    row = _settings()
    mock_db.first.return_value = row
    assert client.delete("/integrations/cylch/key", headers=auth_headers).status_code == 204
    assert row.cylch_key_hash is None
    assert client.get("/integrations/cylch/projects", headers=_key()).status_code == 401


def test_the_key_lists_projects_and_notes_that_it_was_used(client, mock_db):
    row = _settings(used_at=datetime.now(timezone.utc) - timedelta(hours=1))
    before = row.cylch_key_used_at
    mock_db.first.return_value = row
    mock_db.order_by.return_value = mock_db
    mock_db.all.return_value = [_project(name="A film"), _project(name="B film")]

    r = client.get("/integrations/cylch/projects", headers=_key())

    assert r.status_code == 200
    assert [p["name"] for p in r.json()] == ["A film", "B film"]
    assert set(r.json()[0]) == {"id", "name"}   # names to pick from, nothing more
    assert row.cylch_key_used_at > before


def test_colours_are_set_and_a_colour_that_is_not_one_is_refused(client, mock_db):
    pid = uuid.uuid4()
    branding = _branding(pid)
    mock_db.first.side_effect = [_settings(), _project(pid), branding]

    r = client.put(f"/integrations/cylch/projects/{pid}/branding", headers=_key(),
                   json={"primary_color": "#cb2c30", "secondary_color": None})
    assert r.status_code == 200
    assert (branding.primary_color, branding.secondary_color) == ("#cb2c30", None)

    mock_db.first.side_effect = [_settings(), _project(pid), branding]
    r = client.put(f"/integrations/cylch/projects/{pid}/branding", headers=_key(), json={"primary_color": "red"})
    assert r.status_code == 422


def test_branding_for_a_project_that_is_gone_is_a_404(client, mock_db):
    mock_db.first.side_effect = [_settings(), None]
    r = client.put(f"/integrations/cylch/projects/{uuid.uuid4()}/branding", headers=_key(), json={"primary_color": "#000000"})
    assert r.status_code == 404


def test_a_logo_is_stored_under_the_projects_own_prefix_and_replaces_the_old_one(client, mock_db, monkeypatch):
    pid = uuid.uuid4()
    old = f"branding/{pid}/logo/old.webp"
    branding = _branding(pid, logo=old)
    mock_db.first.side_effect = [_settings(), _project(pid), branding]
    put, delete = MagicMock(), MagicMock()
    monkeypatch.setattr(cylch.s3_service, "put_object", put)
    monkeypatch.setattr(cylch.s3_service, "delete_object", delete)

    r = client.put(f"/integrations/cylch/projects/{pid}/logo", headers={**_key(), "Content-Type": "image/webp"}, content=PNG)

    assert r.status_code == 200 and r.json()["has_logo"] is True
    key = put.call_args.args[0]
    # The type comes from the bytes, not from the header that claimed WebP.
    assert key.startswith(f"branding/{pid}/logo/") and key.endswith(".png")
    assert put.call_args.kwargs["content_type"] == "image/png"
    assert branding.logo_s3_key == key and branding.use_cover_as_logo is False
    delete.assert_called_once_with(old)


@pytest.mark.parametrize("body,status", [
    (b"<svg onload=alert(1)>", 415),                       # not a picture we serve back
    (b"\x89PNG\r\n\x1a\n" + b"\x00" * (cylch.MAX_LOGO_BYTES + 1), 413),
])
def test_a_logo_that_is_not_a_small_picture_is_refused_and_nothing_is_stored(client, mock_db, monkeypatch, body, status):
    pid = uuid.uuid4()
    mock_db.first.side_effect = [_settings(), _project(pid), _branding(pid)]
    put = MagicMock()
    monkeypatch.setattr(cylch.s3_service, "put_object", put)
    r = client.put(f"/integrations/cylch/projects/{pid}/logo", headers=_key(), content=body)
    assert r.status_code == status
    put.assert_not_called()


def test_a_project_cylch_makes_belongs_to_whoever_made_the_key(client, mock_db):
    owner = MagicMock(spec=User)
    owner.id, owner.deleted_at, owner.status = uuid.uuid4(), None, UserStatus.active
    mock_db.first.side_effect = [_settings(made_by=owner.id), owner]
    added = []
    mock_db.add.side_effect = added.append

    def _refresh(obj):
        obj.id = obj.id or uuid.uuid4()
    mock_db.flush.side_effect = lambda: [setattr(o, "id", o.id or uuid.uuid4()) for o in added]
    mock_db.refresh.side_effect = _refresh

    r = client.post("/integrations/cylch/projects", headers=_key(), json={"name": "Scarlets | S2E1"})

    assert r.status_code == 201 and r.json()["name"] == "Scarlets | S2E1"
    project, member = added
    assert project.created_by == owner.id
    assert (member.user_id, member.role.value) == (owner.id, "owner")


def test_a_key_whose_maker_has_gone_cannot_make_projects(client, mock_db):
    mock_db.first.side_effect = [_settings(made_by=uuid.uuid4()), None]
    r = client.post("/integrations/cylch/projects", headers=_key(), json={"name": "x"})
    assert r.status_code == 409
    mock_db.add.assert_not_called()
