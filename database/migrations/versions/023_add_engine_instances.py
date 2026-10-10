"""Add durable per-user MetaDocker engine bindings.

Revision ID: 023_add_engine_instances
Revises: 022_phase1_risk_limits
"""
from alembic import op
import sqlalchemy as sa

revision = "023_add_engine_instances"
down_revision = "022_phase1_risk_limits"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "engine_instances",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("engine_instance_id", sa.String(length=128), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False, server_default="metadocker"),
        sa.Column("endpoint", sa.String(length=255), nullable=False),
        sa.Column("account_reference", sa.String(length=100), nullable=False),
        sa.Column("api_key_ciphertext", sa.Text(), nullable=False),
        sa.Column("engine_version", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="unknown"),
        sa.Column("provision_status", sa.String(length=24), nullable=False, server_default="active"),
        sa.Column("last_health_at", sa.DateTime(), nullable=True),
        sa.Column("last_session", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("engine_instance_id", name="uq_engine_instance_id"),
        sa.UniqueConstraint("user_id", "account_reference", name="uq_engine_user_account"),
    )
    op.create_index("idx_engine_user_active", "engine_instances", ["user_id", "is_active"])


def downgrade():
    op.drop_index("idx_engine_user_active", table_name="engine_instances")
    op.drop_table("engine_instances")
