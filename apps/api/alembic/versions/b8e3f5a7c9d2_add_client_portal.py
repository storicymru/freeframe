"""add client portal: client accounts, project_clients, portal links

A client account (users.is_client) reaches only the client portal. Which
projects it sees is in project_clients. Each project's portal runs on one
share link flagged is_portal. A sign-off made while signed in records the
account. Nothing changes for existing users, links or sign-offs.

Revision ID: b8e3f5a7c9d2
Revises: a7d2e4f6b8c1
Create Date: 2026-11-18
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'b8e3f5a7c9d2'
down_revision: Union[str, Sequence[str], None] = 'a7d2e4f6b8c1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('is_client', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('share_links', sa.Column('is_portal', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('sign_offs', sa.Column('signer_user_id', postgresql.UUID(as_uuid=True), nullable=True))
    # No foreign keys: see models/portal.py.
    op.create_table(
        'project_clients',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('project_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('invited_by', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.UniqueConstraint('project_id', 'user_id', name='uq_project_clients_project_user'),
    )
    op.create_index('ix_project_clients_project_id', 'project_clients', ['project_id'])
    op.create_index('ix_project_clients_user_id', 'project_clients', ['user_id'])


def downgrade() -> None:
    op.drop_index('ix_project_clients_user_id', table_name='project_clients')
    op.drop_index('ix_project_clients_project_id', table_name='project_clients')
    op.drop_table('project_clients')
    op.drop_column('sign_offs', 'signer_user_id')
    op.drop_column('share_links', 'is_portal')
    op.drop_column('users', 'is_client')
