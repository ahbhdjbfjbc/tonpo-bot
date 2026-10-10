from datetime import datetime, timedelta, timezone

from services.signal_time import validate_signal_timestamp


def test_timestamp_policy_accepts_recent_timestamp_and_normalizes_to_utc():
    now = datetime(2026, 10, 10, 10, 0, tzinfo=timezone.utc)
    parsed, status = validate_signal_timestamp(
        now.timestamp() - 60, now=now, max_age_seconds=300, max_future_skew_seconds=30
    )
    assert status is None
    assert parsed == now - timedelta(seconds=60)
    assert parsed.tzinfo == timezone.utc


def test_timestamp_policy_rejects_stale_future_and_invalid_timestamps():
    now = datetime(2026, 10, 10, 10, 0, tzinfo=timezone.utc)
    for value, expected in (
        (now - timedelta(seconds=301), "stale_signal"),
        (now + timedelta(seconds=31), "future_signal"),
        (float("nan"), "invalid_timestamp"),
        (True, "invalid_timestamp"),
        ("not-a-time", "invalid_timestamp"),
    ):
        _parsed, status = validate_signal_timestamp(
            value, now=now, max_age_seconds=300, max_future_skew_seconds=30
        )
        assert status == expected
