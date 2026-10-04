import asyncio
from datetime import datetime
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import Session


def test_admin_dashboard_counts_trades_without_loading_new_trade_columns():
    from bot.admin import AdminHandler

    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, is_active BOOLEAN, "
            "is_verified BOOLEAN, is_banned BOOLEAN)"
        )
        connection.exec_driver_sql(
            "INSERT INTO users (id, is_active, is_verified, is_banned) "
            "VALUES (1, 1, 1, 0)"
        )
        # Match an older deployed schema that predates execution_results.
        connection.exec_driver_sql(
            "CREATE TABLE trades (id INTEGER PRIMARY KEY, created_at DATETIME)"
        )
        connection.exec_driver_sql(
            "INSERT INTO trades (id, created_at) VALUES (1, CURRENT_TIMESTAMP)"
        )

    class Message:
        async def reply_text(self, text, **kwargs):
            self.text = text

    with Session(engine) as session:
        handler = AdminHandler.__new__(AdminHandler)
        handler.db = session
        handler.admin_ids = [1362929493]
        handler.user_repo = SimpleNamespace(get_active_users=lambda: [object()])
        handler.monitoring = SimpleNamespace(get_system_health=lambda: {
            "status": "healthy",
            "uptime": 3600,
            "system": {"error": "system metrics unavailable"},
            "database": {"active_connections": 1},
        })
        message = Message()
        result = asyncio.run(handler.dashboard(
            SimpleNamespace(callback_query=None, message=message,
                            effective_user=SimpleNamespace(id=1362929493)),
            SimpleNamespace(),
        ))

    assert result == 0
    assert "الصفقات (24 ساعة): 1" in message.text
    assert "• المعالج: غير متاح" in message.text
    assert "• الذاكرة: غير متاح" in message.text
    engine.dispose()


def test_non_admin_cannot_dispatch_admin_callback(monkeypatch):
    from bot.main import Bot
    from config.settings import settings

    monkeypatch.setattr(settings, "ADMIN_USER_IDS", [1362929493], raising=False)

    class CallbackQuery:
        data = "admin_users"

        async def answer(self, text=None, **kwargs):
            self.answer_text = text
            self.show_alert = kwargs.get("show_alert", False)

    query = CallbackQuery()
    update = SimpleNamespace(
        callback_query=query,
        effective_user=SimpleNamespace(id=999999),
    )
    instance = Bot.__new__(Bot)
    instance.admin = SimpleNamespace(
        has_permission=lambda user_id, permission: user_id in [1362929493],
        handle_callback=lambda *_: (_ for _ in ()).throw(
            AssertionError("admin callback must not be dispatched")
        ),
    )

    asyncio.run(instance._handle_callback(update, SimpleNamespace()))

    assert query.answer_text == "❌ Admin access required"
    assert query.show_alert is True


def test_non_admin_direct_admin_callback_invocation_is_denied():
    from bot.admin import AdminHandler

    class CallbackQuery:
        data = "admin_stats"

        async def answer(self, text=None, **kwargs):
            self.answer_text = text
            self.show_alert = kwargs.get("show_alert", False)

    query = CallbackQuery()
    handler = AdminHandler.__new__(AdminHandler)
    handler.admin_ids = [1362929493]
    handler._show_system_stats = lambda *_: (_ for _ in ()).throw(
        AssertionError("unauthorized admin callback must not run")
    )
    update = SimpleNamespace(
        callback_query=query,
        effective_user=SimpleNamespace(id=999999),
        effective_message=None,
    )

    asyncio.run(handler.handle_callback(update, SimpleNamespace(user_data={})))

    assert query.answer_text == "❌ Admin access required"
    assert query.show_alert is True
