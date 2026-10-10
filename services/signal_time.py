"""Timestamp validation shared by every signal ingress and confirmation path."""
from datetime import datetime, timezone
import math
from typing import Any


def validate_signal_timestamp(
    value: Any,
    *,
    now: datetime | None = None,
    max_age_seconds: float = 300,
    max_future_skew_seconds: float = 30,
) -> tuple[datetime | None, str | None]:
    """Return an aware UTC timestamp and None, or (None, a rejection status)."""
    try:
        if isinstance(value, bool) or value is None:
            return None, "invalid_timestamp"
        if isinstance(value, datetime):
            parsed = value
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            parsed = parsed.astimezone(timezone.utc)
        elif isinstance(value, (int, float)):
            epoch = float(value)
            if not math.isfinite(epoch):
                return None, "invalid_timestamp"
            if epoch > 1e12:
                epoch /= 1000.0
            parsed = datetime.fromtimestamp(epoch, timezone.utc)
        else:
            text = str(value).strip()
            if not text:
                return None, "invalid_timestamp"
            try:
                epoch = float(text)
            except ValueError:
                parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                parsed = parsed.astimezone(timezone.utc)
            else:
                if not math.isfinite(epoch):
                    return None, "invalid_timestamp"
                if epoch > 1e12:
                    epoch /= 1000.0
                parsed = datetime.fromtimestamp(epoch, timezone.utc)
    except (OverflowError, OSError, TypeError, ValueError):
        return None, "invalid_timestamp"

    now_utc = now or datetime.now(timezone.utc)
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    age_seconds = (now_utc.astimezone(timezone.utc) - parsed).total_seconds()
    if age_seconds > max_age_seconds:
        return parsed, "stale_signal"
    if age_seconds < -max_future_skew_seconds:
        return parsed, "future_signal"
    return parsed, None
