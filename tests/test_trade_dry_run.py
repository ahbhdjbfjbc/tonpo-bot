import asyncio
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from services import trade_executor as trade_executor_module
from services.trade_executor import TradeExecutor
from bot.callbacks import CallbackHandlers


class ExecutionMustNotBeCalled:
    async def get_connection(self, user_id):
        raise AssertionError("gateway connection must not be requested in dry-run mode")


def test_dry_run_blocks_open_close_and_modify(monkeypatch):
    monkeypatch.setattr(trade_executor_module.settings, "TRADING_DRY_RUN", True, raising=False)
    executor = TradeExecutor.__new__(TradeExecutor)
    executor.execution_provider = ExecutionMustNotBeCalled()
    executor.mt5_manager = ExecutionMustNotBeCalled()

    async def verify():
        opened = await executor.execute_trade(101, "BUY EURUSD")
        closed = await executor.close_trade(101, "position-1")
        modified = await executor.modify_trade(101, "position-1", sl=1.0)
        for result in (opened, closed, modified):
            assert result["success"] is False
            assert result["status"] == "dry_run"

    asyncio.run(verify())


def test_dry_run_blocks_close_all_callback(monkeypatch):
    monkeypatch.setattr(trade_executor_module.settings, "TRADING_DRY_RUN", True, raising=False)

    class Query:
        message = None

        async def edit_message_text(self, text):
            self.text = text

    class Update:
        callback_query = Query()

    handler = CallbackHandlers.__new__(CallbackHandlers)
    update = Update()
    asyncio.run(handler.handle_confirmation(update, object(), ["close_all_positions", "yes"]))
    assert "وضع المحاكاة" in update.callback_query.text


def test_live_execution_fails_closed_before_gateway_when_result_column_is_missing(monkeypatch):
    monkeypatch.setattr(trade_executor_module.settings, "TRADING_DRY_RUN", False, raising=False)
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE trades (id INTEGER PRIMARY KEY)"))
    db = sessionmaker(bind=engine)()

    class MustNotConnect:
        async def get_connection(self, user_id):
            raise AssertionError("schema preflight must run before gateway access")

    executor = TradeExecutor.__new__(TradeExecutor)
    executor.db = db
    executor.execution_provider = MustNotConnect()
    executor.mt5_manager = None
    executor.pending_trades = {}
    try:
        result = asyncio.run(executor.execute_trade(101, "BUY EURUSD"))
        assert result["status"] == "blocked_schema"
        assert executor.pending_trades == {}
    finally:
        db.close()
        engine.dispose()
