import importlib.util
from pathlib import Path

import pytest

from database.models import SystemMetric


ROOT = Path(__file__).parents[1]
MIGRATIONS = ROOT / "database" / "migrations" / "versions"


def _load_migration(filename: str):
    path = MIGRATIONS / filename
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_system_metrics_orm_contract_matches_alignment_migration():
    assert SystemMetric.__table__.c.created_at.nullable is False
    indexes = {
        index.name: tuple(column.name for column in index.columns)
        for index in SystemMetric.__table__.indexes
    }
    assert indexes["ix_system_metrics_metric_name"] == ("metric_name",)
    assert indexes["idx_metric_name_date"] == ("metric_name", "created_at")

    alignment = _load_migration("025_system_metrics_schema_alignment.py")
    assert alignment.revision == "025_system_metrics_schema_alignment"
    assert alignment.down_revision == "024_trade_channel_publications"


@pytest.mark.parametrize(
    ("filename", "message"),
    [
        ("012_remove_persisted_mt5_passwords.py", "irreversible"),
        ("013_make_legacy_mt5_fields_optional.py", "NULL"),
        ("015_admin_console.py", "non-reversible"),
    ],
)
def test_irreversible_migration_downgrades_fail_loudly(filename, message):
    migration = _load_migration(filename)
    with pytest.raises(RuntimeError, match=message):
        migration.downgrade()
