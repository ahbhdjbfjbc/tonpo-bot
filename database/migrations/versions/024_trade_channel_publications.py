"""Add durable outbox for executed-trade channel publications.

Revision ID: 024_trade_channel_publications
Revises: 023_add_engine_instances
"""
from alembic import op
import sqlalchemy as sa

revision = "024_trade_channel_publications"
down_revision = "023_add_engine_instances"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "trade_channel_publications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("signal_receipt_id", sa.Integer(), nullable=False),
        sa.Column("trade_uuid", sa.String(length=36), nullable=True),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("order_type", sa.String(length=32), nullable=False),
        sa.Column("position_size", sa.Float(), nullable=True),
        sa.Column("entry_price", sa.Numeric(20, 5), nullable=True),
        sa.Column("stop_loss", sa.Numeric(20, 5), nullable=True),
        sa.Column("take_profits", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("telegram_message_id", sa.BigInteger(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["signal_receipt_id"], ["signal_receipts.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("signal_receipt_id", name="uq_trade_channel_receipt"),
    )
    op.create_index(
        "idx_trade_publication_status",
        "trade_channel_publications",
        ["status", "created_at"],
    )


def downgrade():
    op.drop_index("idx_trade_publication_status", table_name="trade_channel_publications")
    op.drop_table("trade_channel_publications")
