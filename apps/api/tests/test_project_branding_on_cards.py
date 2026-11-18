"""A project's branding rides on its own response, for its card and page.

The logo and two colours a project carries (set in its settings, or sent
across by Cylch) were only ever shown on the client's review pages. The
project list and the project itself now carry them too. A logo is only handed
out when it is one this project's own upload step issued. Real database: the
list is a batch query.
"""
from unittest.mock import patch

from apps.api.tests.test_share_links_trashed_content import (  # noqa: F401  (fixtures)
    _auth, _seed, client, db,
)


def _brand(db, project, **fields):
    from apps.api.models.branding import ProjectBranding
    b = ProjectBranding(project_id=project.id, **fields)
    db.add(b); db.flush()
    return b


def _signed(key):
    return f"https://files.test/{key}?signed"


def test_the_list_and_the_project_carry_its_colours_and_logo(client, db):
    from apps.api.services.owned_keys import project_logo_prefix
    w = _seed(db)
    key = f"{project_logo_prefix(w.project.id)}logo.png"
    _brand(db, w.project, primary_color="#1b365d", secondary_color="#cb2c30", logo_s3_key=key)

    with patch("apps.api.services.s3_service.generate_presigned_get_url", side_effect=_signed):
        listed = {p["id"]: p for p in client.get("/projects", headers=_auth(w.owner)).json()}
        one = client.get(f"/projects/{w.project.id}", headers=_auth(w.owner)).json()

    for got in (listed[str(w.project.id)], one):
        assert got["brand_primary_color"] == "#1b365d"
        assert got["brand_secondary_color"] == "#cb2c30"
        assert got["brand_logo_url"] == _signed(key)


def test_a_project_with_no_branding_says_so(client, db):
    w = _seed(db)
    got = client.get(f"/projects/{w.project.id}", headers=_auth(w.owner)).json()
    assert (got["brand_logo_url"], got["brand_primary_color"], got["brand_secondary_color"]) == (None, None, None)


def test_a_logo_that_is_not_this_projects_own_is_not_handed_out(client, db):
    w = _seed(db)
    # A key pointing somewhere else in storage: another project's logo, say, or footage.
    _brand(db, w.project, primary_color="#1b365d", logo_s3_key="raw/somewhere/else.mov")
    with patch("apps.api.services.s3_service.generate_presigned_get_url", side_effect=_signed):
        got = client.get(f"/projects/{w.project.id}", headers=_auth(w.owner)).json()
    assert got["brand_logo_url"] is None
    assert got["brand_primary_color"] == "#1b365d"
