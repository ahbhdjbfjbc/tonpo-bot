"""Add per-user trading_mode (demo|live) and user_audit_logs.

Revision ID: 016
Revises: 015
Non-destructive: existing users default to demo.
"""
from alembic import op
import sqlalchemy as sa

revision = "016"
down_revision = "015"
branch_labels = None
depends_on = None


def upgrade():
    # trading_mode on users — default demo for all existing rows
    with op.batch_alter_table("users") as batch:
        batch.add_column(
            sa.Column(
                "trading_mode",
                sa.String(length=10),
                nullable=False,
                server_default="demo",
            )
        )
        batch.create_index("ix_users_trading_mode", ["trading_mode"])

    op.create_table(
        "user_audit_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("action", sa.String(80), nullable=False),
        sa.Column("old_value", sa.JSON(), nullable=True),
        sa.Column("new_value", sa.JSON(), nullable=True),
        sa.Column("source", sa.String(40), nullable=True),
        sa.Column("result", sa.String(20), nullable=False, server_default="ok"),
        sa.Column("failure_reason", sa.String(200), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_user_audit_user", "user_audit_logs", ["user_id"])
    op.create_index("ix_user_audit_telegram", "user_audit_logs", ["telegram_id"])
    op.create_index("ix_user_audit_action", "user_audit_logs", ["action"])
    op.create_index("ix_user_audit_created", "user_audit_logs", ["created_at"])


def downgrade():
    op.drop_table("user_audit_logs")
    with op.batch_alter_table("users") as batch:
        batch.drop_index("ix_users_trading_mode")
        batch.drop_column("trading_mode")
