"""Organisation roles: someone the organisation has given a role sees every
project without being added to each.

  * no role (how every account starts): only the projects they were added to;
  * "member" (User): editor on every project;
  * "manager" (Content manager): owner on every project, and creates projects;
  * "admin" (Administrator): as a manager, and hands the roles out.

A client account never gains anything this way, whatever its row says, and a
deleted project is as gone to the organisation as to its own members. These run
against a real database: the rule lives in queries.
"""
import uuid

import pytest

from apps.api.tests.test_share_links_trashed_content import (  # noqa: F401  (fixtures)
    _auth, _seed, _trash_project, client, db,
)


def _person(db, name, org_role=None, **extra):
    from apps.api.models.user import User
    u = User(email=f"{name}-{uuid.uuid4().hex[:8]}@t.local", name=name, org_role=org_role, **extra)
    db.add(u); db.flush(); db.refresh(u)
    return u


def _roles():
    from apps.api.models.user import OrgRole
    return OrgRole


def test_someone_with_no_role_sees_only_what_they_were_added_to(client, db):
    w = _seed(db)
    outsider = _person(db, "freelancer")
    assert client.get(f"/projects/{w.project.id}", headers=_auth(outsider)).status_code == 403
    listed = client.get("/projects", headers=_auth(outsider)).json()
    assert str(w.project.id) not in [p["id"] for p in listed]


@pytest.mark.parametrize("org_role,project_role", [("member", "editor"), ("manager", "owner"), ("admin", "owner")])
def test_an_organisation_role_opens_every_project(client, db, org_role, project_role):
    w = _seed(db)
    person = _person(db, "team", _roles()(org_role))
    opened = client.get(f"/projects/{w.project.id}", headers=_auth(person))
    assert opened.status_code == 200
    assert opened.json()["role"] == project_role
    listed = {p["id"]: p for p in client.get("/projects", headers=_auth(person)).json()}
    assert listed[str(w.project.id)]["role"] == project_role
    # And what is in it: the asset, by the same door a member uses.
    assert client.get(f"/assets/{w.A.id}", headers=_auth(person)).status_code == 200
    assert client.get(f"/projects/{w.project.id}/members", headers=_auth(person)).status_code == 200


def test_a_user_cannot_do_what_takes_an_owner_and_a_content_manager_can(client, db):
    w = _seed(db)
    user = _person(db, "user", _roles().member)
    manager = _person(db, "manager", _roles().manager)
    rename = {"name": "Renamed"}
    assert client.patch(f"/projects/{w.project.id}", json=rename, headers=_auth(user)).status_code == 403
    assert client.patch(f"/projects/{w.project.id}", json=rename, headers=_auth(manager)).status_code == 200


def test_being_added_by_name_can_raise_someone_but_never_lowers_them(db):
    from apps.api.models.project import ProjectMember, ProjectRole
    from apps.api.services.permissions import effective_member

    w = _seed(db)
    # The seeded viewer joins the organisation as a user: an editor everywhere now.
    w.viewer.org_role = _roles().member
    # The seeded owner too: still the owner of their own project.
    w.owner.org_role = _roles().member
    db.flush()
    assert effective_member(db, w.project.id, w.viewer).role == ProjectRole.editor
    assert effective_member(db, w.project.id, w.owner).role == ProjectRole.owner
    # The stored membership is not rewritten by being looked at.
    stored = db.query(ProjectMember).filter(
        ProjectMember.project_id == w.project.id, ProjectMember.user_id == w.viewer.id,
    ).one()
    assert stored.role == ProjectRole.viewer


def test_a_client_account_gains_nothing_from_a_role(client, db):
    from apps.api.services.permissions import can_create_projects, effective_member, org_project_role

    w = _seed(db)
    # A row that should never exist; the rule must hold even if one does.
    wrong = _person(db, "client", _roles().admin, is_client=True)
    assert org_project_role(wrong) is None
    assert effective_member(db, w.project.id, wrong) is None
    assert can_create_projects(wrong) is False


def test_a_deleted_project_is_gone_to_the_organisation_too(client, db):
    from apps.api.services.permissions import effective_member

    w = _seed(db)
    manager = _person(db, "manager", _roles().manager)
    _trash_project(client, db, w)
    assert effective_member(db, w.project.id, manager) is None
    assert client.get(f"/projects/{w.project.id}", headers=_auth(manager)).status_code == 404
    listed = client.get("/projects", headers=_auth(manager)).json()
    assert str(w.project.id) not in [p["id"] for p in listed]


def test_live_events_follow_the_same_rule(db):
    from apps.api.services.permissions import EVENTS_ACCESS_REVOKED, project_events_denial

    w = _seed(db)
    member = _person(db, "user", _roles().member)
    outsider = _person(db, "freelancer")
    wrong = _person(db, "client", _roles().member, is_client=True)
    assert project_events_denial(db, w.project.id, member.id, member.token_version) is None
    assert project_events_denial(db, w.project.id, outsider.id, outsider.token_version) == EVENTS_ACCESS_REVOKED
    assert project_events_denial(db, w.project.id, wrong.id, wrong.token_version) == EVENTS_ACCESS_REVOKED


@pytest.mark.parametrize("org_role,status", [(None, 403), ("member", 403), ("manager", 201), ("admin", 201)])
def test_content_managers_and_administrators_create_projects(client, db, org_role, status):
    person = _person(db, "someone", _roles()(org_role) if org_role else None)
    made = client.post("/projects", json={"name": "New"}, headers=_auth(person))
    assert made.status_code == status


def test_a_client_account_cannot_be_added_to_a_project_as_a_member(client, db):
    w = _seed(db)
    a_client = _person(db, "client", is_client=True)
    added = client.post(f"/projects/{w.project.id}/members",
                        json={"user_id": str(a_client.id), "role": "viewer"}, headers=_auth(w.owner))
    assert added.status_code == 400
    assert "client account" in added.json()["detail"]


# ── Handing the roles out ──────────────────────────────────────────────────────

def test_an_administrator_sets_a_role_and_it_takes_effect(client, db):
    w = _seed(db)
    admin = _person(db, "admin", _roles().admin, is_superadmin=True)
    person = _person(db, "new starter")
    assert client.get(f"/projects/{w.project.id}", headers=_auth(person)).status_code == 403

    given = client.patch(f"/admin/users/{person.id}/org-role", json={"org_role": "member"}, headers=_auth(admin))
    assert given.status_code == 200
    assert given.json()["org_role"] == "member"
    assert client.get(f"/projects/{w.project.id}", headers=_auth(person)).status_code == 200

    taken = client.patch(f"/admin/users/{person.id}/org-role", json={"org_role": None}, headers=_auth(admin))
    assert taken.json()["org_role"] is None
    assert client.get(f"/projects/{w.project.id}", headers=_auth(person)).status_code == 403


def test_the_administrator_role_and_the_admin_flag_stay_in_step(client, db):
    admin = _person(db, "admin", _roles().admin, is_superadmin=True)
    person = _person(db, "deputy")

    up = client.patch(f"/admin/users/{person.id}/org-role", json={"org_role": "admin"}, headers=_auth(admin)).json()
    assert (up["org_role"], up["is_superadmin"]) == ("admin", True)
    down = client.patch(f"/admin/users/{person.id}/org-role", json={"org_role": "manager"}, headers=_auth(admin)).json()
    assert (down["org_role"], down["is_superadmin"]) == ("manager", False)

    # The older Make/Remove Admin switch moves the role with it.
    made = client.patch(f"/admin/users/{person.id}/role", json={"is_admin": True}, headers=_auth(admin)).json()
    assert (made["org_role"], made["is_superadmin"]) == ("admin", True)
    removed = client.patch(f"/admin/users/{person.id}/role", json={"is_admin": False}, headers=_auth(admin)).json()
    assert (removed["org_role"], removed["is_superadmin"]) == ("manager", False)


def test_who_may_not_change_roles_and_whose(client, db):
    admin = _person(db, "admin", _roles().admin, is_superadmin=True)
    manager = _person(db, "manager", _roles().manager)
    person = _person(db, "someone")
    a_client = _person(db, "client", is_client=True)

    refused = client.patch(f"/admin/users/{person.id}/org-role", json={"org_role": "admin"}, headers=_auth(manager))
    assert refused.status_code == 403
    own = client.patch(f"/admin/users/{admin.id}/org-role", json={"org_role": "manager"}, headers=_auth(admin))
    assert own.status_code == 400
    for_client = client.patch(f"/admin/users/{a_client.id}/org-role", json={"org_role": "member"}, headers=_auth(admin))
    assert for_client.status_code == 400
    unknown = client.patch(f"/admin/users/{person.id}/org-role", json={"org_role": "boss"}, headers=_auth(admin))
    assert unknown.status_code == 422
