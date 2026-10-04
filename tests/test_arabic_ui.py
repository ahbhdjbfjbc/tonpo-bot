import asyncio
from types import SimpleNamespace

from bot.handlers import CommandHandlers
from bot.keyboards import get_confirmation_keyboard, get_help_keyboard, get_settings_keyboard
from bot.registration import RegistrationHandler, ENTER_ACCOUNT
from bot.utils import get_user_language


class Message:
    def __init__(self):
        self.text = None
        self.reply_markup = None

    async def reply_text(self, text, **kwargs):
        self.text = text
        self.reply_markup = kwargs.get("reply_markup")
        return self


class Query:
    async def answer(self):
        pass

    async def edit_message_text(self, text, **kwargs):
        self.text = text
        self.reply_markup = kwargs.get("reply_markup")


class Context:
    def __init__(self):
        self.user_data = {}


def test_start_and_help_are_arabic(monkeypatch):
    from config.settings import settings
    monkeypatch.setattr(settings, "ADMIN_USER_IDS", [], raising=False)
    handler = CommandHandlers.__new__(CommandHandlers)
    handler.user_repo = SimpleNamespace(get_by_telegram_id=lambda user_id: None)
    user = SimpleNamespace(id=123, first_name="Test")
    update = SimpleNamespace(effective_user=user, message=Message())
    context = Context()

    asyncio.run(handler.start(update, context))
    assert "أهلًا بك" in update.message.text
    assert "/register" in update.message.text

    asyncio.run(handler.help(update, context))
    assert "أوامر Tonpo Bot" in update.message.text
    assert "التداول" in update.message.text
    assert "/trade" in update.message.text


def test_registration_prompt_and_primary_menus_are_arabic():
    handler = RegistrationHandler.__new__(RegistrationHandler)
    handler.user_repo = SimpleNamespace(get_by_telegram_id=lambda user_id: None)
    user = SimpleNamespace(id=123)
    update = SimpleNamespace(effective_user=user, message=Message())

    state = asyncio.run(handler.start(update, Context()))
    assert state == ENTER_ACCOUNT
    assert "لنبدأ إعداد حسابك" in update.message.text
    assert "معرّف حساب MT5" in update.message.text

    assert get_confirmation_keyboard().inline_keyboard[0][0].text == "✅ نعم"
    assert get_settings_keyboard().inline_keyboard[0][0].text == "⚖️ المخاطر"
    assert get_help_keyboard().inline_keyboard[0][0].text == "التداول"


def test_arabic_is_default_but_explicit_language_preference_is_preserved():
    update = SimpleNamespace(effective_user=SimpleNamespace(language_code="en-US"))
    context = Context()
    assert get_user_language(update, context) == "ar"

    context.user_data["language"] = "en"
    assert get_user_language(update, context) == "en"
