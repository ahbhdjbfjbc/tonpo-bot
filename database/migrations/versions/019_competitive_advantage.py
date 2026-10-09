"""Persist Phase 35 signal protection context and notification idempotency.

Revision ID: 019
Revises: 018
"""
from alembic import op
import sqlalchemy as sa

revision = "019"
down_revision = "018"
branch_labels = None
depends_on = None

def upgrade():
    signal_columns = [
        ("validation_status", sa.String(24)), ("risk_status", sa.String(24)),
        ("final_decision", sa.String(32)), ("risk_reason", sa.String(255)),
        ("protection_reason", sa.String(255)), ("signal_id", sa.String(180)),
        ("account_id", sa.String(64)), ("direction", sa.String(16)),
        ("entry_price", sa.Numeric(20, 5)), ("stop_loss", sa.Numeric(20, 5)),
        ("take_profits", sa.JSON()), ("signal_timestamp", sa.DateTime()),
        ("execution_latency_ms", sa.Float()),
    ]
    for name, column_type in signal_columns:
        op.add_column("signal_receipts", sa.Column(name, column_type, nullable=True))
    op.create_index("ix_signal_receipts_signal_id", "signal_receipts", ["signal_id"])
    op.create_index("ix_signal_receipts_account_id", "signal_receipts", ["account_id"])
    settings_columns = [
        ("max_slippage", sa.Float()), ("max_volatility", sa.Float()),
        ("session_start_utc", sa.String(5)), ("session_end_utc", sa.String(5)),
        ("max_daily_loss", sa.Float()), ("max_consecutive_losses", sa.Integer()),
    ]
    for name, column_type in settings_columns:
        op.add_column("user_settings", sa.Column(name, column_type, nullable=True))
    op.add_column("user_settings", sa.Column("protection_enabled", sa.Boolean(), nullable=False, server_default="true"))
    op.add_column("notifications", sa.Column("event_key", sa.String(160), nullable=True))
    op.create_index("ix_notifications_event_key", "notifications", ["event_key"])
    op.create_index("uq_notifications_user_event", "notifications", ["user_id", "event_key"], unique=True)

def downgrade():
    op.drop_index("uq_notifications_user_event", table_name="notifications")
    op.drop_index("ix_notifications_event_key", table_name="notifications")
    op.drop_column("notifications", "event_key")
    op.drop_column("user_settings", "protection_enabled")
    for name in ("max_consecutive_losses", "max_daily_loss", "session_end_utc", "session_start_utc", "max_volatility", "max_slippage"):
        op.drop_column("user_settings", name)
    op.drop_index("ix_signal_receipts_account_id", table_name="signal_receipts")
    op.drop_index("ix_signal_receipts_signal_id", table_name="signal_receipts")
    for name in ("execution_latency_ms", "signal_timestamp", "take_profits", "stop_loss", "entry_price", "direction", "account_id", "signal_id", "protection_reason", "risk_reason", "final_decision", "risk_status", "validation_status"):
        op.drop_column("signal_receipts", name)
