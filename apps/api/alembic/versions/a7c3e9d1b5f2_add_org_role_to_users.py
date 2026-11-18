"""users: an organisation role

One nullable column. Someone with a role sees every project without being added
to each; NULL, which is how every existing account starts, leaves a person with
only the projects they were added to, exactly as before. The accounts that are
administrators today become organisation administrators, so nobody loses
anything and the people who could already manage the instance can hand roles
out. Nobody else is given a role here: who is in the organisation is a decision
for an administrator, not for a migration.

Revision ID: a7c3e9d1b5f2
Revises: f2c7d9e1a3b6
Create Date: 2026-11-18
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'a7c3e9d1b5f2'
down_revision: Union[str, Sequence[str], None] = 'f2c7d9e1a3b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

orgrole = sa.Enum('member', 'manager', 'admin', name='userorgrole')


def upgrade() -> None:
    orgrole.create(op.get_bind(), checkfirst=True)
    op.add_column('users', sa.Column('org_role', orgrole, nullable=True))
    op.execute("UPDATE users SET org_role = 'admin' WHERE is_superadmin AND NOT is_client AND deleted_at IS NULL")


def downgrade() -> None:
    op.drop_column('users', 'org_role')
    orgrole.drop(op.get_bind(), checkfirst=True)
