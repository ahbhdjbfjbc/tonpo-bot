import asyncio
import importlib.util
from pathlib import Path
from types import SimpleNamespace

from database.database import Base
from database.models import BotPersistenceStore


def test_bot_persistence_model_matches_its_migration():
    table = Base.metadata.tables["bot_persistence_store"]
    assert table is BotPersistenceStore.__table__
    assert set(table.columns.keys()) == {"id", "key", "value", "updated_at"}

    migration_path = (
        Path(__file__).parents[1]
        / "database"
        / "migrations"
        / "versions"
        / "002_add_bot_persistence.py"
    )
    spec = importlib.util.spec_from_file_location("persistence_migration", migration_path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    assert migration.revision == "002"
    assert migration.down_revision == "001"


def test_db_persistence_loads_and_saves_all_bot_state(monkeypatch):
    from database import db_persistence

    stored = {}

    def load(key):
        return stored.get(key)

    def save(key, value):
        stored[key] = value

    monkeypatch.setattr(db_persistence, "_load", load)
    monkeypatch.setattr(db_persistence, "_save", save)
    persistence = db_persistence.DBPersistence()

    async def exercise():
        await persistence.update_user_data(123, {"language": "en"})
        assert await persistence.get_user_data() == {123: {"language": "en"}}
        assert await persistence.get_bot_data() == {}

    asyncio.run(exercise())
    assert stored[db_persistence._USER_KEY] == {123: {"language": "en"}}


def test_start_replies_for_unregistered_user(monkeypatch):
    from bot.handlers import CommandHandlers
    import importlib

    settings_module = importlib.import_module("config.settings")

    monkeypatch.setattr(settings_module.settings, "ADMIN_USER_IDS", [], raising=False)
    handler = CommandHandlers.__new__(CommandHandlers)
    handler.user_repo = SimpleNamespace(get_by_telegram_id=lambda telegram_id: None)

    sent = []

    class Message:
        async def reply_text(self, message, **kwargs):
            sent.append((message, kwargs))

    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=42, first_name="Test"),
        message=Message(),
    )

    asyncio.run(handler.start(update, SimpleNamespace()))

    assert sent
    assert "أهلًا بك في Tonpo Bot" in sent[0][0]
    assert "/register" in sent[0][0]
