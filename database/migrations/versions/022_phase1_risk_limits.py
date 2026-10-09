"""Add persisted account-wide risk limits for Phase 1.

Revision ID: 022_phase1_risk_limits
Revises: 021
"""
from alembic import op
import sqlalchemy as sa

revision = "022_phase1_risk_limits"
down_revision = "021"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("user_settings", sa.Column("max_drawdown_pct", sa.Float(), nullable=True))
    op.add_column("user_settings", sa.Column("max_open_positions", sa.Integer(), nullable=True))
    op.add_column("user_settings", sa.Column("max_open_trades", sa.Integer(), nullable=True))
    op.add_column("user_settings", sa.Column("peak_equity", sa.Float(), nullable=True))


def downgrade():
    op.drop_column("user_settings", "peak_equity")
    op.drop_column("user_settings", "max_open_trades")
    op.drop_column("user_settings", "max_open_positions")
    op.drop_column("user_settings", "max_drawdown_pct")
