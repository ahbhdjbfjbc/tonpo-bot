import asyncio
from types import SimpleNamespace

from bot.referrals import (
    REFERRAL_FEATURE_KEY,
    add_referral_attribution,
    build_referral_link,
    parse_referral_payload,
)


def test_referral_deep_link_uses_live_bot_username_and_telegram_id():
    class TelegramBot:
        async def get_me(self):
            return SimpleNamespace(username="current_bot")

    link = asyncio.run(build_referral_link(TelegramBot(), 123456))
    assert link == "https://t.me/current_bot?start=ref_123456"
    assert "token" not in link


def test_referral_start_payload_parsing_and_self_referral_rejection():
    assert parse_referral_payload(["ref_123456"], 654321) == 123456
    assert parse_referral_payload(["ref_654321"], 654321) is None
    assert parse_referral_payload(["not-a-referral"], 654321) is None
    assert parse_referral_payload(["ref_0"], 654321) is None


def test_referral_attribution_preserves_existing_and_unrelated_features():
    existing = {
        "max_trades": 10,
        REFERRAL_FEATURE_KEY: {"referrer_telegram_id": 111},
    }
    result = add_referral_attribution(existing, 222, 333)
    assert result == existing

    first_attribution = add_referral_attribution({"max_trades": 10}, 222, 333)
    assert first_attribution == {
        "max_trades": 10,
        REFERRAL_FEATURE_KEY: {"referrer_telegram_id": 222},
    }


def test_referral_attribution_persists_and_survives_subscription_downgrade():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from database.database import Base
    from database.repositories import UserRepository
    from services.subscription import SubscriptionService

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        features = add_referral_attribution(None, 111, 222)
        repo = UserRepository(session)
        repo.create_user(telegram_id=222, subscription_features=features)

        SubscriptionService(session).downgrade_user(222)
        session.expire_all()
        saved_user = repo.get_by_telegram_id(222)
        assert saved_user.subscription_features[REFERRAL_FEATURE_KEY] == {
            "referrer_telegram_id": 111
        }

    engine.dispose()


def test_start_records_first_referral_payload_for_new_user(monkeypatch):
    from bot.handlers import CommandHandlers
    from config.settings import settings

    monkeypatch.setattr(settings, "ADMIN_USER_IDS", [], raising=False)

    class Message:
        async def reply_text(self, text, **kwargs):
            self.text = text

    context = SimpleNamespace(args=["ref_123"], user_data={})
    handler = CommandHandlers.__new__(CommandHandlers)
    handler.user_repo = SimpleNamespace(get_by_telegram_id=lambda user_id: None)
    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=456, first_name="New", username="new_user"),
        message=Message(),
    )

    asyncio.run(handler.start(update, context))
    assert context.user_data["pending_referrer_telegram_id"] == 123
    assert "سيُحفظ مصدره" in update.message.text


def test_start_does_not_replace_existing_referral_for_an_existing_user(monkeypatch):
    from bot.handlers import CommandHandlers
    from config.settings import settings

    monkeypatch.setattr(settings, "ADMIN_USER_IDS", [], raising=False)

    class Message:
        async def reply_text(self, text, **kwargs):
            self.text = text

    registered_user = SimpleNamespace(
        mt5_account_id="account",
        subscription_tier="free",
    )
    handler = CommandHandlers.__new__(CommandHandlers)
    handler.user_repo = SimpleNamespace(get_by_telegram_id=lambda user_id: registered_user)
    context = SimpleNamespace(args=["ref_999"], user_data={"pending_referrer_telegram_id": 111})
    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=456, first_name="Existing"),
        message=Message(),
    )

    asyncio.run(handler.start(update, context))
    assert context.user_data["pending_referrer_telegram_id"] == 111


def test_referral_command_shows_share_button_with_deep_link():
    from bot.handlers import CommandHandlers

    class TelegramBot:
        async def get_me(self):
            return SimpleNamespace(username="current_bot")

    class Message:
        async def reply_text(self, text, **kwargs):
            self.text = text
            self.reply_markup = kwargs.get("reply_markup")

    handler = CommandHandlers.__new__(CommandHandlers)
    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=456),
        message=Message(),
    )
    asyncio.run(handler.referral(update, SimpleNamespace(bot=TelegramBot())))
    button = update.message.reply_markup.inline_keyboard[0][0]
    assert button.url == "https://t.me/current_bot?start=ref_456"
    assert "token" not in button.url


def test_registration_start_preserves_pending_referral():
    from bot.registration import ENTER_ACCOUNT, RegistrationHandler

    class Message:
        async def reply_text(self, text, **kwargs):
            self.text = text

    handler = RegistrationHandler.__new__(RegistrationHandler)
    handler.user_repo = SimpleNamespace(get_by_telegram_id=lambda user_id: None)
    context = SimpleNamespace(user_data={"pending_referrer_telegram_id": 123, "old_form": "stale"})
    update = SimpleNamespace(effective_user=SimpleNamespace(id=456), message=Message())

    state = asyncio.run(handler.start(update, context))
    assert state == ENTER_ACCOUNT
    assert context.user_data == {"pending_referrer_telegram_id": 123}


def test_profile_is_available_without_registration(monkeypatch):
    from bot.handlers import CommandHandlers

    class Message:
        async def reply_text(self, text, **kwargs):
            self.text = text
            self.kwargs = kwargs

    handler = CommandHandlers.__new__(CommandHandlers)
    handler.user_repo = SimpleNamespace(get_by_telegram_id=lambda user_id: None)
    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=456, username="new_user"),
        message=Message(),
    )
    asyncio.run(handler.profile(update, SimpleNamespace()))
    assert "حساب MT5: غير مربوط" in update.message.text
    assert "يرجى التسجيل أولًا" not in update.message.text


def test_command_menu_wiring_keeps_registration_gates_only_on_account_commands(monkeypatch):
    import bot.main as bot_main

    class FakeHandler:
        def __init__(self, command=None, callback=None, **kwargs):
            self.command = command
            self.callback = callback
            self.kwargs = kwargs

    class FakeConversation(FakeHandler):
        def __init__(self, **kwargs):
            super().__init__(callback=None)
            self.options = kwargs

    class FakeApp:
        def __init__(self):
            self.handlers = []

        def add_handler(self, handler):
            self.handlers.append(handler)

    async def stub(*args, **kwargs):
        return None

    class FakeAuth:
        def wrap(self, callback):
            async def wrapped(*args, **kwargs):
                return await callback(*args, **kwargs)

            wrapped.requires_registration = True
            return wrapped

        def wrap_admin(self, callback):
            return callback

    monkeypatch.setattr(bot_main, "CommandHandler", FakeHandler)
    monkeypatch.setattr(bot_main, "ConversationHandler", FakeConversation)
    monkeypatch.setattr(bot_main, "CallbackQueryHandler", FakeHandler)
    monkeypatch.setattr(bot_main, "MessageHandler", FakeHandler)

    bot = bot_main.Bot.__new__(bot_main.Bot)
    bot.application = FakeApp()
    bot.command_handlers = SimpleNamespace(**{
        name: stub for name in (
            "start", "help", "about", "referral", "balance", "positions",
            "history", "profile", "upgrade",
        )
    })
    bot.registration = SimpleNamespace(start=stub, cancel=stub, get_states=lambda: {})
    bot.trading = SimpleNamespace(
        start_trade=stub, start_calculate=stub, cancel=stub, get_states=lambda: {}
    )
    bot.settings_handler = SimpleNamespace(start=stub, cancel=stub, get_states=lambda: {})
    # Mirror real AdminHandler surface used by _setup_handlers (including support).
    bot.admin = SimpleNamespace(
        dashboard=stub,
        stats=stub,
        broadcast=stub,
        cancel=stub,
        get_states=lambda: {},
        open_support_ticket=stub,
    )
    bot.auth_middleware = FakeAuth()
    bot._setup_handlers()

    commands = {
        handler.command: handler
        for handler in bot.application.handlers
        if isinstance(handler, FakeHandler) and handler.command
    }
    assert {"start", "help", "about", "referral", "profile", "upgrade"} <= commands.keys()
    assert not getattr(commands["profile"].callback, "requires_registration", False)
    assert not getattr(commands["upgrade"].callback, "requires_registration", False)
    assert not getattr(commands["referral"].callback, "requires_registration", False)
    assert commands["balance"].callback.requires_registration
    assert commands["positions"].callback.requires_registration
    assert commands["history"].callback.requires_registration

    conversations = [h for h in bot.application.handlers if isinstance(h, FakeConversation)]
    registration = next(h for h in conversations if h.options["name"] == "registration")
    trade = next(h for h in conversations if h.options["name"] == "trading")
    calculate = next(h for h in conversations if h.options["name"] == "calculate")
    assert registration.options["entry_points"][0].command == "register"
    assert trade.options["entry_points"][0].callback.requires_registration
    assert calculate.options["entry_points"][0].callback.requires_registration


def test_plan_compare_callback_routes_to_existing_plan_list(monkeypatch):
    import bot.callbacks as callbacks_module
    from bot.main import Bot

    routed = []

    class FakeCallbacks:
        def __init__(self, *args):
            pass

        async def handle_plan(self, update, context, args):
            routed.append(args)

    class Query:
        data = "plan_compare"

        def __init__(self):
            self.answered = False

        async def answer(self, *args, **kwargs):
            self.answered = True

    monkeypatch.setattr(callbacks_module, "CallbackHandlers", FakeCallbacks)
    bot = Bot.__new__(Bot)
    bot.db = object()
    bot.bot = object()
    bot.execution_provider = None
    query = Query()
    update = SimpleNamespace(
        callback_query=query,
        effective_user=SimpleNamespace(id=42),
    )

    asyncio.run(bot._handle_callback(update, SimpleNamespace()))
    assert query.answered
    assert routed == [["list"]]
