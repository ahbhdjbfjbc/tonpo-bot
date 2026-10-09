"""Protect payment transaction replay identity at the database level.

Revision ID: 020
Revises: 019
"""
from alembic import op
import sqlalchemy as sa


revision = "020"
down_revision = "019"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index(
        "uq_payment_network_tx_hash",
        "payment_requests",
        ["network", "tx_hash"],
        unique=True,
        postgresql_where=sa.text("tx_hash IS NOT NULL"),
    )


def downgrade():
    op.drop_index("uq_payment_network_tx_hash", table_name="payment_requests")
