"""basjoo M11 PR1 admin provision columns on tenants

Revision ID: 2026_06_17_basjoo
Revises: fecff1c3da27
Create Date: 2026-06-17 11:10:00.000000

"""
import sqlalchemy as sa
from alembic import op

import models.types


# revision identifiers, used by Alembic.
revision = '2026_06_17_basjoo'
down_revision = ('fecff1c3da27', 'a4f2d8c9b731')
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('tenants', schema=None) as batch_op:
        batch_op.add_column(sa.Column('custom_idempotency_key', sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column('created_via_admin_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('initial_password_plain', sa.String(length=64), nullable=True))


def downgrade():
    with op.batch_alter_table('tenants', schema=None) as batch_op:
        batch_op.drop_column('initial_password_plain')
        batch_op.drop_column('created_via_admin_at')
        batch_op.drop_column('custom_idempotency_key')
