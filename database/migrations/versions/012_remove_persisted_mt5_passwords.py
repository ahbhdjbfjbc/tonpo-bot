"""stop persisting MT5 passwords

Revision ID: 012
Revises: 011
"""
from alembic import op
import sqlalchemy as sa

revision = '012'
down_revision = '011'
branch_labels = None
depends_on = None


def upgrade():
    # Clear any legacy values before making the column optional. New code never writes it.
    op.execute(sa.text("UPDATE users SET mt5_password = NULL"))
    with op.batch_alter_table('users') as batch:
        batch.alter_column('mt5_password', existing_type=sa.Text(), nullable=True)


def downgrade():
    # Secret values were erased in upgrade and cannot be reconstructed safely.
    raise RuntimeError(
        "Revision 012 is irreversible: persisted MT5 passwords were erased. Use a forward-fix or restore a tested backup."
    )
