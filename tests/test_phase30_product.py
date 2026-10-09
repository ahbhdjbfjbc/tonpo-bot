"""PHASE 30 product-safety tests; external providers and broker are mocked."""
from types import SimpleNamespace
from unittest.mock import Mock

from services.news_protection import NewsProtectionService
from services.results import ResultsService
from web.api.signals import _decision_copy, _signal_timeline


def test_signal_rejection_reason_is_human_readable_without_inventing_context():
    receipt = SimpleNamespace(status="news_unavailable", rejection_reason="news_unavailable", trade_uuid=None)
    decision = _decision_copy(receipt)
    assert decision["title"] == "News data unavailable"
    assert _signal_timeline(receipt) == [
        {"key": "received", "label": "Signal received", "state": "complete"},
        {"key": "decision", "label": "Pipeline decision", "state": "news_unavailable"},
    ]


def test_unknown_reason_is_not_fabricated():
    assert _decision_copy(SimpleNamespace(status="mystery", rejection_reason="vendor_specific", trade_uuid=None)) is None


def test_news_states_are_backend_authoritative_and_fail_closed(monkeypatch):
    from config.settings import settings
    monkeypatch.setattr(settings, "NEWS_PROTECTION_ENABLED", True, raising=False)
    unavailable = NewsProtectionService(provider=Mock(fetch=Mock(side_effect=RuntimeError("provider"))))
    result = unavailable.system_status()
    assert result["status"] == "unavailable"
    assert "blocked" in result["reason"]


def test_results_empty_state_has_no_fake_metrics():
    db = Mock()
    db.query.return_value.filter.return_value.first.return_value = None
    result = ResultsService(db).results(123, "30d")
    assert result["has_data"] is False
    assert result["metrics"] == {}
    assert result["trades"] == []
    assert result["signals"] == []


def test_results_filters_are_restricted_to_supported_periods():
    assert ResultsService._cutoff("today") is not None
    assert ResultsService._cutoff("7d") is not None
    assert ResultsService._cutoff("30d") is not None
    assert ResultsService._cutoff("all") is None
