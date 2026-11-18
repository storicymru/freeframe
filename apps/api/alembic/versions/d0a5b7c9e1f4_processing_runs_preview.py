"""processing_runs: when the quick preview was ready, and what kind

Two nullable columns on the timing log. Nothing else changes.

Revision ID: d0a5b7c9e1f4
Revises: c9f4a6b8d0e3
Create Date: 2026-11-18
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'd0a5b7c9e1f4'
down_revision: Union[str, Sequence[str], None] = 'c9f4a6b8d0e3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('processing_runs', sa.Column('preview_ready_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('processing_runs', sa.Column('preview_kind', sa.String(16), nullable=True))


def downgrade() -> None:
    op.drop_column('processing_runs', 'preview_kind')
    op.drop_column('processing_runs', 'preview_ready_at')
