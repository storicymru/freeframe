"""add client sign-off: sign_offs table and share_links.require_sign_off

A share link can ask the client to sign off the video before it can be
downloaded. Off for every existing link, and no asset has a sign-off, so
nothing changes until someone turns it on for a link.

Revision ID: a7d2e4f6b8c1
Revises: c5d1f3a7b9e2
Create Date: 2026-11-11
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'a7d2e4f6b8c1'
down_revision: Union[str, Sequence[str], None] = 'c5d1f3a7b9e2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'share_links',
        sa.Column('require_sign_off', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    # No foreign keys: the record outlives the asset, version, link and user it
    # names (see models/sign_off.py).
    op.create_table(
        'sign_offs',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('asset_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('version_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('share_link_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('asset_name', sa.String(length=255), nullable=False),
        sa.Column('version_number', sa.Integer(), nullable=False),
        sa.Column('signer_name', sa.String(length=255), nullable=False),
        sa.Column('signer_email', sa.String(length=255), nullable=False),
        sa.Column('statement', sa.Text(), nullable=False),
        sa.Column('ip_address', sa.String(length=64), nullable=True),
        sa.Column('user_agent', sa.String(length=500), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column('reopened_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('reopened_by', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('reopen_reason', sa.Text(), nullable=True),
    )
    op.create_index('ix_sign_offs_asset_id', 'sign_offs', ['asset_id'])
    op.create_index('ix_sign_offs_version_id', 'sign_offs', ['version_id'])
    op.create_index('ix_sign_offs_share_link_id', 'sign_offs', ['share_link_id'])


def downgrade() -> None:
    op.drop_index('ix_sign_offs_share_link_id', table_name='sign_offs')
    op.drop_index('ix_sign_offs_version_id', table_name='sign_offs')
    op.drop_index('ix_sign_offs_asset_id', table_name='sign_offs')
    op.drop_table('sign_offs')
    op.drop_column('share_links', 'require_sign_off')
