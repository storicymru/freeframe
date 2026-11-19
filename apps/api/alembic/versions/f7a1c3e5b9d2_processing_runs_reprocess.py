"""processing_runs: the latest reprocess of a version

Five nullable columns beside the upload's own four moments, so processing a
stored master again is timed without writing over the record of the upload.

Revision ID: f7a1c3e5b9d2
Revises: e3f6a9b2c4d5
Create Date: 2026-11-19
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'f7a1c3e5b9d2'
down_revision: Union[str, Sequence[str], None] = 'e3f6a9b2c4d5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('processing_runs', sa.Column('reprocess_requested_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('processing_runs', sa.Column('reprocess_started_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('processing_runs', sa.Column('reprocess_completed_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('processing_runs', sa.Column('reprocess_outcome', sa.String(length=16), nullable=True))
    op.add_column('processing_runs', sa.Column('reprocess_qualities', sa.String(length=64), nullable=True))


def downgrade() -> None:
    for column in ('reprocess_qualities', 'reprocess_outcome', 'reprocess_completed_at',
                   'reprocess_started_at', 'reprocess_requested_at'):
        op.drop_column('processing_runs', column)
