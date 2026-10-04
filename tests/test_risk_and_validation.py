import pytest

from config.constants import OrderType
from core.models import TradeSignal
from core.risk_engine import RiskEngine, DrawdownCalculator
from core.validators import PriceValidator, RiskValidator, TradeValidator


def test_risk_engine_calculates_position_and_clamps_risk():
    signal = TradeSignal(OrderType.BUY, "EURUSD", 1.1, 1.095, [1.11])
    result = RiskEngine().calculate_trade(signal, balance=10000, risk_factor=0.2,
                                          user_settings={"max_risk_per_trade": 0.03})
    assert result.stop_loss_pips == 50
    assert result.risk_percentage == pytest.approx(3.0)
    assert result.position_size > 0
    assert result.potential_loss == pytest.approx(result.position_size * 50 * 10)
    assert result.is_valid


def test_drawdown_tracks_peak_to_trough():
    result = DrawdownCalculator.calculate_max_drawdown([1000, 1200, 900, 1100])
    assert result["max_drawdown"] == pytest.approx(300)
    assert result["max_drawdown_pct"] == pytest.approx(25)


@pytest.mark.parametrize("risk,valid", [(0.01, True), (0, False), (6, False)])
def test_risk_percentage_validation(risk, valid):
    assert RiskValidator.validate_risk_percentage(risk)[0] is valid


def test_price_and_spread_validation():
    assert PriceValidator.validate(1.2)[0]
    assert not PriceValidator.validate(-1)[0]
    assert PriceValidator.validate_spread(1.1, 1.1002, max_spread=0.0001)[0] is False


def test_trade_validator_rejects_wrong_stop_loss_direction():
    signal = TradeSignal(OrderType.BUY, "EURUSD", 1.1, 1.11, [1.12])
    errors = TradeValidator().validate_trade_parameters(
        signal.symbol, signal.entry, signal.stop_loss, signal.take_profits, signal.order_type
    )
    assert errors


def test_risk_service_uses_broker_tick_and_volume_constraints():
    from services.risk_service import RiskService

    signal = TradeSignal(OrderType.BUY, "EURUSD", 1.1000, 1.0990, [1.1020])
    result = RiskService().calculate_trade(
        signal, balance=10000, risk_factor=0.01,
        broker_constraints={
            "tick_size": 0.0001, "tick_value": 10,
            "volume_min": 0.1, "volume_max": 2.0, "volume_step": 0.1,
        },
    )
    assert result.position_size == pytest.approx(1.0)
    assert result.potential_loss == pytest.approx(100.0)
    assert result.risk_percentage == pytest.approx(1.0)


@pytest.mark.parametrize("balance,risk", [(0, 0.01), (10000, 0), (float("inf"), 0.01), (10000, float("nan"))])
def test_risk_service_rejects_non_finite_or_non_positive_inputs(balance, risk):
    from services.risk_service import RiskService

    signal = TradeSignal(OrderType.BUY, "EURUSD", 1.1000, 1.0990, [1.1020])
    with pytest.raises(ValueError):
        RiskService().calculate_trade(signal, balance=balance, risk_factor=risk)
