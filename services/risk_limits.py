"""Shared validation for the application's central risk-factor policy."""
import math
from typing import Any, Tuple

from config.settings import settings


def get_risk_limits(config: Any = settings) -> Tuple[float, float, float]:
    """Return (minimum, maximum, default) after validating configured factors."""
    try:
        minimum = float(config.MIN_RISK_FACTOR)
        maximum = float(config.MAX_RISK_FACTOR)
        default = float(config.DEFAULT_RISK_FACTOR)
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("Risk limits are not configured") from exc

    if (
        not all(math.isfinite(value) and value > 0 for value in (minimum, maximum, default))
        or minimum > maximum
        or not minimum <= default <= maximum
    ):
        raise ValueError("Configured risk limits are invalid")
    return minimum, maximum, default


def parse_risk_percent(value: Any, config: Any = settings) -> float:
    """Parse a user-entered percentage into a factor within central limits."""
    if isinstance(value, bool):
        raise ValueError("Risk percentage must be numeric")
    try:
        percent = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Risk percentage must be numeric") from exc
    if not math.isfinite(percent):
        raise ValueError("Risk percentage must be finite")

    return validate_risk_factor(percent / 100.0, config)


def validate_risk_factor(value: Any, config: Any = settings) -> float:
    """Validate a stored/API risk factor (for example, 0.01 means 1%)."""
    if isinstance(value, bool):
        raise ValueError("Risk factor must be numeric")
    try:
        factor = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Risk factor must be numeric") from exc
    if not math.isfinite(factor):
        raise ValueError("Risk factor must be finite")
    minimum, maximum, _default = get_risk_limits(config)
    if not minimum <= factor <= maximum:
        raise ValueError("Risk factor is outside configured limits")
    return factor


def risk_limits_percent(config: Any = settings) -> Tuple[float, float]:
    minimum, maximum, _default = get_risk_limits(config)
    return minimum * 100.0, maximum * 100.0
