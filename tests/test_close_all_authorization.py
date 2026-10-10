import asyncio
from types import SimpleNamespace

import pytest

from bot import callbacks as callbacks_module
from bot.callbacks import CallbackHandlers
from bot.keyboards import get_close_all_positions_keyboard, get_confirmation_keyboard


class Query:
    def __init__(self, data=None):
        self.data = data
        self.messages = []
        self.answers = []

    async def answer(self, text=None, show_alert=False):
        self.answers.append((text, show_alert))

    async def edit_message_text(self, text, **kwargs):
        self.messages.append((text, kwargs))


class Connection:
    def __init__(self, positions):
        self.positions = positions
        self.closed = []

    async def get_positions(self):
        return self.positions

    async def close_position(self, position_id):
        self.closed.append(position_id)
        return True


class Provider:
    def __init__(self, connection):
        self.connection = connection
        self.users_requested = []

    async def get_connection(self, user_id):
        self.users_requested.append(user_id)
        return self.connection


def _handler(user, provider):
    handler = CallbackHandlers.__new__(CallbackHandlers)
    handler.user_repo = SimpleNamespace(get_by_telegram_id=lambda user_id: user)
    handler.execution_provider = provider
    handler.db = object()
    handler.bot = object()
    return handler


def _user(*, active=True, banned=False, verified=True, credentials=True):
    return SimpleNamespace(
        is_active=active,
        is_banned=banned,
        is_verified=verified,
        has_gateway_credentials=credentials,
    )


@pytest.mark.parametrize(
    "user",
    [
        None,
        _user(active=False),
        _user(banned=True),
        _user(verified=False),
    ],
)
def test_close_all_confirmation_denies_ineligible_users_before_gateway(user, monkeypatch):
    monkeypatch.setattr(callbacks_module.settings, "TRADING_DRY_RUN", False, raising=False)
    connection = Connection([{"id": "p1"}])
    provider = Provider(connection)
    handler = _handler(user, provider)
    query = Query("position_close_all:yes")
    update = SimpleNamespace(
        callback_query=query,
        effective_user=SimpleNamespace(id=101),
    )

    asyncio.run(
        handler.handle_confirmation(
            update,
            SimpleNamespace(user_data={}),
            ["close_all_positions", "yes"],
        )
    )

    assert provider.users_requested == []
    assert connection.closed == []
    assert query.messages
    assert "غير مصرح" in query.messages[-1][0]


def test_close_all_confirmation_closes_only_positions_from_own_connection(monkeypatch):
    monkeypatch.setattr(callbacks_module.settings, "TRADING_DRY_RUN", False, raising=False)
    connection = Connection([{"id": "p1"}, {"id": "p2"}])
    provider = Provider(connection)
    handler = _handler(_user(), provider)
    query = Query("position_close_all:yes")
    update = SimpleNamespace(
        callback_query=query,
        effective_user=SimpleNamespace(id=202),
    )

    asyncio.run(
        handler.handle_confirmation(
            update,
            SimpleNamespace(user_data={}),
            ["close_all_positions", "yes"],
        )
    )

    assert provider.users_requested == [202]
    assert connection.closed == ["p1", "p2"]
    assert "أُغلقت 2 صفقات" in query.messages[-1][0]


def test_confirmation_keyboard_uses_dedicated_close_all_route_and_keeps_legacy_route():
    close_all = get_confirmation_keyboard("close_all_positions").inline_keyboard[0]
    assert close_all[0].callback_data == "position_close_all:yes"
    assert close_all[1].callback_data == "position_close_all:no"

    legacy = get_confirmation_keyboard().inline_keyboard[0]
    assert legacy[0].callback_data == "confirm_yes"
    assert legacy[1].callback_data == "confirm_no"

    assert (
        get_close_all_positions_keyboard().inline_keyboard[0][0].callback_data
        == "position_close_all"
    )


def test_main_callback_router_dispatches_close_all_without_intercepting_registration(monkeypatch):
    import bot.callbacks as callbacks_package
    from bot.main import Bot

    calls = []

    class CallbackSpy:
        def __init__(self, *args):
            pass

        async def handle_position(self, update, context, args):
            calls.append(("position", args))

        async def handle_confirmation(self, update, context, args):
            calls.append(("confirmation", args))

    monkeypatch.setattr(callbacks_package, "CallbackHandlers", CallbackSpy)
    bot = Bot.__new__(Bot)
    bot.user_repo = SimpleNamespace(get_by_telegram_id=lambda user_id: _user())
    bot.db = object()
    bot.bot = object()
    bot.execution_provider = object()
    bot.registration = SimpleNamespace(
        confirm_credentials=lambda update, context: _record_registration(calls)
    )
    context = SimpleNamespace(user_data={})

    async def dispatch(data):
        query = Query(data)
        update = SimpleNamespace(
            callback_query=query,
            effective_user=SimpleNamespace(id=303),
        )
        await bot._handle_callback(update, context)
        return query

    asyncio.run(dispatch("position_close_all"))
    asyncio.run(dispatch("position_close_all:yes"))
    asyncio.run(dispatch("confirm_yes"))

    assert ("position", ["close_all"]) in calls
    assert ("confirmation", ["close_all_positions", "yes"]) in calls
    assert ("registration", ["confirm_yes"]) in calls


async def _record_registration(calls):
    calls.append(("registration", ["confirm_yes"]))
