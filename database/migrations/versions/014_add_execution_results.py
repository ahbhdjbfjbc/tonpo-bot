"""persist structured per-order results

Revision ID: 014
Revises: 013
"""
from alembic import op
import sqlalchemy as sa

revision = '014'
down_revision = '013'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('trades', sa.Column('execution_results', sa.JSON(), nullable=True))
    op.execute(sa.text("UPDATE trades SET execution_results = '[]' WHERE execution_results IS NULL"))
    with op.batch_alter_table('trades') as batch:
        batch.alter_column('execution_results', existing_type=sa.JSON(), nullable=False,
                           server_default='[]')


def downgrade():
    op.drop_column('trades', 'execution_results')
