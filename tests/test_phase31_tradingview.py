"""PHASE 31 TradingView safety and contract tests; external systems are mocked."""
from types import SimpleNamespace

import pytest

from web.api.webhooks import _normalize_symbol, _public_error, _timestamp
from web.schemas import TradingViewSignalSchema


def test_webhook_schema_never_accepts_payload_user_identity():
    assert "user_id" not in TradingViewSignalSchema.model_fields


def test_payload_prices_reject_nan_and_infinity():
    with pytest.raises(ValueError):
        TradingViewSignalSchema(
            symbol="EURUSD", action="BUY", stop_loss="nan", take_profits=[1.2],
            timestamp=1, id="test-id",
        )
    with pytest.raises(ValueError):
        TradingViewSignalSchema(
            symbol="EURUSD", action="BUY", stop_loss=1.1, take_profits=["inf"],
            timestamp=1, id="test-id",
        )


def test_symbol_normalization_requires_explicit_mapping(monkeypatch):
    from config.settings import settings
    monkeypatch.setattr(settings, "ALLOWED_SYMBOLS", ["EURUSD", "XAUUSD"], raising=False)
    monkeypatch.setattr(settings, "TRADINGVIEW_SYMBOL_MAP", {"EURUSDM": "EURUSD"}, raising=False)
    assert _normalize_symbol("EURUSD") == "EURUSD"
    assert _normalize_symbol("EURUSDm") == "EURUSD"
    with pytest.raises(Exception):
        _normalize_symbol("EUR/USD")


def test_timestamp_accepts_iso_and_rejects_invalid():
    import datetime
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    assert abs(_timestamp(now) - datetime.datetime.now(datetime.timezone.utc).timestamp()) < 2
    with pytest.raises(Exception):
        _timestamp("not-a-timestamp")


def test_webhook_public_errors_never_return_internal_exception_text():
    result = _public_error({"status": "unknown", "error": "database password=do-not-return"})
    assert result == "Execution state is unknown; reconciliation is required"
    assert "password" not in result


def test_unknown_execution_requires_reconciliation_not_retry():
    from web.api.webhooks import _public_error
    assert _public_error({"status": "unknown"}) == "Execution state is unknown; reconciliation is required"
