"""Backend-authoritative economic news protection.

The provider is deliberately narrow: production data must come from a
configured calendar endpoint. No events are fabricated when the provider is
missing or unavailable.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Optional
from urllib.request import Request, urlopen

from config.settings import settings

logger = logging.getLogger(__name__)


class NewsProviderError(RuntimeError):
    """Safe internal error for unavailable or unusable calendar data."""


class NewsDataStale(NewsProviderError):
    """The provider could not refresh a snapshot within its safe age."""


@dataclass(frozen=True)
class NewsEvent:
    event_id: str
    currency: str
    impact: str
    event_at: datetime
    title: str = "Economic event"
    importance: int = 3


def _utc(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        result = value
    else:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            result = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            try:
                result = datetime.fromtimestamp(float(text), tz=timezone.utc)
            except (TypeError, ValueError, OverflowError):
                return None
    if result.tzinfo is None:
        return result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


def _currencies(symbol: str) -> set[str]:
    clean = "".join(ch for ch in str(symbol or "").upper() if ch.isalpha())
    return {clean[:3], clean[3:6]} if len(clean) >= 6 else {clean}


class CalendarProvider:
    """Configured JSON calendar adapter; failures are represented explicitly."""

    def fetch(self) -> list[NewsEvent]:
        url = getattr(settings, "NEWS_PROVIDER_URL", None)
        if not url:
            raise RuntimeError("news provider is not configured")
        request = Request(url, headers={"Accept": "application/json"})
        timeout = float(getattr(settings, "NEWS_PROVIDER_TIMEOUT_SECONDS", 5.0))
        with urlopen(request, timeout=timeout) as response:  # nosec B310 - explicit configured URL
            payload = json.loads(response.read(1_000_000).decode("utf-8"))
        rows = payload.get("events", []) if isinstance(payload, dict) else payload
        if not isinstance(rows, list):
            raise ValueError("calendar response is not a list")
        events: list[NewsEvent] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            event_at = _utc(row.get("event_at", row.get("timestamp", row.get("time"))))
            currency = str(row.get("currency", "")).upper().strip()
            impact = str(row.get("impact", "")).lower().strip()
            event_id = str(row.get("id", "")).strip()
            if event_at and currency and impact == "high" and event_id:
                events.append(NewsEvent(event_id, currency, impact, event_at, str(row.get("title") or "Economic event")))
        return events


class NewsProtectionService:
    def __init__(self, provider: Optional[Any] = None):
        if provider is not None:
            self.provider = provider
        else:
            from services.trading_economics import TradingEconomicsProvider
            self.provider = TradingEconomicsProvider()

    @property
    def enabled(self) -> bool:
        return bool(getattr(settings, "NEWS_PROTECTION_ENABLED", False))

    def assess(self, symbol: str, now: Optional[datetime] = None) -> dict[str, Any]:
        if not self.enabled:
            return {"status": "inactive", "reason": "News protection is disabled by configuration", "events": []}
        now_utc = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        try:
            events = self.provider.fetch()
        except Exception as exc:
            logger.warning("News calendar unavailable (%s)", type(exc).__name__)
            status = "stale" if type(exc).__name__ == "NewsDataStale" else "unavailable"
            return {
                "status": status,
                "reason": "Economic calendar data is stale; new trades are blocked" if status == "stale" else "Economic calendar unavailable; new trades are blocked",
                "events": [],
            }
        pre = timedelta(minutes=float(getattr(settings, "NEWS_PRE_WINDOW_MINUTES", 30)))
        post = timedelta(minutes=float(getattr(settings, "NEWS_POST_WINDOW_MINUTES", 30)))
        currencies = _currencies(symbol)
        active = [event for event in events if event.impact == "high" and event.currency in currencies and event.event_at - pre <= now_utc <= event.event_at + post]
        until = max((event.event_at + post for event in active), default=None)
        if active:
            return {
                "status": "active",
                "reason": "High-impact news protection is active for this symbol",
                "events": [{"id": e.event_id, "currency": e.currency, "impact": e.impact, "importance": e.importance, "event_at": e.event_at.isoformat(), "title": e.title} for e in active],
                "protection_until": until.isoformat() if until else None,
            }
        return {"status": "inactive", "reason": "No relevant high-impact event in the protection window", "events": []}

    def system_status(self) -> dict[str, Any]:
        if not self.enabled:
            return {"status": "inactive", "reason": "News protection is disabled by configuration", "events": []}
        try:
            events = self.provider.fetch()
        except Exception as exc:
            logger.warning("News calendar unavailable (%s)", type(exc).__name__)
            status = "stale" if type(exc).__name__ == "NewsDataStale" else "unavailable"
            return {"status": status, "reason": "Economic calendar data is stale; new trades are blocked" if status == "stale" else "Economic calendar unavailable; new trades are blocked", "events": []}
        now = datetime.now(timezone.utc)
        pre = timedelta(minutes=float(getattr(settings, "NEWS_PRE_WINDOW_MINUTES", 30)))
        post = timedelta(minutes=float(getattr(settings, "NEWS_POST_WINDOW_MINUTES", 30)))
        active = [e for e in events if e.impact == "high" and e.event_at - pre <= now <= e.event_at + post]
        upcoming = sorted((e for e in events if e.impact == "high" and e.event_at > now), key=lambda e: e.event_at)
        until = max((event.event_at + post for event in active), default=None)
        return {
            "status": "active" if active else "inactive",
            "reason": "High-impact news protection is active" if active else "No active high-impact protection window",
            "events": [{"id": e.event_id, "currency": e.currency, "impact": e.impact, "importance": e.importance, "event_at": e.event_at.isoformat(), "title": e.title} for e in active],
            "next_event": ({"id": upcoming[0].event_id, "currency": upcoming[0].currency, "impact": upcoming[0].impact, "importance": upcoming[0].importance, "event_at": upcoming[0].event_at.isoformat(), "title": upcoming[0].title} if upcoming else None),
            "protection_until": until.isoformat() if until else None,
            "provider": getattr(self.provider, "provider_name", "Configured calendar"),
            "last_update": (self.provider.status().get("last_update") if callable(getattr(self.provider, "status", None)) else None),
        }
