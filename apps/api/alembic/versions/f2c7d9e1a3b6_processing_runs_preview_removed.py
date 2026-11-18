"""processing_runs: when a replaced quick preview was cleared away

One nullable column. The sweep that removes replaced previews reads it to find
the ones still on disk, so nothing depends on a timer surviving a restart.

Revision ID: f2c7d9e1a3b6
Revises: e1b6c8d0f2a5
Create Date: 2026-11-18
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'f2c7d9e1a3b6'
down_revision: Union[str, Sequence[str], None] = 'e1b6c8d0f2a5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('processing_runs', sa.Column('preview_removed_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('processing_runs', 'preview_removed_at')
