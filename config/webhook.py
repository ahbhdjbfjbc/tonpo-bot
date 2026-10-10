"""Validation helpers for the Telegram webhook listener configuration."""
from urllib.parse import urlsplit


def validate_webhook_url(value: str | None) -> str | None:
    if not value:
        return value
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("WEBHOOK_URL must be an HTTPS URL without credentials, query, or fragment")
    try:
        parsed.port
    except ValueError as exc:
        raise ValueError("WEBHOOK_URL contains an invalid port") from exc
    return value.rstrip("/")


def require_webhook_url(enabled: bool, url: str | None) -> None:
    if enabled and not url:
        raise ValueError("WEBHOOK_URL is required when USE_WEBHOOK=true")
