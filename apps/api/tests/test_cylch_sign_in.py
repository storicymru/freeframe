"""Cylch is where the team is kept, and this app follows it.

One list of staff, Cylch's. Everyone on it has an account here with the role
Cylch gives them and signs in through Cylch with no second password; anyone
taken off it is deactivated here at once, sessions and all. Client accounts are
outside this entirely: Cylch never creates, changes, signs in or deactivates
one. These run against a real database, since the rule is about who is in it.
"""
import uuid
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import pytest

import apps.api.routers.cylch as cylch
from apps.api.tests.test_share_links_trashed_content import (  # noqa: F401  (fixtures)
    _auth, _seed, client, db,
)


def _person(db, name, **extra):
    from apps.api.models.user import User
    u = User(email=f"{name}-{uuid.uuid4().hex[:8]}@t.local", name=name, **extra)
    db.add(u); db.flush(); db.refresh(u)
    return u


@pytest.fixture
def key(client, db):
    """A real key, made the way an administrator makes one."""
    from apps.api.models.user import OrgRole
    admin = _person(db, "director", is_superadmin=True, org_role=OrgRole.admin)
    made = client.post("/integrations/cylch/key", headers=_auth(admin))
    assert made.status_code == 201
    return {"Authorization": f"Bearer {made.json()['key']}", "_admin": admin}


@pytest.fixture
def tickets():
    """Redis, for the one-time tickets: held here, and gone once read."""
    held = {}
    with patch.object(cylch, "store_cylch_ticket", side_effect=held.__setitem__), \
         patch.object(cylch, "take_cylch_ticket", side_effect=lambda h: held.pop(h, None)):
        yield held


def _headers(key):
    return {"Authorization": key["Authorization"]}


def _list(key, *extra):
    """A list that always carries the director, as Cylch's always will."""
    return {"people": [{"email": key["_admin"].email, "name": "Director", "org_role": "admin"}, *extra]}


def _ticket_of(url):
    parsed = urlparse(url)
    return parsed.fragment.removeprefix("ticket="), parse_qs(parsed.query)


def _user(db, email):
    from apps.api.models.user import User
    db.expire_all()
    return db.query(User).filter(User.email == email).one()


# ── The list ──────────────────────────────────────────────────────────────────

def test_someone_on_cylchs_list_gets_an_account_with_cylchs_role(client, db, key):
    sent = client.put("/integrations/cylch/people", headers=_headers(key),
                      json=_list(key, {"email": "New.Editor@Stori.Test", "name": "New Editor", "org_role": "member"}))
    assert sent.status_code == 200
    assert sent.json()["added"] == 1
    made = _user(db, "new.editor@stori.test")
    assert (made.org_role.value, made.is_superadmin, made.status.value, made.is_client) == ("member", False, "active", False)
    assert made.password_hash is None  # nothing to sign in with here but Cylch


def test_a_change_of_role_in_cylch_is_a_change_of_role_here(client, db, key):
    from apps.api.models.user import OrgRole
    editor = _person(db, "editor", org_role=OrgRole.member)
    promote = _list(key, {"email": editor.email, "name": "Editor", "org_role": "admin"})
    assert client.put("/integrations/cylch/people", headers=_headers(key), json=promote).json()["updated"] == 1
    assert (_user(db, editor.email).org_role, _user(db, editor.email).is_superadmin) == (OrgRole.admin, True)

    demote = _list(key, {"email": editor.email, "name": "Editor", "org_role": "member"})
    client.put("/integrations/cylch/people", headers=_headers(key), json=demote)
    assert (_user(db, editor.email).org_role, _user(db, editor.email).is_superadmin) == (OrgRole.member, False)


def test_someone_taken_off_the_list_loses_this_app_at_once(client, db, key):
    from apps.api.models.user import OrgRole
    w = _seed(db)
    leaver = _person(db, "leaver", org_role=OrgRole.manager)
    session = _auth(leaver)
    assert client.get(f"/projects/{w.project.id}", headers=session).status_code == 200

    gone = client.put("/integrations/cylch/people", headers=_headers(key), json=_list(key))
    assert gone.json()["deactivated"] >= 1
    assert _user(db, leaver.email).status.value == "deactivated"
    # The session they already had is refused from the next request.
    assert client.get(f"/projects/{w.project.id}", headers=session).status_code in (401, 403)
    assert client.get("/projects", headers=session).status_code in (401, 403)


def test_someone_who_comes_back_onto_the_list_is_let_back_in(client, db, key):
    from apps.api.models.user import OrgRole, UserStatus
    returner = _person(db, "returner", org_role=OrgRole.member, status=UserStatus.deactivated)
    back = _list(key, {"email": returner.email, "name": "Returner", "org_role": "member"})
    assert client.put("/integrations/cylch/people", headers=_headers(key), json=back).json()["reactivated"] == 1
    assert _user(db, returner.email).status == UserStatus.active


def test_people_outside_the_organisation_are_not_cylchs_to_remove(client, db, key):
    # A freelancer added by hand to one project holds no organisation role.
    freelancer = _person(db, "freelancer")
    client.put("/integrations/cylch/people", headers=_headers(key), json=_list(key))
    assert _user(db, freelancer.email).status.value == "active"


def test_client_accounts_are_never_touched(client, db, key, tickets):
    from apps.api.models.user import OrgRole
    a_client = _person(db, "client", is_client=True)
    # Even one wrongly holding a role, and even when Cylch names it.
    stray = _person(db, "stray", is_client=True, org_role=OrgRole.member)
    named = _list(key, {"email": a_client.email, "name": "Client", "org_role": "admin"})
    sent = client.put("/integrations/cylch/people", headers=_headers(key), json=named).json()
    assert sent["clients_skipped"] == [a_client.email]
    assert (_user(db, a_client.email).org_role, _user(db, a_client.email).is_superadmin) == (None, False)
    assert _user(db, stray.email).status.value == "active"

    refused = client.post("/integrations/cylch/sign-in", headers=_headers(key),
                          json={"email": a_client.email, "name": "Client", "org_role": "member"})
    assert refused.status_code == 409
    assert tickets == {}


def test_a_list_with_no_administrator_changes_nothing(client, db, key):
    from apps.api.models.user import OrgRole
    editor = _person(db, "editor", org_role=OrgRole.member)
    for people in ([], [{"email": editor.email, "name": "Editor", "org_role": "member"}]):
        sent = client.put("/integrations/cylch/people", headers=_headers(key), json={"people": people})
        assert sent.status_code == 422
    assert _user(db, editor.email).status.value == "active"
    assert _user(db, key["_admin"].email).status.value == "active"


# ── Signing in ────────────────────────────────────────────────────────────────

def test_cylch_signs_a_person_in_with_a_one_time_ticket(client, db, key, tickets):
    w = _seed(db)
    asked = client.post("/integrations/cylch/sign-in", headers=_headers(key),
                        json={"email": "amy@stori.test", "name": "Amy", "org_role": "member", "next": f"/projects/{w.project.id}"})
    assert asked.status_code == 200
    ticket, query = _ticket_of(asked.json()["url"])
    assert query["next"] == [f"/projects/{w.project.id}"]
    # The ticket itself is not what is kept.
    assert ticket not in tickets and len(tickets) == 1

    signed_in = client.post("/auth/cylch/exchange", json={"ticket": ticket})
    assert signed_in.status_code == 200
    session = {"Authorization": f"Bearer {signed_in.json()['access_token']}"}
    assert client.get("/auth/me", headers=session).json()["email"] == "amy@stori.test"
    assert client.get(f"/projects/{w.project.id}", headers=session).status_code == 200

    # Once only.
    assert client.post("/auth/cylch/exchange", json={"ticket": ticket}).status_code == 401


def test_a_ticket_for_someone_since_removed_is_refused(client, db, key, tickets):
    asked = client.post("/integrations/cylch/sign-in", headers=_headers(key),
                        json={"email": "temp@stori.test", "name": "Temp", "org_role": "member"})
    ticket, _ = _ticket_of(asked.json()["url"])
    client.put("/integrations/cylch/people", headers=_headers(key), json=_list(key))
    assert client.post("/auth/cylch/exchange", json={"ticket": ticket}).status_code == 401


@pytest.mark.parametrize("bad", ["https://evil.example/x", "//evil.example", "projects", "/a\\b", None])
def test_sign_in_only_ever_lands_inside_this_app(client, db, key, tickets, bad):
    asked = client.post("/integrations/cylch/sign-in", headers=_headers(key),
                        json={"email": "amy@stori.test", "name": "Amy", "org_role": "member", "next": bad})
    _, query = _ticket_of(asked.json()["url"])
    assert query["next"] == ["/projects"]


def test_these_routes_need_the_key_and_a_session_is_not_one(client, db, key, tickets):
    admin = _auth(key["_admin"])
    body = {"email": "x@stori.test", "name": "X", "org_role": "admin"}
    for headers in ({}, admin, {"Authorization": "Bearer " + cylch.KEY_PREFIX + "wrong"}):
        assert client.post("/integrations/cylch/sign-in", headers=headers, json=body).status_code == 401
        assert client.put("/integrations/cylch/people", headers=headers, json={"people": [body]}).status_code == 401
        assert client.put("/integrations/cylch/home", headers=headers, json={"url": "https://cylch.test"}).status_code == 401
    assert client.post("/auth/cylch/exchange", json={"ticket": "t" * 43}).status_code == 401


# ── The button on the sign-in page ────────────────────────────────────────────

def test_the_sign_in_page_offers_cylch_only_once_cylch_has_said_where_it_is(client, db, key):
    assert client.get("/auth/cylch").json() == {"sign_in_url": None}
    assert client.put("/integrations/cylch/home", headers=_headers(key), json={"url": "https://cylch.stori.test/"}).status_code == 204
    assert client.get("/auth/cylch").json() == {"sign_in_url": "https://cylch.stori.test/adborth/sign-in"}

    # Removing the key takes the button away with it.
    client.delete("/integrations/cylch/key", headers=_auth(key["_admin"]))
    assert client.get("/auth/cylch").json() == {"sign_in_url": None}


@pytest.mark.parametrize("url", ["http://cylch.stori.test", "javascript:alert(1)", "https://x.test/\"onload=", "ftp://x.test"])
def test_cylchs_address_has_to_be_a_plain_https_one(client, db, key, url):
    assert client.put("/integrations/cylch/home", headers=_headers(key), json={"url": url}).status_code == 422
