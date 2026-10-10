"""Align the legacy system_metrics schema with current ORM metadata.

Revision ID: 025_system_metrics_schema_alignment
Revises: 024_trade_channel_publications
"""
from alembic import op
import sqlalchemy as sa

revision = "025_system_metrics_schema_alignment"
down_revision = "024_trade_channel_publications"
branch_labels = None
depends_on = None


def _columns(bind):
    return {column["name"]: column for column in sa.inspect(bind).get_columns("system_metrics")}


def _indexes(bind):
    return {index["name"] for index in sa.inspect(bind).get_indexes("system_metrics")}


def upgrade():
    if op.get_context().as_sql:
        # Offline mode cannot inspect the database. The linear revision chain
        # guarantees the exact legacy indexes created by revision 009.
        op.execute(sa.text("UPDATE system_metrics SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL"))
        op.alter_column("system_metrics", "created_at", existing_type=sa.DateTime(), nullable=False)
        op.drop_index("ix_system_metrics_name", table_name="system_metrics")
        op.drop_index("ix_system_metrics_created", table_name="system_metrics")
        op.create_index("ix_system_metrics_metric_name", "system_metrics", ["metric_name"])
        op.create_index("idx_metric_name_date", "system_metrics", ["metric_name", "created_at"])
        return

    bind = op.get_bind()
    if "system_metrics" not in sa.inspect(bind).get_table_names():
        raise RuntimeError("system_metrics is missing; refusing to apply schema alignment")

    # Repair any legacy null timestamps before matching the non-null ORM contract.
    op.execute(sa.text("UPDATE system_metrics SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL"))
    columns = _columns(bind)
    if columns["created_at"]["nullable"]:
        with op.batch_alter_table("system_metrics") as batch:
            batch.alter_column(
                "created_at",
                existing_type=columns["created_at"]["type"],
                nullable=False,
            )

    indexes = _indexes(bind)
    for legacy in ("ix_system_metrics_name", "ix_system_metrics_created"):
        if legacy in indexes:
            op.drop_index(legacy, table_name="system_metrics")
    indexes = _indexes(bind)
    if "ix_system_metrics_metric_name" not in indexes:
        op.create_index("ix_system_metrics_metric_name", "system_metrics", ["metric_name"])
    if "idx_metric_name_date" not in indexes:
        op.create_index("idx_metric_name_date", "system_metrics", ["metric_name", "created_at"])


def downgrade():
    if op.get_context().as_sql:
        op.drop_index("ix_system_metrics_metric_name", table_name="system_metrics")
        op.drop_index("idx_metric_name_date", table_name="system_metrics")
        op.create_index("ix_system_metrics_name", "system_metrics", ["metric_name"])
        op.create_index("ix_system_metrics_created", "system_metrics", ["created_at"])
        op.alter_column("system_metrics", "created_at", existing_type=sa.DateTime(), nullable=True)
        return

    bind = op.get_bind()
    if "system_metrics" not in sa.inspect(bind).get_table_names():
        return
    indexes = _indexes(bind)
    for current in ("ix_system_metrics_metric_name", "idx_metric_name_date"):
        if current in indexes:
            op.drop_index(current, table_name="system_metrics")
    indexes = _indexes(bind)
    if "ix_system_metrics_name" not in indexes:
        op.create_index("ix_system_metrics_name", "system_metrics", ["metric_name"])
    if "ix_system_metrics_created" not in indexes:
        op.create_index("ix_system_metrics_created", "system_metrics", ["created_at"])
    columns = _columns(bind)
    if not columns["created_at"]["nullable"]:
        with op.batch_alter_table("system_metrics") as batch:
            batch.alter_column(
                "created_at",
                existing_type=columns["created_at"]["type"],
                nullable=True,
            )
