"""asset_versions: uploads that never arrived give their number back

Data only. A cancelled or reclaimed upload used to keep its version number for
as long as its soft-deleted row lasted, so the next upload skipped one: v3,
then v5. From this revision on the number is released as the upload is
disposed of (`services.versions.release_version_number`). This does the same
for the rows already there, and closes the holes they left.

A released row takes a number below zero, unique on its asset. The versions
above it move down by one for each hole beneath them, except on an asset that
has ever been signed off: a sign-off records the number in its statement, so
those keep the numbers people approved.

Only `uploading` rows in the trash are released. Those are the uploads that
were discarded or reclaimed; nothing can restore one. A `failed` version in the
trash may still hold its master and come back, so it keeps its number.

Revision ID: e3f6a9b2c4d5
Revises: d2e5f8a1b3c4
Create Date: 2026-11-19
"""
from collections import defaultdict
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'e3f6a9b2c4d5'
down_revision: Union[str, Sequence[str], None] = 'd2e5f8a1b3c4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def release_and_close(conn) -> int:
    """Release the dead uploads' numbers and close the holes. Returns how many
    versions changed number, released ones included."""
    dead = conn.execute(sa.text(
        "SELECT id, asset_id, version_number FROM asset_versions "
        "WHERE deleted_at IS NOT NULL AND processing_status = 'uploading' AND version_number > 0 "
        "ORDER BY asset_id, version_number"
    )).fetchall()
    if not dead:
        return 0

    freed = defaultdict(list)
    for row in dead:
        freed[row.asset_id].append(row.version_number)

    changed = 0
    set_number = sa.text("UPDATE asset_versions SET version_number = :n WHERE id = :id")
    for asset_id, holes in freed.items():
        lowest = conn.execute(sa.text(
            "SELECT min(version_number) FROM asset_versions WHERE asset_id = :a AND version_number < 0"
        ), {"a": asset_id}).scalar() or 0
        for row in (r for r in dead if r.asset_id == asset_id):
            lowest -= 1
            conn.execute(set_number, {"n": lowest, "id": row.id})
            changed += 1

        signed = conn.execute(sa.text(
            "SELECT 1 FROM sign_offs WHERE asset_id = :a LIMIT 1"
        ), {"a": asset_id}).first()
        if signed:
            continue
        # Lowest first, so each version moves into a number already vacated.
        kept = conn.execute(sa.text(
            "SELECT id, version_number FROM asset_versions "
            "WHERE asset_id = :a AND version_number > 0 ORDER BY version_number"
        ), {"a": asset_id}).fetchall()
        for row in kept:
            below = sum(1 for hole in holes if hole < row.version_number)
            if below:
                conn.execute(set_number, {"n": row.version_number - below, "id": row.id})
                changed += 1
    return changed


def upgrade() -> None:
    release_and_close(op.get_bind())


def downgrade() -> None:
    # The old numbers are not kept, and nothing depends on having them back.
    pass
