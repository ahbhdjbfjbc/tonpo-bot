"""Mocked Trading Economics integration and fail-closed regression coverage."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from urllib.error import HTTPError

import pytest

from services.news_protection import NewsDataStale, NewsProtectionService
from services.trading_economics import TradingEconomicsProvider


def _settings(monkeypatch, **values):
    from config.settings import settings
    defaults = {
        "NEWS_PROTECTION_ENABLED": True,
        "TRADING_ECONOMICS_API_KEY": "test-key-not-a-credential",
        "TRADING_ECONOMICS_BASE_URL": "https://calendar.invalid",
        "TRADING_ECONOMICS_CACHE_SECONDS": 60,
        "TRADING_ECONOMICS_STALE_AFTER_SECONDS": 300,
        "TRADING_ECONOMICS_TIMEOUT_SECONDS": 1,
        "NEWS_PRE_WINDOW_MINUTES": 30,
        "NEWS_POST_WINDOW_MINUTES": 30,
    }
    defaults.update(values)
    for key, value in defaults.items():
        monkeypatch.setattr(settings, key, value, raising=False)


def _row(importance=3, currency="USD", event_at=None):
    return {
        "CalendarId": "12345",
        "Date": (event_at or datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        "Country": "United States",
        "Event": "Test economic event",
        "Currency": currency,
        "Importance": importance,
    }


class _Response:
    status = 200

    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, limit):
        import json
        return json.dumps(self.payload).encode()


def test_trading_economics_normalizes_utc_importance_and_currency(monkeypatch):
    _settings(monkeypatch)
    import services.trading_economics as module
    monkeypatch.setattr(module, "urlopen", lambda request, timeout: _Response([_row(3, "USD")]))
    event = TradingEconomicsProvider().fetch()[0]
    assert event.impact == "high"
    assert event.importance == 3
    assert event.currency == "USD"
    assert event.event_at.tzinfo is not None


@pytest.mark.parametrize("importance, impact", [(1, "low"), (2, "medium"), (3, "high")])
def test_importance_mapping(monkeypatch, importance, impact):
    _settings(monkeypatch)
    import services.trading_economics as module
    monkeypatch.setattr(module, "urlopen", lambda request, timeout: _Response([_row(importance)]))
    assert TradingEconomicsProvider().fetch()[0].impact == impact


def test_provider_missing_key_fails_closed(monkeypatch):
    _settings(monkeypatch, TRADING_ECONOMICS_API_KEY=None)
    result = NewsProtectionService(provider=TradingEconomicsProvider()).assess("EURUSD")
    assert result["status"] == "unavailable"


def test_provider_invalid_data_fails_closed(monkeypatch):
    _settings(monkeypatch)
    import services.trading_economics as module
    monkeypatch.setattr(module, "urlopen", lambda request, timeout: _Response([{"Date": "bad"}]))
    result = NewsProtectionService(provider=TradingEconomicsProvider()).assess("EURUSD")
    assert result["status"] == "unavailable"


@pytest.mark.parametrize("status", [401, 403, 429, 500, 502, 503])
def test_http_provider_errors_fail_closed(monkeypatch, status):
    _settings(monkeypatch)
    import services.trading_economics as module
    def fail(request, timeout):
        raise HTTPError(request.full_url, status, "provider error", {}, None)
    monkeypatch.setattr(module, "urlopen", fail)
    result = NewsProtectionService(provider=TradingEconomicsProvider()).assess("EURUSD")
    assert result["status"] == "unavailable"


@pytest.mark.parametrize("symbol, currencies", [
    ("EURUSD", {"EUR", "USD"}),
    ("GBPUSDm", {"GBP", "USD"}),
    ("USDJPY.a", {"USD", "JPY"}),
])
def test_symbol_suffixes_use_base_currency_pair(monkeypatch, symbol, currencies):
    _settings(monkeypatch)
    from services.news_protection import _currencies
    assert _currencies(symbol) == currencies


def test_high_impact_window_blocks_and_then_resumes(monkeypatch):
    now = datetime.now(timezone.utc)
    _settings(monkeypatch)
    provider = SimpleNamespace(fetch=lambda: [])
    event = SimpleNamespace(event_id="1", currency="USD", impact="high", importance=3, event_at=now, title="FOMC")
    provider.fetch = lambda: [event]
    service = NewsProtectionService(provider=provider)
    assert service.assess("EURUSD", now=now)["status"] == "active"
    assert service.assess("EURUSD", now=now + timedelta(hours=2))["status"] == "inactive"


def test_refresh_failure_with_old_cache_is_stale(monkeypatch):
    _settings(monkeypatch, TRADING_ECONOMICS_CACHE_SECONDS=0, TRADING_ECONOMICS_STALE_AFTER_SECONDS=1)
    provider = TradingEconomicsProvider()
    provider._events = []
    provider._cached_at = datetime.now(timezone.utc) - timedelta(seconds=5)
    import services.trading_economics as module
    monkeypatch.setattr(module, "urlopen", lambda request, timeout: (_ for _ in ()).throw(TimeoutError()))
    with pytest.raises(NewsDataStale):
        provider.fetch()
