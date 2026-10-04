"""make obsolete local MT5 credential columns optional

Revision ID: 013
Revises: 012
"""
from alembic import op
import sqlalchemy as sa

revision = '013'
down_revision = '012'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('users') as batch:
        batch.alter_column('mt5_account_id', existing_type=sa.String(length=50), nullable=True)
        batch.alter_column('mt5_server', existing_type=sa.String(length=100), nullable=True)


def downgrade():
    # These fields are no longer required by gateway-backed accounts; do not invent values.
    pass
