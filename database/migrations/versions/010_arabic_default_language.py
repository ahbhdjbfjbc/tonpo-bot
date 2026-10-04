"""make Arabic the default language for new users

Revision ID: 010
"""
from alembic import op
import sqlalchemy as sa

revision = '010'
down_revision = '009'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('users') as batch_op:
        batch_op.alter_column(
            'language_code',
            existing_type=sa.String(length=10),
            existing_nullable=True,
            server_default='ar',
        )


def downgrade():
    with op.batch_alter_table('users') as batch_op:
        batch_op.alter_column(
            'language_code',
            existing_type=sa.String(length=10),
            existing_nullable=True,
            server_default='en',
        )
