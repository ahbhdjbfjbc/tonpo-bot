import asyncio
from types import SimpleNamespace

from telegram.ext import ConversationHandler

from bot import trading as trading_module
from bot.trading import TradingHandler


def test_calculate_preview_does_not_offer_or_start_execution(monkeypatch):
    handler = TradingHandler.__new__(TradingHandler)

    class CalculationOnlyExecutor:
        async def calculate_only(self, user_id, signal_text):
            return _successful_calculation()

    handler.trade_executor = CalculationOnlyExecutor()
    edited_messages = []

    async def capture_edit(update, context, text, **kwargs):
        edited_messages.append((text, kwargs))

    handler._edit_message = capture_edit
    context = SimpleNamespace(
        user_data={"action": "calculate", "signal_text": "BUY EURUSD"},
        bot=_ExecutionPromptMustNotBeSent(),
    )
    monkeypatch.setattr(
        trading_module,
        "format_trade_calculation",
        lambda result, show_confirmation=True: "<pre>preview</pre>",
    )

    update = SimpleNamespace(effective_user=SimpleNamespace(id=101))
    state = asyncio.run(handler._process_calculation(update, context))

    assert state == ConversationHandler.END
    assert len(edited_messages) == 1
    preview_text, kwargs = edited_messages[0]
    assert "<pre>preview</pre>" in preview_text
    assert "/trade" in preview_text
    assert "تنفيذ هذه الصفقة" not in preview_text
    assert "reply_markup" not in kwargs
    assert "calculation" not in context.user_data
    assert context.bot.messages == []


def test_calculate_context_cannot_reach_trade_execution(monkeypatch):
    handler = TradingHandler.__new__(TradingHandler)
    edited_messages = []

    async def capture_edit(update, context, text, **kwargs):
        edited_messages.append(text)

    handler._edit_message = capture_edit
    pipeline_calls = []

    class PipelineMustNotBeCreated:
        def __init__(self, *args, **kwargs):
            pipeline_calls.append("created")

    monkeypatch.setattr(trading_module, "SignalPipeline", PipelineMustNotBeCreated)
    context = SimpleNamespace(
        user_data={
            "action": "calculate",
            "calculation": _successful_calculation(),
            "signal_text": "BUY EURUSD",
        }
    )
    update = SimpleNamespace(effective_user=SimpleNamespace(id=101))

    state = asyncio.run(handler._execute_trade(update, context))

    assert state == ConversationHandler.END
    assert pipeline_calls == []
    assert edited_messages
    assert "/trade" in edited_messages[0]


class _ExecutionPromptMustNotBeSent:
    def __init__(self):
        self.messages = []

    async def send_message(self, **kwargs):
        self.messages.append(kwargs)


def _successful_calculation():
    return {
        "success": True,
        "signal": {"order_type": "BUY", "symbol": "EURUSD", "entry": 1.1},
        "calculated": {
            "stop_loss_pips": 10,
            "take_profit_pips": [20],
            "risk_percentage": 1.0,
            "position_size": 0.1,
            "potential_loss": 10,
            "potential_profits": [20],
            "total_profit": 20,
            "risk_reward_ratio": 2.0,
        },
        "account": {"balance": 10000},
    }
