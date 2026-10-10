import asyncio
from types import SimpleNamespace

import pytest

from bot.middleware import RateLimitMiddleware
from config.settings import settings
from services.risk_limits import get_risk_limits, parse_risk_percent, risk_limits_percent


def test_risk_percent_parser_uses_configured_minimum_and_maximum(monkeypatch):
    monkeypatch.setattr(settings, "MIN_RISK_FACTOR", 0.001, raising=False)
    monkeypatch.setattr(settings, "MAX_RISK_FACTOR", 0.05, raising=False)
    monkeypatch.setattr(settings, "DEFAULT_RISK_FACTOR", 0.01, raising=False)

    assert parse_risk_percent("0.1") == pytest.approx(0.001)
    assert parse_risk_percent("5") == pytest.approx(0.05)
    assert risk_limits_percent() == pytest.approx((0.1, 5.0))
    for value in ("0.09", "5.01", "nan", "inf", "not-a-number"):
        with pytest.raises(ValueError):
            parse_risk_percent(value)


def test_risk_policy_rejects_invalid_central_configuration():
    invalid = SimpleNamespace(
        MIN_RISK_FACTOR=0.06,
        MAX_RISK_FACTOR=0.05,
        DEFAULT_RISK_FACTOR=0.01,
    )
    with pytest.raises(ValueError):
        get_risk_limits(invalid)


def test_registration_risk_callback_cannot_persist_value_above_global_maximum():
    from bot.registration import COMPLETE, RegistrationHandler

    class Query:
        data = "risk_10.0"

        async def answer(self):
            pass

        async def edit_message_text(self, text):
            self.text = text

    updates = []
    handler = RegistrationHandler.__new__(RegistrationHandler)
    handler.user_repo = SimpleNamespace(
        update_user=lambda user_id, **kwargs: updates.append((user_id, kwargs))
    )
    handler._pending_passwords = {}
    query = Query()
    update = SimpleNamespace(
        callback_query=query,
        message=None,
        effective_user=SimpleNamespace(id=55),
    )

    state = asyncio.run(handler.complete(update, SimpleNamespace(user_data={})))

    assert state == COMPLETE
    assert updates == []
    assert "5%" in query.text


def test_settings_risk_input_cannot_persist_value_above_global_maximum():
    from bot.settings import CONFIRM_UPDATE, SettingsHandler

    class Message:
        text = "10"

        def __init__(self):
            self.replies = []

        async def reply_text(self, text):
            self.replies.append(text)

    updates = []
    handler = SettingsHandler.__new__(SettingsHandler)
    handler.user_repo = SimpleNamespace(
        update_user=lambda user_id, **kwargs: updates.append((user_id, kwargs))
    )
    message = Message()
    update = SimpleNamespace(message=message)
    context = SimpleNamespace(
        user_data={"awaiting": "risk_factor", "settings_user_id": 88}
    )

    state = asyncio.run(handler.confirm_update(update, context))

    assert state == CONFIRM_UPDATE
    assert updates == []
    assert message.replies and "و5." in message.replies[0]


def test_risk_service_caps_even_when_user_settings_try_to_raise_global_maximum():
    from config.constants import OrderType
    from core.models import TradeSignal
    from services.risk_service import RiskService

    signal = TradeSignal(OrderType.BUY, "EURUSD", 1.1000, 1.0990, [1.1020])
    result = RiskService().calculate_trade(
        signal,
        balance=10000,
        risk_factor=0.20,
        user_settings={"max_risk_per_trade": 0.20},
        broker_constraints={
            "tick_size": 0.0001,
            "tick_value": 10,
            "volume_min": 0.1,
            "volume_max": 20.0,
            "volume_step": 0.1,
        },
    )
    assert result.risk_percentage == pytest.approx(5.0)


def test_web_settings_endpoint_rejects_risk_factor_above_central_maximum():
    from fastapi import HTTPException
    from web.api.settings_api import SettingsUpdate, update_settings

    user = SimpleNamespace(
        default_risk_factor=0.01,
        settings=None,
        language="ar",
        allowed_symbols=[],
        blocked_symbols=[],
    )
    db = SimpleNamespace(commit=lambda: None, refresh=lambda _user: None)

    with pytest.raises(HTTPException) as exc:
        update_settings(SettingsUpdate(default_risk_factor=0.10), user=user, db=db)

    assert exc.value.status_code == 422
    assert user.default_risk_factor == pytest.approx(0.01)


def test_rate_limiter_reads_central_configuration(monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_TRADES", 3, raising=False)
    monkeypatch.setattr(settings, "RATE_LIMIT_CALCULATIONS", 7, raising=False)
    monkeypatch.setattr(settings, "RATE_LIMIT_BALANCE", 11, raising=False)
    monkeypatch.setattr(settings, "RATE_LIMIT_POSITIONS", 13, raising=False)
    monkeypatch.setattr(settings, "RATE_LIMIT_SETTINGS", 17, raising=False)
    monkeypatch.setattr(settings, "RATE_LIMIT_DEFAULT", 19, raising=False)

    limiter = RateLimitMiddleware(cache_service=object())

    assert limiter.default_limits == {
        "trade": (3, 60),
        "calculate": (7, 60),
        "balance": (11, 60),
        "positions": (13, 60),
        "settings": (17, 60),
        "default": (19, 60),
    }


def test_rate_limiter_wrapper_handles_callback_update_and_denies_before_handler(monkeypatch):
    import services.subscription as subscription

    class NoPlan:
        def __init__(self, _session):
            pass

        def get_user_plan(self, _user_id):
            return None

    monkeypatch.setattr(subscription, "SubscriptionService", NoPlan)
    class FakeCache:
        def check_rate_limit(self, key, limit, period):
            assert key == "ratelimit:bot:404:positions"
            assert limit == 20
            assert period == 60
            return False, 12

    class CallbackQuery:
        def __init__(self):
            self.answers = []

        async def answer(self, text=None, show_alert=False):
            self.answers.append((text, show_alert))

    calls = []
    callback_query = CallbackQuery()
    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=404),
        effective_message=None,
        callback_query=callback_query,
    )

    async def handler(_update, _context):
        calls.append("called")

    wrapped = RateLimitMiddleware(FakeCache()).wrap("positions")(handler)
    asyncio.run(wrapped(update, object()))

    assert calls == []
    assert callback_query.answers == [("يرجى الانتظار 12 ثانية.", True)]


def test_protected_command_wrapper_applies_authentication_before_limit_and_handler():
    from bot.main import Bot

    order = []

    class Auth:
        def wrap(self, handler):
            async def wrapped(update, context):
                order.append("auth")
                return await handler(update, context)
            return wrapped

    class Limiter:
        def wrap(self, action):
            assert action == "trade"
            def decorator(handler):
                async def wrapped(update, context):
                    order.append("limit")
                    return await handler(update, context)
                return wrapped
            return decorator

    bot = Bot.__new__(Bot)
    bot.auth_middleware = Auth()
    bot.rate_limiter = Limiter()

    async def original(_update, _context):
        order.append("handler")

    wrapped = bot._wrap_limited_command("trade", original)
    asyncio.run(wrapped(object(), object()))

    assert order == ["auth", "limit", "handler"]
