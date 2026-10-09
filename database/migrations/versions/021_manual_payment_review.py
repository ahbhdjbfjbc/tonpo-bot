"""Add manual-admin payment proof and review metadata.

Revision ID: 021
Revises: 020
"""
from alembic import op
import sqlalchemy as sa

revision = "021"
down_revision = "020"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("payment_requests", sa.Column("proof_submitted_at", sa.DateTime(), nullable=True))
    op.add_column("payment_requests", sa.Column("reviewed_at", sa.DateTime(), nullable=True))
    op.add_column("payment_requests", sa.Column("reviewed_by", sa.BigInteger(), nullable=True))
    op.add_column("payment_requests", sa.Column("rejection_reason", sa.String(255), nullable=True))

def downgrade():
    op.drop_column("payment_requests", "rejection_reason")
    op.drop_column("payment_requests", "reviewed_by")
    op.drop_column("payment_requests", "reviewed_at")
    op.drop_column("payment_requests", "proof_submitted_at")
