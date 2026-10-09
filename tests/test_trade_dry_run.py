import asyncio
from types import SimpleNamespace
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



def test_calculate_only_is_explicitly_non_executable_without_gateway_constraints(monkeypatch):
    from gateway_client.adapter import GatewayCapabilityUnavailable
    from services.risk_service import RiskService
    from services.signal_processor import SignalProcessor

    class Connection:
        async def get_account_information(self):
            return {"balance": 10000.0, "currency": "USD"}

        async def get_symbol_price(self, symbol):
            return {"bid": 1.1000, "ask": 1.1001}

        async def get_symbol_constraints(self, symbol):
            raise GatewayCapabilityUnavailable("unsupported")

    class Executor(TradeExecutor):
        async def _get_connection(self, user_id):
            return Connection()

    user = SimpleNamespace(
        default_risk_factor=0.01,
        max_position_size=1.0,
        settings=SimpleNamespace(symbol_risk_overrides={}),
    )
    executor = Executor.__new__(Executor)
    executor.user_repo = SimpleNamespace(get_by_telegram_id=lambda user_id: user)
    executor.signal_processor = SignalProcessor()
    executor.risk_service = RiskService()

    result = asyncio.run(executor.calculate_only(101, "BUY EURUSD\nEntry 1.1000\nSL 1.0990\nTP 1.1020"))

    assert result["success"] is False
    assert result["status"] == "constraints_unavailable"
    assert result["executable"] is False
    assert "hardcoded" not in result["error"].lower()


def test_gateway_adapter_exposes_unsupported_constraints_capability_explicitly():
    from gateway_client.adapter import GatewayCapabilityUnavailable, TonpoConnectionAdapter

    adapter = TonpoConnectionAdapter.__new__(TonpoConnectionAdapter)
    try:
        asyncio.run(adapter.get_symbol_constraints("EURUSD"))
    except GatewayCapabilityUnavailable as exc:
        assert "constraints" in str(exc).lower()
    else:
        raise AssertionError("unsupported gateway capability must fail closed")
