"""Secure TradingView ingress; all decisions flow through SignalPipeline."""
from __future__ import annotations

import json
import logging
import math
import time
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from config.settings import settings
from core.models import UnifiedSignal
from services.signal_pipeline import SignalPipeline
from services.cache import CacheService, RateLimitUnavailable
import hashlib
from web.deps import get_db
from web.schemas import TradingViewSignalSchema

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])

_RATE_LIMIT = 30
_RATE_WINDOW = 60
_MAX_TIMESTAMP_SKEW = 300
_webhook_cache: CacheService | None = None


def _client_key(request: Request) -> str:
    # Do not trust a caller-controlled X-Forwarded-For header without an
    # explicitly configured trusted proxy boundary.
    return (request.client.host if request.client else "unknown")


def _get_webhook_cache() -> CacheService:
    global _webhook_cache
    if _webhook_cache is None:
        _webhook_cache = CacheService()
    return _webhook_cache


def _check_rate_limit(key: str) -> None:
    # The digest prevents raw client identifiers from becoming Redis keys.
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    try:
        allowed, retry_after = _get_webhook_cache().check_rate_limit(
            f"ratelimit:tradingview:{digest}", _RATE_LIMIT, _RATE_WINDOW
        )
    except RateLimitUnavailable as exc:
        logger.warning("TradingView rate limiting unavailable; rejecting request")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="TradingView protection unavailable",
        ) from exc
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded",
            headers={"Retry-After": str(max(1, retry_after))},
        )


def _timestamp(value: Any) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        result = float(value)
    else:
        text = str(value or "").strip()
        try:
            result = float(text)
        except ValueError:
            try:
                parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                result = parsed.timestamp()
            except ValueError as exc:
                raise HTTPException(status_code=400, detail="Invalid timestamp") from exc
    if not math.isfinite(result):
        raise HTTPException(status_code=400, detail="Invalid timestamp")
    if result > 1e12:
        result /= 1000.0
    if abs(time.time() - result) > _MAX_TIMESTAMP_SKEW:
        raise HTTPException(status_code=400, detail="Timestamp outside allowed window")
    return result


def _authenticate(secret: Optional[str]) -> bool:
    return SignalPipeline.authenticate_tradingview(secret)


def _target_user_id() -> int:
    value = getattr(settings, "TRADINGVIEW_TELEGRAM_ID", None)
    try:
        target = int(value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=503, detail="TradingView target is not configured") from exc
    if target <= 0:
        raise HTTPException(status_code=503, detail="TradingView target is not configured")
    return target


def _normalize_symbol(value: str) -> str:
    raw = str(value).upper().strip()
    mapping = getattr(settings, "TRADINGVIEW_SYMBOL_MAP", {}) or {}
    canonical = mapping.get(raw, raw)
    allowed = {str(symbol).upper() for symbol in (getattr(settings, "ALLOWED_SYMBOLS", []) or [])}
    if canonical not in allowed:
        raise HTTPException(status_code=400, detail="Unsupported or ambiguous symbol")
    return canonical


def _public_error(result: dict[str, Any]) -> Optional[str]:
    status_name = str(result.get("status") or "")
    known = {
        "invalid": "Signal validation failed",
        "unauthorized": "Trading account is unavailable",
        "rejected_subscription": "Subscription or feature access is unavailable",
        "subscription_required": "Subscription or feature access is unavailable",
        "limit_reached": "Subscription trade limit reached",
        "news_blocked": "News Protection is active",
        "news_stale": "News data is stale; new trades are blocked",
        "news_unavailable": "News data is unavailable; new trades are blocked",
        "duplicate": "Duplicate signal",
        "already_processed": "Signal was already processed",
        "unknown": "Execution state is unknown; reconciliation is required",
        "dry_run": "Dry-run mode is active; no broker order was sent",
        "blocked": "Execution safety controls blocked the signal",
        "manual_review": "Signal is awaiting confirmation",
        "confirmation_required": "Signal is awaiting confirmation",
        "cancelled": "Signal was cancelled",
    }
    return known.get(status_name)


@router.post("/tradingview")
async def tradingview_webhook(
    request: Request,
    db: Session = Depends(get_db),
    x_tradingview_secret: Optional[str] = Header(None, alias="X-TradingView-Secret"),
):
    """TradingView → authenticated ingress → shared SignalPipeline → TradeExecutor."""
    # Keep the endpoint disabled unless explicitly enabled. Return 404 so a
    # disabled ingress does not disclose whether its secret is configured.
    if not bool(getattr(settings, "ENABLE_WEBHOOKS", False)):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    if not _authenticate(x_tradingview_secret):
        logger.warning("TradingView webhook unauthorized from %s", request.client.host if request.client else "unknown")
        raise HTTPException(status_code=401, detail="Unauthorized")
    _check_rate_limit(_client_key(request))
    target_user = _target_user_id()

    raw = await request.body()
    if not raw or len(raw) > 32_768:
        raise HTTPException(status_code=400, detail="Invalid body size")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Malformed JSON") from exc
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="Payload must be a JSON object")
    forbidden_identity = {"user_id", "account_id", "subscription_id"}.intersection(data)
    if forbidden_identity:
        raise HTTPException(status_code=400, detail="Identity fields are not accepted")

    try:
        signal = TradingViewSignalSchema.model_validate(data)
        if not signal.timestamp:
            raise ValueError("timestamp is required")
        _timestamp(signal.timestamp)
        if signal.id and signal.signal_id and signal.id.strip() != signal.signal_id.strip():
            raise ValueError("signal identifiers do not match")
        external_id = (signal.id or signal.signal_id or "").strip()
        if not external_id or len(external_id) > 180:
            raise ValueError("signal identifier is required")
        symbol = _normalize_symbol(signal.symbol)
        take_profits = signal.resolved_tps()
    except HTTPException:
        raise
    except Exception as exc:
        logger.info("TradingView payload rejected (%s)", type(exc).__name__)
        raise HTTPException(status_code=400, detail="Schema validation failed") from exc

    payload_obj = {"action": signal.action, "symbol": symbol, "stop_loss": signal.stop_loss, "take_profits": take_profits}
    if signal.entry is not None:
        payload_obj["entry"] = signal.entry
    if signal.timeframe:
        payload_obj["timeframe"] = signal.timeframe
    if signal.strategy or signal.source:
        payload_obj["strategy"] = signal.strategy or signal.source
    payload_obj["id"] = external_id
    envelope = UnifiedSignal(
        source="tradingview", payload=json.dumps(payload_obj), user_id=target_user,
        external_id=external_id, received_at=datetime.now(timezone.utc).replace(tzinfo=None),
        metadata={"timestamp": signal.timestamp},
    )

    from web.runtime import get_signal_pipeline
    try:
        result = await get_signal_pipeline(db).process(envelope)
    except Exception:
        logger.error("SignalPipeline processing failed (%s)", "pipeline_error")
        raise HTTPException(status_code=500, detail="Processing failed")

    status_name = str(result.get("status") or "unknown")
    accepted = {"dry_run", "executed", "partial", "confirmation_required", "manual_review", "pending", "unknown"}
    http_status = 200 if status_name in accepted else (409 if status_name in {"duplicate", "already_processed"} else 400)
    response: dict[str, Any] = {"status": status_name, "success": bool(result.get("success")), "dry_run": bool(getattr(settings, "TRADING_DRY_RUN", True))}
    if result.get("receipt_id") is not None:
        response["receipt_id"] = result["receipt_id"]
    public_error = _public_error(result)
    if public_error:
        response["reason"] = public_error
    logger.info("TradingView signal processed target=%s symbol=%s status=%s dry_run=%s", target_user, symbol, status_name, response["dry_run"])
    return response if http_status == 200 else JSONResponse(status_code=http_status, content=response)
