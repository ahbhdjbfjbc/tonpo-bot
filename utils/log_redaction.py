"""Redact configured secrets from every emitted log line.

Third-party libraries (python-telegram-bot, httpx) can embed the bot token in
exception messages and request URLs. Redacting at the formatter level covers
messages, arguments and formatted tracebacks alike.
"""
from __future__ import annotations

import logging
from typing import Iterable, List, Optional

REDACTED = "[REDACTED]"
_MIN_SECRET_LENGTH = 8


class RedactingFormatter(logging.Formatter):
    """Wrap an existing formatter and replace secret values in its output."""

    def __init__(self, base: Optional[logging.Formatter], secrets: Iterable[str]):
        super().__init__()
        self._base = base or logging.Formatter()
        self._secrets: List[str] = sorted(
            {s for s in secrets if isinstance(s, str) and len(s) >= _MIN_SECRET_LENGTH},
            key=len,
            reverse=True,
        )

    def format(self, record: logging.LogRecord) -> str:
        text = self._base.format(record)
        for secret in self._secrets:
            if secret in text:
                text = text.replace(secret, REDACTED)
        return text


def install_secret_redaction(secrets: Iterable[str], logger: Optional[logging.Logger] = None) -> None:
    """Install redaction on all handlers of ``logger`` (root logger by default)."""
    target = logger or logging.getLogger()
    values = [s for s in secrets if s]
    if not values:
        return
    for handler in target.handlers:
        current = handler.formatter
        if isinstance(current, RedactingFormatter):
            values = list(set(values) | set(current._secrets))
            current = current._base
        handler.setFormatter(RedactingFormatter(current, values))


def configured_secrets() -> List[str]:
    """Collect secret settings that must never appear in logs."""
    try:
        from config.settings import settings
    except Exception:  # pragma: no cover - settings failures surface elsewhere
        return []
    names = (
        "BOT_TOKEN",
        "JWT_SECRET",
        "ENCRYPTION_KEY",
        "ADMIN_API_KEY",
        "TRADINGVIEW_WEBHOOK_SECRET",
        "PAYMENT_WEBHOOK_SECRET",
        "ETHERSCAN_API_KEY",
        "TRADING_ECONOMICS_API_KEY",
    )
    values: List[str] = []
    for name in names:
        value = getattr(settings, name, None)
        if hasattr(value, "get_secret_value"):
            value = value.get_secret_value()
        if isinstance(value, str) and value:
            values.append(value)
    return values
