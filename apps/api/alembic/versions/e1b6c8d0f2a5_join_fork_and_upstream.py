"""join this fork's migrations with upstream's

The fork (sign-off, client portal, processing runs) and upstream (compression
level, derived size) each added migrations after c5d1f3a7b9e2. This joins the
two lines into one head. It changes nothing itself.

Revision ID: e1b6c8d0f2a5
Revises: d0a5b7c9e1f4, f4b9c2a7d105
Create Date: 2026-11-18
"""
from typing import Sequence, Union

revision: str = 'e1b6c8d0f2a5'
down_revision: Union[str, Sequence[str], None] = ('d0a5b7c9e1f4', 'f4b9c2a7d105')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
