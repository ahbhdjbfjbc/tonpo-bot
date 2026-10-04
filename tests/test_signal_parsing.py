import pytest

from config.constants import OrderType
from core.exceptions import InvalidSymbolError, SignalParseError
from core.models import TradeSignal
from core.parser import SignalParser, SignalEnricher, SignalNormalizer
from services.signal_processor import SignalProcessor


@pytest.fixture
def parser():
    return SignalParser()


def test_parse_standard_market_signal(parser):
    signal = parser.parse("BUY EURUSD\nEntry NOW\nSL 1.0800\nTP1 1.0900\nTP2 1.1000")
    assert signal.order_type is OrderType.BUY
    assert signal.symbol == "EURUSD"
    assert signal.entry is None
    assert signal.stop_loss == 1.08
    assert signal.take_profits == [1.09, 1.1]
    assert signal.is_market_order and signal.direction == "LONG"


def test_parse_json_pending_signal(parser):
    signal = parser.parse('{"order_type":"Sell Limit","symbol":"EURUSD","entry":1.1,"stop_loss":1.11,"take_profits":[1.09]}')
    assert signal.order_type is OrderType.SELL_LIMIT
    assert signal.is_pending_order
    assert signal.validate() == []


def test_parse_rejects_disallowed_symbol(parser):
    with pytest.raises(InvalidSymbolError, match="not allowed"):
        parser.parse("BUY NOTREAL\nEntry NOW\nSL 1.0\nTP1 2.0")


def test_signal_caps_take_profits_and_checks_direction():
    signal = TradeSignal(OrderType.BUY, "EURUSD", 1.1, 1.09, [1.11, 1.12, 1.13, 1.14])
    assert signal.take_profits == [1.11, 1.12, 1.13]
    assert signal.has_multiple_tps
    assert signal.validate() == []
    assert SignalNormalizer.normalize_symbol(" eurusd ") == "EURUSD"


def test_enricher_reports_pips_and_reward_risk():
    signal = TradeSignal(OrderType.BUY, "EURUSD", 1.1, 1.095, [1.11])
    data = SignalEnricher().add_pip_values(signal)
    rr = SignalEnricher().add_risk_reward(signal)
    assert data["sl_pips"] == pytest.approx(50)
    assert data["tp_pips"] == pytest.approx([100])
    assert rr["rr_ratio"] == pytest.approx(2.0)


def test_duplicate_detection_handles_database_order_type_strings():
    signal = TradeSignal(OrderType.BUY, "EURUSD", 1.1, 1.09, [1.11])
    restored = TradeSignal("Buy", "EURUSD", 1.2, 1.09, [1.22])

    assert SignalProcessor().is_duplicate(signal, [restored])
