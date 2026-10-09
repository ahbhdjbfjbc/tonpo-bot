"""persist safe signal decision context

Revision ID: 017
Revises: 016
"""
from alembic import op
import sqlalchemy as sa

revision = "017"
down_revision = "016"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("signal_receipts", sa.Column("rejection_reason", sa.String(255), nullable=True))
    op.add_column("signal_receipts", sa.Column("news_status", sa.String(24), nullable=True))


def downgrade():
    op.drop_column("signal_receipts", "news_status")
    op.drop_column("signal_receipts", "rejection_reason")
