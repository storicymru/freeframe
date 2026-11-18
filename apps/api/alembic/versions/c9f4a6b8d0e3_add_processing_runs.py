"""add processing_runs: how long each upload took to arrive and to process

One row per version, written best-effort beside the real work and read only by
the admin timing report. A new table and nothing else: no existing row changes.

Revision ID: c9f4a6b8d0e3
Revises: b8e3f5a7c9d2
Create Date: 2026-11-18
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'c9f4a6b8d0e3'
down_revision: Union[str, Sequence[str], None] = 'b8e3f5a7c9d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # No foreign keys: see models/processing_run.py.
    op.create_table(
        'processing_runs',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('version_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('asset_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('project_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('asset_name', sa.String(255), nullable=True),
        sa.Column('asset_type', sa.String(32), nullable=True),
        sa.Column('original_filename', sa.String(512), nullable=True),
        sa.Column('mime_type', sa.String(128), nullable=True),
        sa.Column('file_size_bytes', sa.BigInteger(), nullable=True),
        sa.Column('duration_seconds', sa.Float(), nullable=True),
        sa.Column('width', sa.Integer(), nullable=True),
        sa.Column('height', sa.Integer(), nullable=True),
        sa.Column('fps', sa.Float(), nullable=True),
        sa.Column('upload_started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('upload_completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('processing_started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('processing_completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('outcome', sa.String(16), nullable=True),
        sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.UniqueConstraint('version_id', name='uq_processing_runs_version_id'),
    )
    op.create_index('ix_processing_runs_created_at', 'processing_runs', ['created_at'])


def downgrade() -> None:
    op.drop_index('ix_processing_runs_created_at', table_name='processing_runs')
    op.drop_table('processing_runs')
