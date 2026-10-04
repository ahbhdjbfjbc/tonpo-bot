"""add durable signal idempotency receipts

Revision ID: 011
Revises: 010
"""
from alembic import op
import sqlalchemy as sa

revision = '011'
down_revision = '010'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'signal_receipts',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('source', sa.String(32), nullable=False),
        sa.Column('idempotency_key', sa.String(64), nullable=False),
        sa.Column('signal_text', sa.Text(), nullable=False),
        sa.Column('status', sa.String(24), nullable=False, server_default='received'),
        sa.Column('trade_uuid', sa.String(36), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.UniqueConstraint('user_id', 'idempotency_key', name='uq_signal_receipt_user_key'),
    )
    op.create_index('ix_signal_receipts_user_id', 'signal_receipts', ['user_id'])


def downgrade():
    op.drop_index('ix_signal_receipts_user_id', table_name='signal_receipts')
    op.drop_table('signal_receipts')
