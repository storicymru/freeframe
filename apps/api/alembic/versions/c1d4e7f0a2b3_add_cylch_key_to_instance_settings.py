"""instance_settings: a key for Cylch

Four nullable columns on the one settings row. Cylch, the studio's project app,
is where a client's logo and colours are kept; with a key it can list projects,
make one, and set a project's branding here, and nothing else. Only the SHA-256
of the key is stored, so the key itself is shown once, when it is made, and a
database dump does not hand anyone a working key. NULL, which is how every
instance starts, means there is no key and the integration's routes answer 401.

Revision ID: c1d4e7f0a2b3
Revises: a7c3e9d1b5f2
Create Date: 2026-11-18
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'c1d4e7f0a2b3'
down_revision: Union[str, Sequence[str], None] = 'a7c3e9d1b5f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('instance_settings', sa.Column('cylch_key_hash', sa.String(length=64), nullable=True))
    op.add_column('instance_settings', sa.Column('cylch_key_made_by', postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column('instance_settings', sa.Column('cylch_key_made_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('instance_settings', sa.Column('cylch_key_used_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('instance_settings', 'cylch_key_used_at')
    op.drop_column('instance_settings', 'cylch_key_made_at')
    op.drop_column('instance_settings', 'cylch_key_made_by')
    op.drop_column('instance_settings', 'cylch_key_hash')
