"""instance_settings: where Cylch lives

One nullable column, set by Cylch itself with its key. With it the sign-in page
offers "Sign in with Cylch"; NULL, as on every existing instance, changes nothing.

Revision ID: d2e5f8a1b3c4
Revises: c1d4e7f0a2b3
Create Date: 2026-11-18
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'd2e5f8a1b3c4'
down_revision: Union[str, Sequence[str], None] = 'c1d4e7f0a2b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('instance_settings', sa.Column('cylch_url', sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column('instance_settings', 'cylch_url')
