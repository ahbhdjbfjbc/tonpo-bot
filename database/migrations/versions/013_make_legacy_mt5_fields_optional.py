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
    # Requiring these values again may fail on gateway-backed accounts and cannot
    # safely invent credentials or server identifiers for existing rows.
    raise RuntimeError(
        "Revision 013 cannot be safely reversed: legacy MT5 fields may be NULL. Use a forward-fix or restore a tested backup."
    )
