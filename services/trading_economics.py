"""Trading Economics economic-calendar adapter.

The API credential is used only to construct the outbound request. Neither
the request URL, response, nor exception details are logged or returned.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from config.settings import settings
from services.news_protection import NewsDataStale, NewsEvent, NewsProviderError, _utc


class TradingEconomicsProvider:
    provider_name = "Trading Economics"

    def __init__(self):
        self._events: list[NewsEvent] | None = None
        self._cached_at: datetime | None = None
        self._last_success: datetime | None = None
        self._last_error: str | None = None

    def _url(self, now: datetime) -> str:
        key = getattr(settings, "TRADING_ECONOMICS_API_KEY", None)
        base = str(getattr(settings, "TRADING_ECONOMICS_BASE_URL", "")).rstrip("/")
        if not key or not base:
            raise NewsProviderError("Trading Economics is not configured")
        start = (now - timedelta(days=1)).date().isoformat()
        end = (now + timedelta(days=2)).date().isoformat()
        # Trading Economics documents the c= parameter for the calendar API.
        # This value is never logged, serialized, or included in user output.
        return f"{base}/calendar/country/All/{start}/{end}?{urlencode({'c': key, 'f': 'json'})}"

    @staticmethod
    def _normalize(payload: object) -> list[NewsEvent]:
        if not isinstance(payload, list) or not payload:
            raise NewsProviderError("Trading Economics response is empty or malformed")
        labels = {1: "low", 2: "medium", 3: "high"}
        events: list[NewsEvent] = []
        for row in payload:
            if not isinstance(row, dict):
                raise NewsProviderError("Trading Economics event is malformed")
            event_at = _utc(row.get("Date"))
            event_id = str(row.get("CalendarId", "")).strip()
            currency = str(row.get("Currency", "")).upper().strip()
            title = str(row.get("Event") or row.get("Category") or "").strip()
            try:
                importance = int(row.get("Importance"))
            except (TypeError, ValueError):
                importance = 0
            if not event_at or not event_id or not currency or not title or importance not in labels:
                raise NewsProviderError("Trading Economics event is incomplete")
            events.append(NewsEvent(event_id, currency, labels[importance], event_at, title, importance))
        return events

    def _refresh(self, now: datetime) -> list[NewsEvent]:
        request = Request(self._url(now), headers={"Accept": "application/json"})
        timeout = float(getattr(settings, "TRADING_ECONOMICS_TIMEOUT_SECONDS", 5.0))
        try:
            with urlopen(request, timeout=timeout) as response:  # nosec B310 - configured provider
                if int(getattr(response, "status", 200)) >= 400:
                    raise NewsProviderError("Trading Economics returned an error")
                payload = json.loads(response.read(2_000_000).decode("utf-8"))
            events = self._normalize(payload)
        except (HTTPError, URLError, TimeoutError, UnicodeError, json.JSONDecodeError, ValueError, NewsProviderError) as exc:
            self._last_error = type(exc).__name__
            raise NewsProviderError("Trading Economics request failed") from exc
        self._events, self._cached_at, self._last_success, self._last_error = events, now, now, None
        return events

    def fetch(self) -> list[NewsEvent]:
        now = datetime.now(timezone.utc)
        cache_seconds = int(getattr(settings, "TRADING_ECONOMICS_CACHE_SECONDS", 60))
        stale_after = int(getattr(settings, "TRADING_ECONOMICS_STALE_AFTER_SECONDS", 300))
        if self._events is not None and self._cached_at is not None and (now - self._cached_at).total_seconds() <= cache_seconds:
            return list(self._events)
        try:
            return list(self._refresh(now))
        except NewsProviderError as exc:
            if self._events is not None and self._cached_at is not None and (now - self._cached_at).total_seconds() <= stale_after:
                return list(self._events)
            if self._events is not None:
                raise NewsDataStale("Trading Economics calendar data is stale") from exc
            raise

    def status(self) -> dict[str, object]:
        return {
            "provider": self.provider_name,
            "last_update": self._last_success.isoformat() if self._last_success else None,
            "available": self._events is not None and self._last_error is None,
        }
